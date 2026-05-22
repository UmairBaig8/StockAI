#!/bin/bash
set -e

# ── Install Docker ──
apt-get update
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin git

# ── Clone StockAI repo ──
mkdir -p /opt/stockai
if [ ! -d /opt/stockai/.git ]; then
  git clone https://github.com/UmairBaig8/StockAI.git /opt/stockai || echo "Clone failed - ensure repo is accessible"
fi

# ── Write .env ──
cat > /opt/stockai/devserver/.env << 'ENVFILE'
MEMORY_DEEPSEEK_API_KEY=${deepseek_api_key}
MEMORY_GEMINI_API_KEY=${gemini_api_key}
MEMORY_OPENAI_API_KEY=${openai_api_key}
MEMORY_ANTHROPIC_API_KEY=${anthropic_api_key}
MEMORY_AWS_ACCESS_KEY_ID=${aws_access_key_id}
MEMORY_AWS_SECRET_ACCESS_KEY=${aws_secret_access_key}
MEMORY_BEDROCK_MODEL=${bedrock_model}
TELEGRAM_BOT_TOKEN=${telegram_bot_token}
TELEGRAM_CHAT_ID=${telegram_chat_id}
DEV_BOT_TOKEN=${dev_bot_token}
ALLOWED_TELEGRAM_ID=${allowed_telegram_id}
AUTO_STOP_MINUTES=${auto_stop_minutes}
CODE_SERVER_PASSWORD=${code_server_password}
CODE_SERVER_PORT=${code_server_port}
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
AWS_DEFAULT_REGION=us-east-1
ENVFILE

# ── Build custom code-server image ──
echo "Building custom code-server image (Python + Go + Rust)..."
cd /opt/stockai/devserver
docker build -t devserver-code-server:latest -f Dockerfile.codeserver .

# ── Start StockAI infrastructure + bot ──
echo "Starting StockAI services..."
docker compose -f docker-compose.yml up -d redis postgres memory orchestrator engine bot

# ── Systemd for resilience ──
cat > /etc/systemd/system/stockai-devserver.service << 'SERVICE'
[Unit]
Description=StockAI DevServer
After=docker.service
Requires=docker.service

[Service]
Type=simple
WorkingDirectory=/opt/stockai/devserver
EnvironmentFile=/opt/stockai/devserver/.env
ExecStart=/usr/bin/docker compose -f docker-compose.yml up -d redis postgres memory orchestrator engine bot
ExecStop=/usr/bin/docker compose -f docker-compose.yml down
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable stockai-devserver
systemctl start stockai-devserver

echo "StockAI DevServer setup complete!"
echo "Bot status: systemctl status stockai-devserver"
echo "To start code-server: send /start to your Telegram bot"
