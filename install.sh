#!/bin/bash
set -e
# StockAI - One-line install. Run: curl -sSL <url>/install.sh | bash

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
banner(){
  echo -e "${GREEN}"
  echo "  ╔═══════════════════════════════════════════╗"
  echo "  ║           StockAI Installer               ║"
  echo "  ║   Self-Evolving Trading Agent (v1.0)      ║"
  echo "  ╚═══════════════════════════════════════════╝"
  echo -e "${NC}"
}

check(){
  command -v "$1" >/dev/null 2>&1 && echo -e "  ${GREEN}✓${NC} $2" || { echo -e "  ${RED}✗${NC} $2 (missing)"; MISSING=1; }
}

banner

# Clone / enter project
if [ ! -d "StockAI" ]; then
  echo -e "${CYAN}>>> Cloning StockAI...${NC}"
  git clone https://github.com/anomalyco/stockai.git 2>/dev/null || {
    echo -e "${RED}Clone failed. Download manually from GitHub.${NC}"
    exit 1
  }
fi
cd StockAI

# Check prerequisites
echo -e "\n${CYAN}>>> Checking prerequisites...${NC}"
MISSING=0
check go "Go 1.21+"
check cargo "Rust / Cargo"
check python3 "Python 3.11+"
check docker "Docker"
if [ "$MISSING" = "1" ]; then
  echo -e "\n${RED}Missing dependencies. Install them first:${NC}"
  echo "  Go:     https://go.dev/dl/"
  echo "  Rust:   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
  echo "  Python: https://python.org or brew install python"
  echo "  Docker: https://docker.com"
  exit 1
fi

# Install Python deps
echo -e "\n${CYAN}>>> Installing Python dependencies (uv)...${NC}"
pip3 install uv 2>/dev/null || pip install uv 2>/dev/null || true
uv sync 2>/dev/null || true

# Build Go
echo -e "${CYAN}>>> Building Go orchestrator...${NC}"
go mod tidy 2>/dev/null && go build -o bin/orchestrator ./cmd/orchestrator 2>/dev/null || echo "  Skip (will use Docker)"

# Build Rust
echo -e "${CYAN}>>> Building Rust engine (1-2 min)...${NC}"
cd execution && cargo build --bin execution 2>/dev/null && cd .. || echo "  Skip (will use Docker)"

# Configure
if [ ! -f ".env" ]; then
  echo -e "\n${CYAN}>>> Setup${NC}"
  echo -n "DeepSeek API Key (sk-...): "
  read -r KEY
  echo -n "Telegram Bot Token (optional, press enter to skip): "
  read -r TG_TOKEN
  echo -n "Telegram Chat ID (optional): "
  read -r TG_CHAT

  cat > .env << EOF
MEMORY_LLM_PROVIDER=deepseek
MEMORY_DEEPSEEK_API_KEY=${KEY}
MEMORY_DEEPSEEK_MODEL=deepseek-chat
TELEGRAM_BOT_TOKEN=${TG_TOKEN:-test}
TELEGRAM_CHAT_ID=${TG_CHAT:-test}
RELAY_URL=http://localhost:8080
HTTP_PORT=8080
MEMORY_LANCE_DB_PATH=./data/lancedb
EOF
fi

# Start
echo -e "\n${CYAN}>>> Starting StockAI...${NC}"
docker compose up -d 2>/dev/null && echo -e "${GREEN}Docker stack started${NC}" || {
  echo "Starting services directly (Docker not available)..."
  uv run uvicorn app.main:app --port 8000 &
  ./bin/orchestrator &
  cd execution && ./target/debug/execution &
  cd ..
  sleep 5
}

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         StockAI is running!               ║${NC}"
echo -e "${GREEN}╠═══════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Dashboard:  http://localhost:8000         ║${NC}"
echo -e "${GREEN}║  Wallet:     http://localhost:8000/api/v1/wallet${NC}"
echo -e "${GREEN}║  Health:     http://localhost:8000/api/v1/health${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════╝${NC}"
echo ""
echo "  To stop:  docker compose down"
echo "  To watch: docker compose logs -f"
