#!/bin/bash
set -e
echo "=== StockAI Deploy to AWS EC2 ==="

EC2_IP="${EC2_IP:-}"
PEM_KEY="${PEM_KEY:-~/.ssh/aws.pem}"
DEEPSEEK_KEY="${MEMORY_DEEPSEEK_API_KEY:-}"

if [ -z "$EC2_IP" ]; then
  echo "Usage:"
  echo "  EC2_IP=<your-ec2-ip> MEMORY_DEEPSEEK_API_KEY=<key> bash deploy.sh"
  echo "  PEM_KEY defaults to ~/.ssh/aws.pem"
  exit 1
fi

SSH="ssh -o StrictHostKeyChecking=no -i $PEM_KEY ec2-user@$EC2_IP"

# --- 1. Install deps ---
echo ">>> Installing Docker..."
$SSH 'sudo yum update -y && sudo yum install -y docker git && sudo service docker start && sudo usermod -aG docker ec2-user'
$SSH 'sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose && sudo chmod +x /usr/local/bin/docker-compose'

# Add swap for Rust build on t2.micro
echo ">>> Adding 1GB swap (needed for Rust build)..."
$SSH 'sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile && echo "/swapfile swap swap defaults 0 0" | sudo tee -a /etc/fstab'

# --- 2. Copy project ---
echo ">>> Copying project..."
rsync -avz -e "ssh -i $PEM_KEY" \
  --exclude='target/' --exclude='.venv/' --exclude='bin/' \
  --exclude='data/' --exclude='.git/' --exclude='.playwright-mcp/' \
  . "ec2-user@$EC2_IP:~/stockai/"

# --- 3. Create .env ---
echo ">>> Configuring..."
$SSH "cat > ~/stockai/.env << EOF
MEMORY_LLM_PROVIDER=deepseek
MEMORY_DEEPSEEK_API_KEY=${DEEPSEEK_KEY}
MEMORY_DEEPSEEK_MODEL=${DEEPSEEK_MODEL:-deepseek-chat}
TELEGRAM_BOT_TOKEN=test
TELEGRAM_CHAT_ID=test
RELAY_URL=http://${EC2_IP}:8080
HTTP_PORT=8080
MEMORY_LANCE_DB_PATH=/data/lancedb
DOCKER_MODE=1
EOF"

# --- 4. Build & start ---
echo ">>> Building images (5-10 min on t2.micro)..."
$SSH 'cd ~/stockai && docker compose build'

echo ">>> Starting services..."
$SSH 'cd ~/stockai && docker compose up -d'

echo ""
echo "============================================"
echo "  DEPLOYED to http://${EC2_IP}:8000"
echo "============================================"
echo "Dashboard:  http://${EC2_IP}:8000"
echo "Wallet:     http://${EC2_IP}:8000/api/v1/wallet"
echo "Services:   http://${EC2_IP}:8000/api/v1/services"
echo ""
echo "Logs: ssh -i $PEM_KEY ec2-user@${EC2_IP} 'docker compose -f ~/stockai/docker-compose.yml logs -f'"
