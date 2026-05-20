# StockAI AWS Infrastructure

> **For AI agents:** This folder contains all AWS infrastructure code, deployment scripts, and operational runbooks. Read this file first before any AWS operations.

## Quick Reference

| Field | Value |
|-------|-------|
| **Instance ID** | `i-0845fd29ea0f8b328` |
| **Elastic IP** | `52.70.58.6` (static, never changes) |
| **EIP Allocation ID** | `eipalloc-044a7a75729bf849b` |
| **Region** | `us-east-1` (N. Virginia) |
| **Type** | `t3.medium` (2 vCPU, 4 GB RAM) |
| **EBS** | 20 GB gp3 |
| **Key Pair** | `stockai-key.pem` (repo root) |
| **Security Group** | `sg-0e816e1f85a798bf1` |
| **Account** | `arn:aws:iam::453767499603:root` |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    AWS Cloud (us-east-1)                        │
│                                                                 │
│  ┌─────────────┐    ┌──────────────────────────────────────┐   │
│  │ EventBridge │    │         Lambda: stockai-scheduler     │   │
│  │ 9:00 AM IST │───▶│   action: start                       │   │
│  │ Mon-Fri     │    │   → EC2 start                         │   │
│  └─────────────┘    │   → Wait running                      │   │
│                     │   → Associate Elastic IP              │   │
│  ┌─────────────┐    └──────────────────────────────────────┘   │
│  │ EventBridge │                                                 │
│  │ 3:30 PM IST │───┐                                            │
│  │ Mon-Fri     │   │   ┌──────────────────────────────────────┐ │
│  └─────────────┘   └──▶│         Lambda: stockai-scheduler     │ │
│                         │   action: stop                        │ │
│                         │   → Create EBS snapshot               │ │
│                         │   → EC2 stop                          │ │
│                         │   → Prune snapshots >30 days          │ │
│                         └──────────────────────────────────────┘ │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  EC2: i-0845fd29ea0f8b328 (t3.medium)                    │   │
│  │  Elastic IP: 52.70.58.6 (static)                         │   │
│  │                                                          │   │
│  │  ┌────────────────────────────────────────────────────┐ │   │
│  │  │  Docker Compose                                     │ │   │
│  │  │  ┌───────┐ ┌────────┐ ┌─────────┐ ┌──────────┐    │ │   │
│  │  │  │Redis  │ │Postgres│ │ Memory  │ │Orchestr. │    │ │   │
│  │  │  │:6379  │ │ :5432  │ │ :8000   │ │ :8080    │    │ │   │
│  │  │  └───────┘ └────────┘ └─────────┘ └──────────┘    │ │   │
│  │  │  ┌──────────┐                                      │ │   │
│  │  │  │ Engine   │                                      │ │   │
│  │  │  │ :9001    │                                      │ │   │
│  │  │  └──────────┘                                      │ │   │
│  │  └────────────────────────────────────────────────────┘ │   │
│  │                                                          │   │
│  │  EBS Volume: snapshotted daily, 30-day retention         │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Schedule

| Event | Time (IST) | Time (UTC) | Action |
|-------|------------|------------|--------|
| **Start** | 8:30 AM | 3:00 | Start EC2 → wait running → associate EIP |
| **Stop** | 3:30 PM | 10:00 | Snapshot EBS → stop EC2 → prune old snapshots |

Days: **Mon-Fri only** (no weekend trading).

## Cost Breakdown

| Item | 24/7 Cost | Scheduled Cost | Notes |
|------|-----------|----------------|-------|
| t3.medium EC2 | ~$30/mo | ~$13/mo | 6.5 hrs/day × 22 days |
| Elastic IP | Free | ~$3.60/mo | Free when attached, $0.005/hr when stopped |
| EBS snapshots | — | ~$1.50/mo | 30 × 20GB daily |
| Lambda | Free | Free | 2 invocations/day, well within free tier |
| EventBridge | Free | Free | 1M events/mo free |
| **Total** | **~$30/mo** | **~$18/mo** | **~40% savings** |

## File Structure

```
aws_deploy/
├── README.md                    # This file — full documentation
├── cloudformation/
│   └── stockai-scheduler.yaml   # Lambda + EventBridge + IAM (auto start/stop)
├── scripts/
│   ├── setup.sh                 # One-command full setup (first time)
│   ├── teardown.sh              # Destroy all AWS resources
│   ├── snapshot.sh              # Manual EBS snapshot
│   ├── status.sh                # Check instance + services + snapshots
│   └── logs.sh                  # Tail service logs
├── .env.example                 # Environment template (never commit real .env)
└── CHANGELOG.md                 # Deployment history
```

## Setup (First Time)

### Prerequisites

1. AWS CLI installed and authenticated
2. EC2 instance running (`aws-deploy.sh` from repo root)
3. `execution/execution-bin` built and available
4. `.env` file in repo root

### One-Command Setup

