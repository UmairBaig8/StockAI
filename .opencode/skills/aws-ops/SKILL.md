# AWS + Git Operations Skill

Manage StockAI AWS infrastructure and Git workflow: deploy, update, start/stop, reset, snapshots.

## Triggers

- "deploy", "update aws", "push and deploy", "git push and update"
- "aws start", "aws stop", "aws status", "aws reset", "aws snapshot"
- "fresh start", "check aws", "aws health", "aws logs"
- "commit and deploy", "update to latest", "latest fixes"

## Quick Reference

| Field | Value |
|-------|-------|
| **Instance ID** | `i-0845fd29ea0f8b328` |
| **Elastic IP** | `52.70.58.6` (static) |
| **Region** | `us-east-1` |
| **Key Pair** | `stockai-key.pem` (repo root) |
| **Scheduler** | Mon-Fri 9:00 AM - 3:30 PM IST (auto) |

## Workflows

### Update (commit → push → deploy)

```bash
# Check what changed
git status
git diff --stat

# Commit
git add . && git commit -m "type: message"

# Push
git push

# Update instance
bash aws-update.sh
```

### Quick Update (already pushed)

```bash
bash aws-update.sh
```

### Start Instance (if stopped)

```bash
aws lambda invoke --function-name stockai-scheduler --payload '{"action":"start"}' /dev/stdout
```

### Stop Instance (creates snapshot first)

```bash
aws lambda invoke --function-name stockai-scheduler --payload '{"action":"stop"}' /dev/stdout
```

### Reset Data (fresh start)

```bash
ssh -i stockai-key.pem ec2-user@52.70.58.6 'sudo docker exec stockai-postgres-1 psql -U stockai -d stockai -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
ssh -i stockai-key.pem ec2-user@52.70.58.6 'sudo docker exec stockai-redis-1 redis-cli FLUSHALL'
ssh -i stockai-key.pem ec2-user@52.70.58.6 'sudo docker exec stockai-memory-1 rm -rf /data/lancedb/*'
ssh -i stockai-key.pem ec2-user@52.70.58.6 'sudo docker restart stockai-memory-1 stockai-orchestrator-1 stockai-engine-1'
```

### Status Check

```bash
bash aws_deploy/scripts/status.sh
```

### View Logs

```bash
bash aws_deploy/scripts/logs.sh memory       # Memory
bash aws_deploy/scripts/logs.sh engine       # Engine
bash aws_deploy/scripts/logs.sh orchestrator  # Orchestrator
bash aws_deploy/scripts/logs.sh all           # All
```

### Manual Snapshot

```bash
bash aws_deploy/scripts/snapshot.sh "Manual $(date +%Y-%m-%d)"
```

### Fresh Deploy (new instance)

```bash
# Build execution binary first
cargo build --release --manifest-path execution/Cargo.toml
cp execution/target/release/execution-bin execution/execution-bin

# Deploy
bash aws-deploy.sh
```

## Git Quick Commands

```bash
git status                    # Check changes
git diff                      # See diffs
git log --oneline -10         # Last 10 commits
git branch                    # Current branch
git stash                     # Stash changes
git stash pop                 # Restore stashed
git reset --hard HEAD         # Discard local changes
git pull origin main          # Pull latest
```

## File Locations

| File | Purpose |
|------|---------|
| `aws_deploy/README.md` | Full AWS documentation |
| `aws_deploy/scripts/setup.sh` | One-command AWS setup |
| `aws_deploy/scripts/status.sh` | Status check |
| `aws_deploy/scripts/logs.sh` | View service logs |
| `aws_deploy/scripts/snapshot.sh` | Manual EBS snapshot |
| `aws_deploy/scripts/teardown.sh` | Destroy AWS resources |
| `aws-update.sh` | Update running instance |
| `aws-deploy.sh` | Fresh deploy (new instance) |
| `aws_env.md` | Quick AWS reference |
