# StockAI AWS Environment

## Current Instance (as of 2026-05-20)

| Field | Value |
|-------|-------|
| **Instance ID** | `i-0845fd29ea0f8b328` |
| **Public IP** | `34.236.237.163` |
| **Region** | `us-east-1` (N. Virginia) |
| **Type** | `t3.medium` (2 vCPU, 4 GB RAM) |
| **AMI** | Amazon Linux 2023 |
| **EBS** | 20 GB gp3 |
| **Key Pair** | `stockai-key.pem` (in repo root) |
| **Security Group** | `sg-0e816e1f85a798bf1` (ports 22, 8000, 8080, 9001) |
| **State** | Running |
| **Account ID** | `arn:aws:iam::453767499603:root` |

## Deployed Services (via Docker Compose)

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
| `http://34.236.237.163:8000` | Dashboard (real-time) |
| `http://34.236.237.163:8000/api/v1/wallet` | Wallet status (JSON) |
| `http://34.236.237.163:8000/api/v1/dash` | Trade history + summary |
| `http://34.236.237.163:8000/api/v1/health` | Health check (+ LanceDB entries) |
| `http://34.236.237.163:8000/api/v1/services` | All service statuses |
| `http://34.236.237.163:8000/api/v1/quote/{TICKER}` | Live market quote |
| `http://34.236.237.163:8000/ws/market` | WebSocket market feed |
| `http://34.236.237.163:8080` | TOTP 2FA relay |
| `http://34.236.237.163:9001/health` | Engine health check |

## SSH Access

```bash
ssh -i stockai-key.pem ec2-user@34.236.237.163
```

## Useful Commands

### Check service status
```bash
ssh -i stockai-key.pem ec2-user@34.236.237.163 'sudo docker compose -f /root/stockai/docker-compose.yml ps'
```

### View logs
```bash
# Memory/Strategy logs
ssh -i stockai-key.pem ec2-user@34.236.237.163 'sudo docker logs stockai-memory-1 --tail 50'

# Engine logs
ssh -i stockai-key.pem ec2-user@34.236.237.163 'sudo docker logs stockai-engine-1 --tail 50'

# Orchestrator logs
ssh -i stockai-key.pem ec2-user@34.236.237.163 'sudo docker logs stockai-orchestrator-1 --tail 50'
```

### Redeploy after code push
```bash
ssh -i stockai-key.pem ec2-user@34.236.237.163 'sudo bash -c "
cd /root/stockai && git pull origin main
docker compose build memory && docker compose up -d memory
"'
```

### Rebuild engine (Rust binary changes)
```bash
# On EC2: install Rust natively, then build
ssh -i stockai-key.pem ec2-user@52.91.29.172 'sudo bash -c "
cd /root/stockai/execution && cargo build --release --bin execution
cp target/release/execution ./execution-bin
docker compose build engine && docker compose up -d engine
"'
```

### Free disk space (when 8GB fills up)
```bash
ssh -i stockai-key.pem ec2-user@52.91.29.172 'sudo bash -c "
docker compose down
docker system prune -af --volumes
docker compose up -d
"'
```

### Enable paper trading (if 2FA blocks trades)
```bash
ssh -i stockai-key.pem ec2-user@52.91.29.172 'sudo docker exec stockai-redis-1 redis-cli SET 2fa:active "paper-mode"'
```

### Terminate instance
```bash
aws ec2 terminate-instances --instance-ids i-0845fd29ea0f8b328 --region us-east-1
aws ec2 delete-security-group --group-id sg-0e816e1f85a798bf1 --region us-east-1
```

## AWS Auth (for re-deploy)

```bash
# Use AWS CLI v2 browser login (simplest)
aws login

# Then deploy with one command
MEMORY_DEEPSEEK_API_KEY=sk-... bash aws-deploy.sh
```

## Pipeline Status (2026-05-20)

- Paper trading: **Active** — forced trades every 5 min + natural RSI signals
- Postmortems: **Active** — LanceDB stores analysis for every loss
- Evolution memory: **Active** — vector similarity checks before each trade
- Devil's Advocate: **Active** — LLM reviews every natural signal (relaxed for paper mode)
- 2FA Telegram: Offline (bot token = "test") — paper mode bypasses via Redis key `2fa:active`
- Dashboard WS: **Fixed** — periodic push every 5s (was event-only)

## Known Issues

- **execution-bin not in git** — must be scp'd after clone (103MB, in .gitignore)
- **Docker Compose v2** — Amazon Linux 2023 only ships v1; deploy script installs v2 plugin
- **8GB EBS fills up** during Docker builds — fixed: new instances use 20GB

## Deployment History

| Date | Commit | Change |
|------|--------|--------|
| 2026-05-20 | `1bb2804` | Fresh deploy: t3.medium + 20GB EBS + full .env copy + compose v2 + paper trading |
| 2026-05-20 | `259f79a` | Skip 2FA in MOCK_MODE (code fix, engine binary not rebuilt on old instance) |
| 2026-05-20 | `819b498` | Dashboard WS periodic push every 5s |
| 2026-05-20 | `10c6476` | Fix main.py indentation bug (WS routes orphaned) + settings_store path |
| 2026-05-18 | `7d35722` | Forced paper trades, relaxed strategy + advocate |
| 2026-05-18 | `749a86a` | Pre-built engine binary (avoids Rust OOM on t2.small) |
| 2026-05-18 | `f706906` | Paper pipeline fixes (advocate, market state, P&L) |
| 2026-05-18 | `dfca196` | Initial AWS deploy via user-data |
