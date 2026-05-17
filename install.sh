#!/bin/bash
set -e
# StockAI — One-line install. Works on: macOS, Linux (Ubuntu/Amazon Linux), fresh EC2.
# Run: curl -sSL https://raw.githubusercontent.com/UmairBaig8/StockAI/main/install.sh | bash

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
banner(){
  echo -e "${GREEN}"
  echo "  ╔═══════════════════════════════════════════╗"
  echo "  ║           StockAI Installer               ║"
  echo "  ║   Self-Evolving Trading Agent (v1.0)      ║"
  echo "  ╚═══════════════════════════════════════════╝"
  echo -e "${NC}"
}
banner

OS="$(uname -s)"

# ── Auto-install Docker if missing ──
if ! command -v docker &>/dev/null; then
  echo -e "${CYAN}>>> Installing Docker...${NC}"
  if [ "$OS" = "Linux" ]; then
    if command -v apt-get &>/dev/null; then
      sudo apt-get update -y && sudo apt-get install -y docker.io docker-compose-v2
    elif command -v yum &>/dev/null; then
      sudo yum update -y && sudo yum install -y docker
      sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
      sudo chmod +x /usr/local/bin/docker-compose
    fi
    sudo service docker start 2>/dev/null || sudo systemctl start docker
    sudo usermod -aG docker "$USER" 2>/dev/null || true
    echo -e "${GREEN}Docker installed${NC}"
  elif [ "$OS" = "Darwin" ]; then
    echo -e "${RED}Please install Docker Desktop: https://docker.com${NC}"
    exit 1
  fi
fi

# ── Auto-install git if missing ──
command -v git &>/dev/null || {
  echo -e "${CYAN}>>> Installing git...${NC}"
  command -v apt-get &>/dev/null && sudo apt-get install -y git
  command -v yum &>/dev/null && sudo yum install -y git
}

# ── Clone / enter project ──
REPO_DIR="${REPO_DIR:-$HOME/stockai}"
if [ ! -d "$REPO_DIR" ]; then
  echo -e "${CYAN}>>> Cloning StockAI...${NC}"
  git clone https://github.com/UmairBaig8/StockAI.git "$REPO_DIR"
fi
cd "$REPO_DIR"

# ── Create .env if missing ──
if [ ! -f ".env" ]; then
  echo -e "\n${CYAN}>>> Setup${NC}"
  if [ -z "$MEMORY_DEEPSEEK_API_KEY" ]; then
    echo -n "DeepSeek API Key (sk-...): "
    read -r DEEPSEEK_KEY
  else
    DEEPSEEK_KEY="$MEMORY_DEEPSEEK_API_KEY"
  fi

  cat > .env << EOF
MEMORY_LLM_PROVIDER=deepseek
MEMORY_DEEPSEEK_API_KEY=${DEEPSEEK_KEY}
MEMORY_DEEPSEEK_MODEL=${MEMORY_DEEPSEEK_MODEL:-deepseek-chat}
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-test}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID:-test}
RELAY_URL=${RELAY_URL:-http://localhost:8080}
HTTP_PORT=8080
MEMORY_LANCE_DB_PATH=/data/lancedb
DOCKER_MODE=1
EOF
fi

# ── Build & start ──
echo -e "\n${CYAN}>>> Building & starting (5-10 min on first run)...${NC}"
docker compose build 2>/dev/null || docker-compose build
docker compose up -d 2>/dev/null || docker-compose up -d

sleep 5

PUBLIC_IP=$(curl -s http://checkip.amazonaws.com 2>/dev/null || echo "localhost")
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         StockAI is running!               ║${NC}"
echo -e "${GREEN}╠═══════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Dashboard:  http://${PUBLIC_IP}:8000         ║${NC}"
echo -e "${GREEN}║  Wallet:     http://${PUBLIC_IP}:8000/api/v1/wallet${NC}"
echo -e "${GREEN}║  Health:     http://${PUBLIC_IP}:8000/api/v1/health${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════╝${NC}"
echo ""
echo "  To stop:  docker compose down"
echo "  To watch: docker compose logs -f"
echo "  Dir:      $REPO_DIR"