```bash
bash aws_deploy/scripts/setup.sh
```

This does:
1. Allocates Elastic IP (if not exists) → associates with instance
2. Deploys CloudFormation stack (Lambda + EventBridge + IAM)
3. Updates `aws_env.md` with static IP
4. Verifies all resources

### Manual Setup Steps

If you need to run steps individually:

```bash
# 1. Allocate Elastic IP (skip if already have one)
aws ec2 allocate-address --domain vpc --region us-east-1

# 2. Associate with instance
aws ec2 associate-address \
  --instance-id i-0845fd29ea0f8b328 \
  --allocation-id eipalloc-044a7a75729bf849b \
  --region us-east-1

# 3. Deploy CloudFormation stack
aws cloudformation create-stack \
  --stack-name stockai-scheduler \
  --template-body file://aws_deploy/cloudformation/stockai-scheduler.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1

# 4. Wait for completion
aws cloudformation wait stack-create-complete \
  --stack-name stockai-scheduler --region us-east-1
```

## Operations

### Check Status

```bash
bash aws_deploy/scripts/status.sh
```

Or manually:

```bash
# Instance state
aws ec2 describe-instances \
  --instance-ids i-0845fd29ea0f8b328 \
  --region us-east-1 \
  --query 'Reservations[0].Instances[0].State.Name' --output text

# EIP association
aws ec2 describe-addresses \
  --allocation-ids eipalloc-044a7a75729bf849b \
  --region us-east-1 \
  --query 'Addresses[0].[PublicIp,InstanceId]' --output table

# Docker services
ssh -i stockai-key.pem ec2-user@52.70.58.6 \
  'sudo docker compose -f /root/stockai/docker-compose.yml ps'

# Health check
curl -s http://52.70.58.6:8000/api/v1/health
```

### Manual Start/Stop

```bash
# Start (also re-associates EIP)
aws lambda invoke \
  --function-name stockai-scheduler \
  --payload '{"action":"start"}' \
  /dev/stdout

# Stop (creates snapshot first)
aws lambda invoke \
  --function-name stockai-scheduler \
  --payload '{"action":"stop"}' \
  /dev/stdout
```

### Manual Snapshot

```bash
bash aws_deploy/scripts/snapshot.sh
```

Or:

```bash
VOLUME_ID=$(aws ec2 describe-instances \
  --instance-ids i-0845fd29ea0f8b328 \
  --region us-east-1 \
  --query 'Reservations[0].Instances[0].BlockDeviceMappings[0].Ebs.VolumeId' \
  --output text)

aws ec2 create-snapshot \
  --volume-id $VOLUME_ID \
  --description "StockAI manual snapshot $(date +%Y-%m-%d) (SEBI audit)" \
  --region us-east-1
```

### View Snapshots

```bash
aws ec2 describe-snapshots \
  --owner-ids self \
  --filters "Name=tag:Purpose,Values=SEBI-audit" \
  --region us-east-1 \
  --query 'Snapshots[].[SnapshotId,StartTime,Description]' \
  --output table
```

### View Logs

```bash
bash aws_deploy/scripts/logs.sh memory     # Memory service
bash aws_deploy/scripts/logs.sh engine     # Engine service
bash aws_deploy/scripts/logs.sh orchestrator  # Orchestrator
bash aws_deploy/scripts/logs.sh all        # All services
```

### Update Code on Running Instance

```bash
bash aws-update.sh              # reads IP from aws_env.md
bash aws-update.sh 52.70.58.6   # specific IP
```

### Enable Paper Trading

```bash
ssh -i stockai-key.pem ec2-user@52.70.58.6 \
  'sudo docker exec stockai-redis-1 redis-cli SET 2fa:active "paper-mode"'
```

### Free Disk Space

```bash
ssh -i stockai-key.pem ec2-user@52.70.58.6 \
  'sudo bash -c "cd /root/stockai && docker compose down && docker system prune -af --volumes && docker compose up -d"'
```

## Modification Guide

### Change Start/Stop Times

Edit `cloudformation/stockai-scheduler.yaml`:

```yaml
Parameters:
  StartHourUTC:
    Default: 3    # Change this (UTC hour)
  StopHourUTC:
    Default: 10   # Change this (UTC hour)
```

Then update:

```bash
aws cloudformation update-stack \
  --stack-name stockai-scheduler \
  --template-body file://aws_deploy/cloudformation/stockai-scheduler.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1

aws cloudformation wait stack-update-complete \
  --stack-name stockai-scheduler --region us-east-1
```

**UTC to IST conversion:** IST = UTC + 5:30

| IST | UTC | Parameter |
|-----|-----|-----------|
| 8:00 AM | 2:30 | StartHourUTC: 2 (cron minute handles :30) |
| 9:00 AM | 3:30 | StartHourUTC: 3 |
| 3:00 PM | 9:30 | StopHourUTC: 9 |
| 3:30 PM | 10:00 | StopHourUTC: 10 |

