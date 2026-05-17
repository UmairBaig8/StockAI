#!/bin/bash
set -e
# StockAI AWS EC2 Deploy - creates t2.small, deploys, prints dashboard URL
# Usage: MEMORY_DEEPSEEK_API_KEY=sk-... bash aws-deploy.sh

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
DEEPSEEK_KEY="${MEMORY_DEEPSEEK_API_KEY:-}"

if [ -z "$DEEPSEEK_KEY" ]; then
  echo -e "${RED}MEMORY_DEEPSEEK_API_KEY is required${NC}"
  echo "Usage: MEMORY_DEEPSEEK_API_KEY=sk-... bash aws-deploy.sh"
  exit 1
fi

# --- Validate AWS CLI ---
if ! aws sts get-caller-identity &>/dev/null; then
  echo -e "${RED}AWS CLI not authenticated. Run: aws sso login${NC}"
  exit 1
fi

KEY_NAME="${KEY_NAME:-stockai-key}"
SG_NAME="stockai-sg-$(date +%s)"
INSTANCE_NAME="stockai-$(date +%Y%m%d-%H%M)"

echo -e "${GREEN}=== StockAI AWS EC2 Deploy ===${NC}"
echo "Instance: $INSTANCE_NAME | Region: ${AWS_REGION:-us-east-1}"

# --- 1. Create key pair ---
echo -e "\n${CYAN}>>> Creating key pair...${NC}"
if aws ec2 describe-key-pairs --key-names "$KEY_NAME" &>/dev/null 2>&1; then
  echo "  Key pair $KEY_NAME exists"
else
  aws ec2 create-key-pair --key-name "$KEY_NAME" --query 'KeyMaterial' --output text > "${KEY_NAME}.pem"
  chmod 400 "${KEY_NAME}.pem"
  echo "  Created: ${KEY_NAME}.pem"
fi

# --- 2. Security group ---
echo -e "${CYAN}>>> Creating security group...${NC}"
SG_ID=$(aws ec2 create-security-group --group-name "$SG_NAME" --description "StockAI" --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 22 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 8000 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 8080 --cidr 0.0.0.0/0
echo "  SG: $SG_ID (ports 22, 8000, 8080)"

# --- 3. Launch EC2 ---
echo -e "${CYAN}>>> Launching t2.small...${NC}"
AMI_ID=$(aws ec2 describe-images --owners amazon --filters "Name=name,Values=al2023-ami-2023*-x86_64" --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' --output text)
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type t2.small \
  --key-name "$KEY_NAME" \
  --security-group-ids "$SG_ID" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
  --query 'Instances[0].InstanceId' \
  --output text)
echo "  Instance: $INSTANCE_ID"

# --- 4. Wait for running ---
echo -e "${CYAN}>>> Waiting for instance...${NC}"
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "  Public IP: $PUBLIC_IP"

# Wait for SSH
echo -e "${CYAN}>>> Waiting for SSH...${NC}"
for i in {1..30}; do
  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 -i "${KEY_NAME}.pem" "ec2-user@$PUBLIC_IP" echo ready 2>/dev/null && break
  sleep 5
done

# --- 5. Install Docker on EC2 ---
echo -e "\n${CYAN}>>> Installing Docker on EC2...${NC}"
ssh -o StrictHostKeyChecking=no -i "${KEY_NAME}.pem" "ec2-user@$PUBLIC_IP" '
  sudo yum update -y
  sudo yum install -y docker git
  sudo service docker start
  sudo usermod -aG docker ec2-user
  sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
  sudo chmod +x /usr/local/bin/docker-compose
'

# --- 6. Deploy project ---
echo -e "${CYAN}>>> Uploading project...${NC}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
rsync -avz -e "ssh -o StrictHostKeyChecking=no -i ${KEY_NAME}.pem" \
  --exclude='target/' --exclude='.venv/' --exclude='bin/' \
  --exclude='data/' --exclude='.git/' --exclude='.playwright-mcp/' \
  --exclude="*.pem" \
  "$SCRIPT_DIR/" "ec2-user@$PUBLIC_IP:~/stockai/"

# --- 7. Configure and start ---
echo -e "${CYAN}>>> Configuring and starting...${NC}"
ssh -o StrictHostKeyChecking=no -i "${KEY_NAME}.pem" "ec2-user@$PUBLIC_IP" "
  cat > ~/stockai/.env << 'EOF'
MEMORY_LLM_PROVIDER=deepseek
MEMORY_DEEPSEEK_API_KEY=${DEEPSEEK_KEY}
MEMORY_DEEPSEEK_MODEL=deepseek-chat
TELEGRAM_BOT_TOKEN=test
TELEGRAM_CHAT_ID=test
RELAY_URL=http://${PUBLIC_IP}:8080
HTTP_PORT=8080
MEMORY_LANCE_DB_PATH=/data/lancedb
DOCKER_MODE=1
EOF
  cd ~/stockai && docker compose build && docker compose up -d
"

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
echo ""
echo "  SSH:      ssh -i ${KEY_NAME}.pem ec2-user@$PUBLIC_IP"
echo "  Logs:     ssh -i ${KEY_NAME}.pem ec2-user@$PUBLIC_IP 'docker compose -f ~/stockai/docker-compose.yml logs -f'"
echo ""
echo "  Terminate: aws ec2 terminate-instances --instance-ids $INSTANCE_ID"
echo "             aws ec2 delete-security-group --group-id $SG_ID"
