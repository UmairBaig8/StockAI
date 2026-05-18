# StockAI AWS Environment

## Current Instance (as of 2026-05-18)

| Field | Value |
|-------|-------|
| **Instance ID** | `i-058cc54d6a71a3064` |
| **Public IP** | `3.85.55.232` |
| **Region** | `us-east-1` (N. Virginia) |
| **Type** | `t2.small` (1 vCPU, 2 GB RAM) |
| **AMI** | Amazon Linux 2023 |
| **Key Pair** | `stockai-key.pem` (in repo root) |
| **Security Group** | `sg-06ad9c996866ee2b5` (ports 22, 8000, 8080) |
| **State** | Running |
| **Account ID** | `arn:aws:iam::453767499603:root` |

## Deployed Services (via Docker Compose)

| Service | Port | Language | Status |
|---------|------|----------|--------|
| **Memory** | 8000 | Python (FastAPI + DeepSeek) | Running |
| **Orchestrator** | 8080 | Go (Redis pub/sub, scheduler) | Running |
| **Engine** | 9001 (internal) | Rust (execution engine) | Running |
| **Redis** | 6379 | Redis 7 Alpine | Healthy |

## Endpoints

| URL | Description |
|-----|-------------|
| `http://3.85.55.232:8000` | Dashboard (real-time) |
| `http://3.85.55.232:8000/api/v1/wallet` | Wallet status (JSON) |
| `http://3.85.55.232:8000/api/v1/dash` | Trade history + summary |
| `http://3.85.55.232:8000/api/v1/health` | Health check (+ LanceDB entries) |
| `http://3.85.55.232:8000/api/v1/services` | All service statuses |
| `http://3.85.55.232:8000/api/v1/quote/{TICKER}` | Live market quote |
| `http://3.85.55.232:8000/ws/market` | WebSocket market feed |
| `http://3.85.55.232:8080` | TOTP 2FA relay |

## SSH Access

```bash
ssh -i stockai-key.pem ec2-user@3.85.55.232
```

## Useful Commands

### Check service status
```bash
ssh -i stockai-key.pem ec2-user@3.85.55.232 'sudo docker compose -f /root/stockai/docker-compose.yml ps'
```

### View logs
```bash
# Memory/Strategy logs
ssh -i stockai-key.pem ec2-user@3.85.55.232 'sudo docker logs stockai-memory-1 --tail 50'

# Engine logs
ssh -i stockai-key.pem ec2-user@3.85.55.232 'sudo docker logs stockai-engine-1 --tail 50'

# Orchestrator logs
ssh -i stockai-key.pem ec2-user@3.85.55.232 'sudo docker logs stockai-orchestrator-1 --tail 50'
```

### Redeploy after code push
```bash
ssh -i stockai-key.pem ec2-user@3.85.55.232 'sudo bash -c "
cd /root/stockai && git pull origin main
docker compose build
docker compose up -d --force-recreate
"'
```

### Rebuild single service
```bash
# Memory only (Python, fast rebuild)
ssh -i stockai-key.pem ec2-user@3.85.55.232 'sudo bash -c "
cd /root/stockai && git pull origin main
docker compose build memory && docker compose up -d memory
"'

# Engine only (Rust binary is pre-built, fast)
ssh -i stockai-key.pem ec2-user@3.85.55.232 'sudo bash -c "
cd /root/stockai && git pull origin main
docker compose build engine && docker compose up -d engine
"'
```

### Rebuild engine binary locally (if Rust code changes)
```bash
docker run --rm --platform linux/amd64 \
  -v $(pwd)/execution:/build -w /build \
  rust:1.95-slim sh -c \
  "apt-get update -qq && apt-get install -y -qq pkg-config libssl-dev && cargo build --bin execution && cp target/debug/execution /build/execution-bin"
```

### Terminate instance
```bash
aws ec2 terminate-instances --instance-ids i-058cc54d6a71a3064 --region us-east-1
aws ec2 delete-security-group --group-id sg-06ad9c996866ee2b5 --region us-east-1
```

## AWS Auth (for re-deploy)

```bash
# Use AWS CLI v2 browser login (simplest)
aws login

# Then deploy with one command
MEMORY_DEEPSEEK_API_KEY=sk-... bash aws-deploy.sh
```

## Pipeline Status (2026-05-18)

- Paper trading: **Active** — forced trades every 5 min + natural RSI signals
- Postmortems: **Active** — LanceDB stores analysis for every loss
- Evolution memory: **Active** — vector similarity checks before each trade
- Devil's Advocate: **Active** — LLM reviews every natural signal (relaxed for paper mode)
- 2FA Telegram: Offline (bot token = "test")

## Deployment History

| Date | Commit | Change |
|------|--------|--------|
| 2026-05-18 | `7d35722` | Forced paper trades, relaxed strategy + advocate |
| 2026-05-18 | `749a86a` | Pre-built engine binary (avoids Rust OOM on t2.small) |
| 2026-05-18 | `f706906` | Paper pipeline fixes (advocate, market state, P&L) |
| 2026-05-18 | `dfca196` | Initial AWS deploy via user-data |
