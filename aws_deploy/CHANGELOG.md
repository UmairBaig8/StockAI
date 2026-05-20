# StockAI AWS Deployment Changelog

## 2026-05-21

### Infrastructure Automation
- Created `aws_deploy/` folder with all AWS infrastructure code
- Deployed CloudFormation stack `stockai-scheduler` (Lambda + EventBridge + IAM)
- Allocated Elastic IP `52.70.58.6` (static, replaces dynamic `34.236.237.163`)
- Auto start/stop schedule: Mon-Fri 9:00 AM - 3:30 PM IST
- EBS snapshots: daily on stop, 30-day retention (SEBI audit)
- Estimated cost savings: ~40% ($18/mo vs $30/mo)

### Scripts Created
- `aws_deploy/scripts/setup.sh` — one-command full setup
- `aws_deploy/scripts/teardown.sh` — destroy scheduler resources
- `aws_deploy/scripts/snapshot.sh` — manual EBS snapshot
- `aws_deploy/scripts/status.sh` — comprehensive status check
- `aws_deploy/scripts/logs.sh` — tail service logs

### CloudFormation
- `aws_deploy/cloudformation/stockai-scheduler.yaml` — Lambda + EventBridge scheduler
- Parameters: InstanceId, ElasticIpAllocationId, StartHourUTC, StopHourUTC, SnapshotRetentionDays
- Lambda auto-reassociates EIP on start

## 2026-05-20

### Fresh Deploy
- New EC2 instance `i-0845fd29ea0f8b328` (t3.medium, 20GB EBS)
- Public IP: `34.236.237.163` (later changed to Elastic IP `52.70.58.6`)
- All services running: Memory, Engine, Orchestrator, Redis, PostgreSQL
- Paper trading enabled

### Fixes
- Skip 2FA check in MOCK_MODE (engine)
- Dashboard WS periodic push every 5s
- Fix main.py indentation bug (WS routes orphaned)

## 2026-05-18

### Initial Deploy
- First AWS EC2 deployment
- Forced paper trades every 5 min
- Docker Compose setup with all services
