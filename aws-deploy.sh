#!/bin/bash
set -e
# StockAI AWS EC2 — FRESH DEPLOY: creates new t3.medium, builds & starts all services
# Usage: bash aws-deploy.sh
# Prerequisites: aws cli authenticated, .env in repo root, execution/execution-bin exists

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'

if ! aws sts get-caller-identity &>/dev/null; then
  echo -e "${RED}AWS CLI not authenticated. Run: aws sso login${NC}"
  exit 1
fi

if [ ! -f ".env" ]; then
  echo -e "${RED}.env not found in repo root${NC}"
  exit 1
fi

if [ ! -f "execution/execution-bin" ]; then
  echo -e "${RED}execution/execution-bin not found — build locally first${NC}"
  exit 1
fi

KEY_NAME="${KEY_NAME:-stockai-key}"
SG_NAME="stockai-sg-$(date +%s)"
INSTANCE_NAME="stockai-$(date +%Y%m%d-%H%M)"
REGION="${AWS_REGION:-us-east-1}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.medium}"
EBS_SIZE="${EBS_SIZE:-20}"

echo -e "${GREEN}=== StockAI AWS EC2 Deploy ===${NC}"
echo "Instance: $INSTANCE_NAME | Type: $INSTANCE_TYPE | EBS: ${EBS_SIZE}GB | Region: $REGION"

# ── 1. Key pair ──
echo -e "\n${CYAN}>>> Creating key pair...${NC}"
aws ec2 describe-key-pairs --key-names "$KEY_NAME" --region "$REGION" &>/dev/null 2>&1 \
  && echo "  Using existing key: $KEY_NAME" \
  || { aws ec2 create-key-pair --key-name "$KEY_NAME" --query 'KeyMaterial' --output text --region "$REGION" > "${KEY_NAME}.pem"
       chmod 400 "${KEY_NAME}.pem"; echo "  Created: ${KEY_NAME}.pem"; }

# ── 2. Security group ──
echo -e "${CYAN}>>> Creating security group...${NC}"
SG_ID=$(aws ec2 create-security-group --group-name "$SG_NAME" --description "StockAI" --region "$REGION" --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 22 --cidr 0.0.0.0/0 --region "$REGION"
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 8000 --cidr 0.0.0.0/0 --region "$REGION"
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 8080 --cidr 0.0.0.0/0 --region "$REGION"
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 9001 --cidr 0.0.0.0/0 --region "$REGION"
echo "  SG: $SG_ID (ports 22, 8000, 8080, 9001)"

# ── 3. User-data (auto-runs on boot) ──
USER_DATA=$(cat <<'EOF' | base64 -w0
#!/bin/bash
exec > /var/log/stockai-userdata.log 2>&1
set -e
export HOME=/root
curl -sSL https://raw.githubusercontent.com/UmairBaig8/StockAI/main/install.sh | bash
EOF
)

# ── 4. Launch EC2 ──
echo -e "${CYAN}>>> Launching $INSTANCE_TYPE with ${EBS_SIZE}GB EBS...${NC}"
AMI_ID=$(aws ec2 describe-images --owners amazon \
  --filters "Name=name,Values=al2023-ami-2023*-x86_64" \
  --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' --output text --region "$REGION")

INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type "$INSTANCE_TYPE" \
  --key-name "$KEY_NAME" \
  --security-group-ids "$SG_ID" \
  --user-data "$USER_DATA" \
  --block-device-mappings "[{\"DeviceName\":\"/dev/xvda\",\"Ebs\":{\"VolumeSize\":${EBS_SIZE},\"VolumeType\":\"gp3\",\"DeleteOnTermination\":true}}]" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
  --query 'Instances[0].InstanceId' \
  --output text --region "$REGION")

echo "  Instance: $INSTANCE_ID ($INSTANCE_NAME)"

# ── 5. Wait for running ──
echo -e "${CYAN}>>> Waiting for instance (boot + Docker + build ~8 min)...${NC}"
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"
PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text --region "$REGION")
echo "  Public IP: $PUBLIC_IP"

# ── 6. Wait for SSH ──
echo -e "${CYAN}>>> Waiting for SSH...${NC}"
for i in $(seq 1 60); do
  if ssh -i "${KEY_NAME}.pem" -o StrictHostKeyChecking=no -o ConnectTimeout=5 ec2-user@"$PUBLIC_IP" echo "SSH ready" 2>/dev/null; then
    break
  fi
  echo -n "."
  sleep 5
done

# ── 7. Copy .env + execution-bin, install compose v2 ──
echo -e "\n${CYAN}>>> Copying .env + execution-bin...${NC}"
scp -i "${KEY_NAME}.pem" -o StrictHostKeyChecking=no .env ec2-user@"$PUBLIC_IP":/tmp/stockai-env
scp -i "${KEY_NAME}.pem" -o StrictHostKeyChecking=no execution/execution-bin ec2-user@"$PUBLIC_IP":/tmp/execution-bin
ssh -i "${KEY_NAME}.pem" -o StrictHostKeyChecking=no ec2-user@"$PUBLIC_IP" 'sudo bash -c "
cp /tmp/stockai-env /root/stockai/.env && chmod 600 /root/stockai/.env
cp /tmp/execution-bin /root/stockai/execution/execution-bin && chmod +x /root/stockai/execution/execution-bin
mkdir -p /usr/local/lib/docker/cli-plugins
curl -sL https://github.com/docker/compose/releases/download/v2.40.2/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
"'
echo -e "${GREEN}  Done${NC}"

# ── 8. Build & start ──
echo -e "\n${CYAN}>>> Building & starting services...${NC}"
ssh -i "${KEY_NAME}.pem" -o StrictHostKeyChecking=no ec2-user@"$PUBLIC_IP" 'sudo bash -c "
cd /root/stockai
docker compose down 2>/dev/null || true
docker compose build
docker compose up -d
"'

# ── 9. Enable paper trading ──
echo -e "\n${CYAN}>>> Enabling paper trading...${NC}"
sleep 10
ssh -i "${KEY_NAME}.pem" -o StrictHostKeyChecking=no ec2-user@"$PUBLIC_IP" 'sudo docker exec stockai-redis-1 redis-cli SET 2fa:active "paper-mode"'

# ── 10. Wait for dashboard ──
echo -e "${CYAN}>>> Waiting for services...${NC}"
for i in $(seq 1 60); do
  if curl -sf "http://${PUBLIC_IP}:8000/api/v1/health" &>/dev/null; then
    echo -e "${GREEN}  Services ready!${NC}"
    break
  fi
  echo -n "."
  sleep 10
done

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            StockAI Deployed!                 ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Dashboard:  http://${PUBLIC_IP}:8000${NC}"
echo -e "${GREEN}║  Wallet:     http://${PUBLIC_IP}:8000/api/v1/wallet${NC}"
echo -e "${GREEN}║  Services:   http://${PUBLIC_IP}:8000/api/v1/services${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo "  Instance: $INSTANCE_ID ($INSTANCE_NAME)"
echo "  IP:       $PUBLIC_IP"
echo "  Key:      ${KEY_NAME}.pem"
echo "  SSH:      ssh -i ${KEY_NAME}.pem ec2-user@$PUBLIC_IP"
echo ""
echo "  Update:   bash aws-update.sh"
echo "  Logs:     ssh -i ${KEY_NAME}.pem ec2-user@$PUBLIC_IP 'sudo docker compose -f /root/stockai/docker-compose.yml logs -f'"
echo ""
echo "  Terminate: aws ec2 terminate-instances --instance-ids $INSTANCE_ID --region $REGION"
