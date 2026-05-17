#!/bin/bash
set -e
# StockAI AWS EC2 — one command: creates t2.small, deploys, prints dashboard URL
# Usage: MEMORY_DEEPSEEK_API_KEY=sk-... bash aws-deploy.sh

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
DEEPSEEK_KEY="${MEMORY_DEEPSEEK_API_KEY:-}"

if [ -z "$DEEPSEEK_KEY" ]; then
  echo -e "${RED}MEMORY_DEEPSEEK_API_KEY is required${NC}"
  echo "Usage: MEMORY_DEEPSEEK_API_KEY=sk-... bash aws-deploy.sh"
  exit 1
fi

if ! aws sts get-caller-identity &>/dev/null; then
  echo -e "${RED}AWS CLI not authenticated. Run: aws sso login${NC}"
  exit 1
fi

KEY_NAME="${KEY_NAME:-stockai-key}"
SG_NAME="stockai-sg-$(date +%s)"
INSTANCE_NAME="stockai-$(date +%Y%m%d-%H%M)"
REGION="${AWS_REGION:-us-east-1}"

echo -e "${GREEN}=== StockAI AWS EC2 Deploy ===${NC}"
echo "Instance: $INSTANCE_NAME | Region: $REGION"

# ── 1. Key pair ──
echo -e "\n${CYAN}>>> Creating key pair...${NC}"
aws ec2 describe-key-pairs --key-names "$KEY_NAME" &>/dev/null 2>&1 \
  && echo "  Using existing key: $KEY_NAME" \
  || { aws ec2 create-key-pair --key-name "$KEY_NAME" --query 'KeyMaterial' --output text > "${KEY_NAME}.pem"
       chmod 400 "${KEY_NAME}.pem"; echo "  Created: ${KEY_NAME}.pem"; }

# ── 2. Security group ──
echo -e "${CYAN}>>> Creating security group...${NC}"
SG_ID=$(aws ec2 create-security-group --group-name "$SG_NAME" --description "StockAI" --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 22 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 8000 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 8080 --cidr 0.0.0.0/0
echo "  SG: $SG_ID (ports 22, 8000, 8080)"

# ── 3. User-data (auto-runs on boot) ──
USER_DATA=$(cat <<EOF | base64 -w0
#!/bin/bash
exec > /var/log/stockai-userdata.log 2>&1
set -e
export MEMORY_DEEPSEEK_API_KEY="${DEEPSEEK_KEY}"
export MEMORY_DEEPSEEK_MODEL="${MEMORY_DEEPSEEK_MODEL:-deepseek-chat}"
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-test}"
export TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-test}"
export HOME=/root
curl -sSL https://raw.githubusercontent.com/UmairBaig8/StockAI/main/install.sh | bash
EOF
)

# ── 4. Launch EC2 ──
echo -e "${CYAN}>>> Launching t2.small...${NC}"
AMI_ID=$(aws ec2 describe-images --owners amazon \
  --filters "Name=name,Values=al2023-ami-2023*-x86_64" \
  --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' --output text)

INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type t2.small \
  --key-name "$KEY_NAME" \
  --security-group-ids "$SG_ID" \
  --user-data "$USER_DATA" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
  --query 'Instances[0].InstanceId' \
  --output text)

echo "  Instance: $INSTANCE_ID ($INSTANCE_NAME)"

# ── 5. Wait for running ──
echo -e "${CYAN}>>> Waiting for instance (boot + Docker + build ~8 min)...${NC}"
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "  Public IP: $PUBLIC_IP"

# ── 6. Wait for dashboard to respond ──
echo -e "${CYAN}>>> Waiting for services (build in progress)...${NC}"
for i in $(seq 1 60); do
  if curl -s "http://${PUBLIC_IP}:8000/api/v1/health" &>/dev/null; then
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
echo "  Key:      ${KEY_NAME}.pem"
echo "  SSH:      ssh -i ${KEY_NAME}.pem ec2-user@$PUBLIC_IP"
echo "  Logs:     ssh -i ${KEY_NAME}.pem ec2-user@$PUBLIC_IP 'tail -f /var/log/stockai-userdata.log'"
echo ""
echo "  Terminate: aws ec2 terminate-instances --instance-ids $INSTANCE_ID"
echo "             aws ec2 delete-security-group --group-id $SG_ID"
