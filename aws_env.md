# StockAI AWS Environment

> **For AI agents:** Read this file first for quick reference. Full docs: [devserver/README.md](devserver/README.md)

## Quick Reference

| Field | Value |
|-------|-------|
| **Instance ID** | `i-0ef6c5e6ee869eb14` |
| **Elastic IP** | `100.28.190.112` (static, never changes) |
| **Region** | `us-east-1` (N. Virginia) |
| **Type** | `t3.medium` (2 vCPU, 4 GB RAM) |
| **AMI** | Ubuntu 22.04 LTS |
| **EBS** | 30 GB gp3 |
| **Key Pair** | `devserver-key.pem` (in `devserver/terraform/`) |
| **Security Group** | `sg-03247e83c895dd023` (ports 22, 8000, 8080, 8443) |
| **State** | Running |
| **Account ID** | `arn:aws:iam::453767499603:root` |
| **Scheduler** | Mon-Fri 8:30 AM - 3:30 PM IST (auto start/stop) |
| **Snapshots** | Daily EBS, 30-day retention |

## Services

| Service | Port | Language | Status |
|---------|------|----------|--------|
| **Memory** | 8000 | Python (FastAPI + DeepSeek) | Running |
| **Orchestrator** | 8080 | Go (Redis pub/sub, scheduler) | Running |
| **Engine** | 9001 (internal) | Rust (execution engine) | Running |
| **Bot** | — | Python (dev control via Telegram) | Running |
| **Redis** | 6379 | Redis 7 Alpine | Healthy |
| **PostgreSQL** | 5432 | Postgres 16 Alpine | Healthy |
| **Code-Server** | 8443 (on-demand) | VS Code in browser | `/start` via Telegram |

## Endpoints

| URL | Description |
|-----|-------------|
| `http://100.28.190.112:8000` | Dashboard (real-time) |
| `http://100.28.190.112:8000/api/v1/health` | Health check |
| `http://100.28.190.112:8000/api/v1/services` | Service statuses |
| `http://100.28.190.112:8000/api/v1/wallet` | Wallet status |
| `http://100.28.190.112:8000/api/v1/dash` | Trade history + summary |
| `http://100.28.190.112:8000/api/v1/quote/{TICKER}` | Live market quote |
| `http://100.28.190.112:8000/api/v1/strategy/status` | Strategy debug |
| `http://100.28.190.112:8443` | VS Code (on-demand via Telegram `/start`) |

## SSH

```bash
ssh -i devserver/terraform/devserver-key.pem ubuntu@100.28.190.112
```

## Quick Operations

### Deploy (via Terraform)

```bash
cd devserver/terraform
cp terraform.tfvars.example terraform.tfvars   # fill in tokens
terraform init && terraform apply
```

### Update Code

```bash
git push                                              # local
ssh -i devserver/terraform/devserver-key.pem ubuntu@100.28.190.112
cd /opt/stockai && git pull
cd devserver && sudo docker compose -f docker-compose.yml up -d --build memory
```

### Check Status

```bash
curl -s http://100.28.190.112:8000/api/v1/health
ssh -i devserver/terraform/devserver-key.pem ubuntu@100.28.190.112 \
  'sudo docker compose -f /opt/stockai/devserver/docker-compose.yml ps'
```

### View Logs

```bash
ssh -i devserver/terraform/devserver-key.pem ubuntu@100.28.190.112 \
   'sudo docker logs devserver-memory-1 --tail 50'
```

### Emergency Halt

Send `/halt` to the dev Telegram bot. Send `/resume` to re-enable.

### Manual Start/Stop Instance

```bash
aws lambda invoke --function-name stockai-devserver-scheduler \
  --payload '{"action":"start"}' /dev/stdout --region us-east-1
aws lambda invoke --function-name stockai-devserver-scheduler \
  --payload '{"action":"stop"}' /dev/stdout --region us-east-1
```

## Architecture

```
EC2 (t3.medium, Ubuntu 22.04, 30GB gp3)
│
├── Docker Compose
│   ├── redis        — :6379  (persistence, pub/sub)
│   ├── postgres     — :5432  (trades, wallet, events, LLM traces)
│   ├── memory       — :8000  (FastAPI: strategy, market data, dashboard)
│   ├── orchestrator — :8080  (Go: app bot, scheduler, Redis bridge)
│   ├── engine       — :9001  (Rust: trade execution, mock broker)
│   ├── code-server  — :8443  (VS Code in browser, on-demand)
│   └── bot          —        (Telegram dev control, healthcheck)
│
├── systemd: stockai-devserver (auto-start on reboot)
├── EventBridge + Lambda: auto start/stop Mon-Fri
└── Elastic IP: static, auto re-associated on start
```

## Strategy Controls

| Setting | Default | Description |
|---------|---------|-------------|
| `position_size_pct` | 5% (clamped 2-15%) | Per-trade position size |
| `max_positions` | 3 (clamped 1-8) | Max concurrent positions |
| `stop_loss_pct` | 0.8% (clamped 0.5-2%) | Stop loss |
| `take_profit_pct` | 1.5% | Take profit target |
| `force_trade_sec` | 600s | Max idle before forced trade |

All configurable at `/settings` or via UI. Guardrails enforced in `settings_store.py`.

## Deployment History

| Date | Change |
|------|--------|
| 2026-05-22 | Terraform devserver deploy (100.28.190.112) — replaces old 52.70.58.6 |
| 2026-05-22 | Scheduler: Lambda + EventBridge auto start/stop Mon-Fri |
| 2026-05-22 | Telegram dev bot: /halt /resume /forcebuy /start /stop |
| 2026-05-22 | GitHub Actions CI (Python lint + Go build + Rust check) |
| 2026-05-21 | Persistence fixes + per-ticker circuit breakers + guardrails |
| 2026-05-20 | Initial AWS deploy (52.70.58.6) |