### Change Snapshot Retention

Edit `cloudformation/stockai-scheduler.yaml`:

```yaml
Parameters:
  SnapshotRetentionDays:
    Default: 30   # Change this (SEBI requires minimum 30 days)
```

Then update stack (same command as above).

### Change Instance Type

1. Stop instance first
2. Change type in AWS Console or:

```bash
aws ec2 modify-instance-attribute \
  --instance-id i-0845fd29ea0f8b328 \
  --instance-type '{"Value": "t3.large"}' \
  --region us-east-1
```

3. Start instance

### Add New AWS Resource

Add to `cloudformation/stockai-scheduler.yaml` under `Resources:`, then update stack.

### Change IAM Permissions

Edit `LambdaExecutionRole` → `Policies` → `PolicyDocument` → `Statement` → `Action` in the CloudFormation template.

## Teardown

### Remove Scheduler Only

```bash
aws cloudformation delete-stack \
  --stack-name stockai-scheduler --region us-east-1

aws cloudformation wait stack-delete-complete \
  --stack-name stockai-scheduler --region us-east-1
```

### Full Teardown (Everything)

```bash
bash aws_deploy/scripts/teardown.sh
```

Or manually:

```bash
# 1. Delete CloudFormation stack
aws cloudformation delete-stack --stack-name stockai-scheduler --region us-east-1

# 2. Release Elastic IP
aws ec2 disassociate-address --association-id <assoc-id> --region us-east-1
aws ec2 release-address --allocation-id eipalloc-044a7a75729bf849b --region us-east-1

# 3. Delete snapshots (optional — keep for SEBI audit)
aws ec2 describe-snapshots --owner-ids self \
  --filters "Name=tag:Purpose,Values=SEBI-audit" \
  --region us-east-1 --query 'Snapshots[*].SnapshotId' --output text \
  | tr '\t' '\n' | xargs -I {} aws ec2 delete-snapshot --snapshot-id {} --region us-east-1

# 4. Terminate EC2
aws ec2 terminate-instances --instance-ids i-0845fd29ea0f8b328 --region us-east-1

# 5. Delete security group
aws ec2 delete-security-group --group-id sg-0e816e1f85a798bf1 --region us-east-1
```

## SEBI Audit Trail

Snapshots are tagged for compliance:

| Tag | Value |
|-----|-------|
| `Purpose` | `SEBI-audit` |
| `InstanceId` | `i-0845fd29ea0f8b328` |
| `CreatedDate` | `YYYY-MM-DD` |
| `Name` | `stockai-YYYY-MM-DD` |

To export audit trail:

```bash
aws ec2 describe-snapshots \
  --owner-ids self \
  --filters "Name=tag:Purpose,Values=SEBI-audit" \
  --region us-east-1 \
  --query 'Snapshots[].[Tags[?Key==`CreatedDate`].Value|[0],SnapshotId,StartTime]' \
  --output table
```

## Troubleshooting

### Instance won't start

```bash
# Check state
aws ec2 describe-instances --instance-ids i-0845fd29ea0f8b328 \
  --region us-east-1 --query 'Reservations[0].Instances[0].State' --output json

# Force start
aws ec2 start-instances --instance-ids i-0845fd29ea0f8b328 --region us-east-1
```

### EIP not associated after start

```bash
# Check association
aws ec2 describe-addresses --allocation-ids eipalloc-044a7a75729bf849b \
  --region us-east-1

# Re-associate manually
aws ec2 associate-address \
  --instance-id i-0845fd29ea0f8b328 \
  --allocation-id eipalloc-044a7a75729bf849b \
  --region us-east-1
```

### Lambda errors

```bash
# Check CloudWatch logs
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/stockai-scheduler \
  --region us-east-1

# View last 50 log events
aws logs tail /aws/lambda/stockai-scheduler --region us-east-1
```

### CloudFormation stuck

```bash
# Check events
aws cloudformation describe-stack-events \
  --stack-name stockai-scheduler --region us-east-1 \
  --query 'StackEvents[].[LogicalResourceId,ResourceStatus,ResourceStatusReason]' \
  --output table
```

### Snapshot failed

```bash
# Check snapshot status
aws ec2 describe-snapshots \
  --snapshot-ids <snapshot-id> \
  --region us-east-1 \
  --query 'Snapshots[0].[State,StateMessage]' --output table
```

## Deployment History

| Date | Change | Author |
|------|--------|--------|
| 2026-05-21 | CloudFormation scheduler (Lambda + EventBridge) deployed | Agent |
| 2026-05-21 | Elastic IP allocated (52.70.58.6) and associated | Agent |
| 2026-05-21 | aws_deploy/ folder created with all scripts | Agent |
| 2026-05-20 | Fresh EC2 deploy on new instance (34.236.237.163 → 52.70.58.6) | Agent |
| 2026-05-18 | Initial AWS deploy | Agent |
