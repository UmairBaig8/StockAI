# StockAI AWS Environment

> **For AI agents:** Read this file first for quick reference. Full documentation: [aws_deploy/README.md](aws_deploy/README.md). Skills: [SKILLS.md](SKILLS.md)

## Quick Reference

| Field | Value |
|-------|-------|
| **Instance ID** | `i-0845fd29ea0f8b328` |
| **Elastic IP** | `52.70.58.6` (static, never changes) |
| **EIP Allocation ID** | `eipalloc-044a7a75729bf849b` |
| **Region** | `us-east-1` (N. Virginia) |
| **Type** | `t3.medium` (2 vCPU, 4 GB RAM) |
| **AMI** | Amazon Linux 2023 |
| **EBS** | 20 GB gp3 |
| **Key Pair** | `stockai-key.pem` (in repo root) |
| **Security Group** | `sg-0e816e1f85a798bf1` (ports 22, 8000, 8080, 9001) |
| **State** | Running |
| **Account ID** | `arn:aws:iam::453767499603:root` |
| **Scheduler** | Mon-Fri 9:00 AM - 3:30 PM IST (auto start/stop) |
| **Snapshots** | Daily EBS, 30-day retention (SEBI audit) |

## Services

| Service | Port | Language | Status |
|---------|------|----------|--------|
| **Memory** | 8000 | Python (FastAPI + DeepSeek) | Running |
| **Orchestrator** | 8080 | Go (Redis pub/sub, scheduler) | Running |
| **Engine** | 9001 (internal) | Rust (execution engine) | Running |
| **Redis** | 6379 | Redis 7 Alpine | Healthy |
| **PostgreSQL** | 5432 | Postgres 16 Alpine | Healthy |

## Endpoints

| URL | Description |
|-----|-------------|
| `http://52.70.58.6:8000` | Dashboard (real-time) |
| `http://52.70.58.6:8000/api/v1/health` | Health check |
| `http://52.70.58.6:8000/api/v1/services` | Service statuses |
| `http://52.70.58.6:8000/api/v1/wallet` | Wallet status |
| `http://52.70.58.6:8000/api/v1/dash` | Trade history + summary |
| `http://52.70.58.6:8000/api/v1/quote/{TICKER}` | Live market quote |
| `http://52.70.58.6:8080` | TOTP 2FA relay |

## SSH

```bash
ssh -i stockai-key.pem ec2-user@52.70.58.6
```

---

## Quick Operations

### Deploy (fresh instance)

```bash
bash aws-deploy.sh
```

Creates new t3.medium (20GB EBS), copies `.env` + `execution-bin`, builds & starts all services.

### Update (existing instance)

```bash
bash aws-update.sh                  # reads IP from this file
bash aws-update.sh 52.70.58.6   # specific IP
```

Git pull → rebuilds changed services → restarts. Detects Rust changes automatically.

### Check status

```bash
ssh -i stockai-key.pem ec2-user@52.70.58.6 'sudo docker compose -f /root/stockai/docker-compose.yml ps'
curl -s http://52.70.58.6:8000/api/v1/health
curl -s http://52.70.58.6:8000/api/v1/services
```

### View logs

```bash
ssh -i stockai-key.pem ec2-user@52.70.58.6 'sudo docker logs stockai-memory-1 --tail 50'
ssh -i stockai-key.pem ec2-user@52.70.58.6 'sudo docker logs stockai-engine-1 --tail 50'
ssh -i stockai-key.pem ec2-user@52.70.58.6 'sudo docker logs stockai-orchestrator-1 --tail 50'
```

### Manual rebuild (single service)

```bash
# Memory (Python) — fast
ssh -i stockai-key.pem ec2-user@52.70.58.6 'sudo bash -c "cd /root/stockai && docker compose build memory && docker compose up -d memory"'

# Engine (Rust) — needs execution-bin uploaded first
scp -i stockai-key.pem execution/execution-bin ec2-user@52.70.58.6:/tmp/execution-bin
ssh -i stockai-key.pem ec2-user@52.70.58.6 'sudo bash -c "cp /tmp/execution-bin /root/stockai/execution/execution-bin && cd /root/stockai && docker compose build engine && docker compose up -d engine"'
```

### Enable paper trading

```bash
ssh -i stockai-key.pem ec2-user@52.70.58.6 'sudo docker exec stockai-redis-1 redis-cli SET 2fa:active "paper-mode"'
```

### Free disk space

```bash
ssh -i stockai-key.pem ec2-user@52.70.58.6 'sudo bash -c "cd /root/stockai && docker compose down && docker system prune -af --volumes && docker compose up -d"'
```

### Terminate

```bash
aws ec2 terminate-instances --instance-ids i-0845fd29ea0f8b328 --region us-east-1
aws ec2 delete-security-group --group-id sg-0e816e1f85a798bf1 --region us-east-1
```

---

## Architecture

```
Client → :8000 → Memory (FastAPI + Python)
                    ├── Strategy Agent (RSI, MACD, BB, forced trades)
                    ├── Market Data (yfinance polling 2s)
                    ├── Vector Store (LanceDB — postmortems + memory)
                    ├── LLM Providers (DeepSeek, Gemini, OpenAI, Bedrock)
                    └── WebSocket feeds (/ws/market, /ws/dashboard, /ws/services, /ws/wallet)

Client → :8080 → Orchestrator (Go)
                    ├── Redis pub/sub (trade:signal → trade:result)
                    ├── TOTP 2FA relay
                    └── Scheduler

Engine → :9001 → Execution Engine (Rust)
                    ├── Subscribes trade:signal on Redis
                    ├── Mock broker (paper trading)
                    └── Health check HTTP server

Redis :6379 — pub/sub + 2fa:active key + position persistence
PostgreSQL :5432 — trade history + wallet state + daily reports
```

## Pipeline Flow

1. **Market Data** polls yfinance every 2s → pushes quotes via WebSocket
2. **Strategy Agent** scans for RSI/MACD/BB signals → forced trade every 5 min if no signal
3. Pre-trade checks: memory (LanceDB), sentiment, advocate, researcher, macro
4. Signal published to Redis `trade:signal`
5. **Engine** receives signal → mock execution → publishes `trade:result`
6. **Strategy** listens to `trade:result` → tracks consecutive losses
7. Losses trigger **Critic** postmortem → stored in LanceDB with correction rules

## Paper Trading Config

- `MOCK_MODE=true` in engine env
- Redis key `2fa:active = "paper-mode"` bypasses 2FA check
- Engine publishes OPEN/WIN/LOSS results to `trade:result`
- Strategy tracks P&L, consecutive losses, daily loss limits

## Known Issues

- **execution-bin not in git** (103MB, in .gitignore) — must be scp'd on fresh deploy
- **Docker Compose v2** — AL2023 ships v1 only; deploy script installs v2 plugin
- **yfinance TzCache error** — harmless, cache folder exists but not used

## Deployment History

| Date | Commit | Change |
|------|--------|--------|
| 2026-05-20 | `0787add` | Fresh deploy on new instance (52.70.58.6) — t3.medium, 20GB EBS |
| 2026-05-20 | `1bb2804` | Deploy script: full .env copy, execution-bin upload, compose v2 install |
| 2026-05-20 | `259f79a` | Skip 2FA check in MOCK_MODE (engine) |
| 2026-05-20 | `819b498` | Dashboard WS periodic push every 5s |
| 2026-05-20 | `10c6476` | Fix main.py indentation bug (WS routes orphaned) |
| 2026-05-18 | `7d35722` | Forced paper trades every 5 min |
| 2026-05-18 | `dfca196` | Initial AWS deploy |
