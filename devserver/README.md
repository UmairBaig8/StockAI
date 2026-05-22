# StockAI DevServer

Single EC2 instance running **StockAI trading app** + **VS Code in browser** + **Telegram control bot**.

## Architecture

```
EC2 (t3.medium, Ubuntu 22.04, 30GB gp3)
│
├── Docker Compose (all services)
│   ├── redis         — :6379  (always on)
│   ├── postgres      — :5432  (always on)
│   ├── memory        — :8000  (FastAPI + strategy + dashboard)
│   ├── orchestrator  — :8080  (Go, Telegram app bot, scheduler)
│   ├── engine        — :9001  (Rust, trade execution)
│   ├── code-server   — :8443  (VS Code in browser, on-demand)
│   └── bot           —        (Telegram dev bot, always on)
│
├── systemd: stockai-devserver (auto-start on reboot)
└── Elastic IP: auto-assigned by Terraform
```

## Quick Start

### Prerequisites
- AWS CLI with credentials
- Terraform >= 1.5
- Two Telegram bots (create via @BotFather):
  - **App bot**: for StockAI trade notifications (already exists)
  - **Dev bot**: for controlling code-server (new)

### Deploy

```bash
cd devserver/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your bot tokens and API keys
terraform init
terraform apply
```

Terraform provisions: EC2, Security Group, Elastic IP, IAM role, SSH keypair.

### Verify

```bash
# Health check
curl http://<ip>:8000/api/v1/health

# All services
ssh -i devserver-key.pem ubuntu@<ip>
sudo docker compose -f /opt/stockai/devserver/docker-compose.yml ps
```

## Telegram Commands

Send to your **dev bot** (not the StockAI app bot):

| Command | Action |
|---------|--------|
| `/start` | Launch VS Code (code-server) |
| `/stop` | Stop VS Code to save cost |
| `/url` | Get code-server URL + StockAI dashboard links |
| `/status` | Check dev + app container states |
| `/exec <cmd>` | Run command inside code-server |
| `/app start\|stop\|restart` | Control StockAI trading services |
| `/setidle <min>` | Change auto-stop timer (default 30min) |

## Workspace

On `/start`, code-server mounts:
- `/workspace/` — Docker volume (persistent, your files)
- `/workspace/StockAI/` — bind mount to `/opt/stockai` (read-only, latest deployed code)

## StockAI Dashboard

| Endpoint | Description |
|----------|-------------|
| `http://<ip>:8000` | Cockpit UI |
| `http://<ip>:8000/api/v1/health` | Health check |
| `http://<ip>:8000/api/v1/dash` | Trade history + summary |
| `http://<ip>:8000/api/v1/wallet` | Wallet status |
| `http://<ip>:8000/api/v1/report/daily` | Daily P&L report |

## Cost

| Item | Est. Cost |
|------|-----------|
| t3.medium (24/7) | ~$30/mo |
| 30GB gp3 EBS | ~$2.40/mo |
| Elastic IP (attached) | Free |
| **Total** | **~$32/mo** |

Code-server auto-stops after idle (default 30min). Use `/setidle` to adjust.

## Files

```
devserver/
├── terraform/              # AWS infrastructure as code
│   ├── main.tf             # EC2, SG, EIP, IAM, keypair
│   ├── variables.tf        # All configurable parameters
│   └── terraform.tfvars    # Your actual values (gitignored)
├── Dockerfile.codeserver   # Custom code-server with Python + Go + Rust
├── docker-compose.yml      # All 7 services
├── bot/                    # Telegram dev control bot
│   ├── bot.py
│   └── Dockerfile
├── scripts/
│   └── setup.sh            # EC2 bootstrap (cloud-init)
└── .gitignore
```

## Updating

```bash
# Push code changes
git add . && git commit -m "..." && git push

# Pull on EC2 and rebuild changed services
ssh -i devserver-key.pem ubuntu@<ip>
cd /opt/stockai && git pull
cd devserver
sudo docker compose -f docker-compose.yml up -d --build memory
```
