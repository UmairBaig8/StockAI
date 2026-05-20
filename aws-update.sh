#!/bin/bash
set -e
# StockAI AWS EC2 — UPDATE: git pull + rebuild + restart on existing instance
# Usage: bash aws-update.sh
# Usage: bash aws-update.sh 34.236.237.163  (specific IP)
# Reads instance IP from aws_env.md if not provided

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
KEY_NAME="${KEY_NAME:-stockai-key}"

# ── Find instance IP ──
if [ -n "$1" ]; then
  PUBLIC_IP="$1"
elif [ -f "aws_env.md" ]; then
  PUBLIC_IP=$(grep -m1 '\*\*Public IP\*\*' aws_env.md | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+')
fi

if [ -z "$PUBLIC_IP" ]; then
  echo -e "${RED}No instance IP found. Usage: bash aws-update.sh <IP>${NC}"
  exit 1
fi

echo -e "${GREEN}=== StockAI Update ===${NC}"
echo "Target: $PUBLIC_IP"

# ── 1. Test SSH ──
if ! ssh -i "${KEY_NAME}.pem" -o StrictHostKeyChecking=no -o ConnectTimeout=10 ec2-user@"$PUBLIC_IP" echo "SSH OK" 2>/dev/null; then
  echo -e "${RED}Cannot SSH to $PUBLIC_IP${NC}"
  exit 1
fi

# ── 2. Git pull ──
echo -e "\n${CYAN}>>> Pulling latest code...${NC}"
ssh -i "${KEY_NAME}.pem" -o StrictHostKeyChecking=no ec2-user@"$PUBLIC_IP" 'sudo bash -c "cd /root/stockai && git pull origin main"'

# ── 3. Check if execution-bin changed (needs rebuild) ──
echo -e "\n${CYAN}>>> Checking for Rust changes...${NC}"
RUST_CHANGED=$(ssh -i "${KEY_NAME}.pem" -o StrictHostKeyChecking=no ec2-user@"$PUBLIC_IP" 'sudo bash -c "cd /root/stockai && git diff HEAD~1 --name-only | grep -c \"^execution/\" || true"')

if [ "$RUST_CHANGED" -gt 0 ]; then
  echo -e "${CYAN}  Rust code changed — uploading new execution-bin...${NC}"
  if [ -f "execution/execution-bin" ]; then
    scp -i "${KEY_NAME}.pem" -o StrictHostKeyChecking=no execution/execution-bin ec2-user@"$PUBLIC_IP":/tmp/execution-bin
    ssh -i "${KEY_NAME}.pem" -o StrictHostKeyChecking=no ec2-user@"$PUBLIC_IP" 'sudo cp /tmp/execution-bin /root/stockai/execution/execution-bin && sudo chmod +x /root/stockai/execution/execution-bin'
    echo -e "${GREEN}  execution-bin updated${NC}"
  else
    echo -e "${RED}  execution/execution-bin not found locally — build first${NC}"
  fi
fi

# ── 4. Rebuild changed services ──
echo -e "\n${CYAN}>>> Rebuilding services...${NC}"
if [ "$RUST_CHANGED" -gt 0 ]; then
  echo "  Building engine + memory + orchestrator..."
  ssh -i "${KEY_NAME}.pem" -o StrictHostKeyChecking=no ec2-user@"$PUBLIC_IP" 'sudo bash -c "
    cd /root/stockai
    docker compose build memory orchestrator engine
    docker compose up -d
  "'
else
  echo "  Building memory only (Python changes)..."
  ssh -i "${KEY_NAME}.pem" -o StrictHostKeyChecking=no ec2-user@"$PUBLIC_IP" 'sudo bash -c "
    cd /root/stockai
    docker compose build memory
    docker compose up -d memory
  "'
fi

# ── 5. Verify ──
echo -e "\n${CYAN}>>> Verifying...${NC}"
sleep 5
HEALTH=$(curl -sf "http://${PUBLIC_IP}:8000/api/v1/health" 2>/dev/null || echo "FAIL")
SERVICES=$(curl -sf "http://${PUBLIC_IP}:8000/api/v1/services" 2>/dev/null || echo "FAIL")

if [ "$HEALTH" != "FAIL" ]; then
  echo -e "${GREEN}  Health: $HEALTH${NC}"
else
  echo -e "${RED}  Health check failed — check logs:${NC}"
  echo "  ssh -i ${KEY_NAME}.pem ec2-user@$PUBLIC_IP 'sudo docker compose -f /root/stockai/docker-compose.yml logs --tail 30'"
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            StockAI Updated!                  ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Dashboard:  http://${PUBLIC_IP}:8000${NC}"
echo -e "${GREEN}║  Services:   http://${PUBLIC_IP}:8000/api/v1/services${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
