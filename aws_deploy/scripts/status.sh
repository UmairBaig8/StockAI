#!/bin/bash
set -e
# StockAI AWS — Status Check
# Usage: bash aws_deploy/scripts/status.sh

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
INSTANCE_ID="${INSTANCE_ID:-i-0845fd29ea0f8b328}"
REGION="${AWS_REGION:-us-east-1}"
KEY_NAME="${KEY_NAME:-stockai-key}"

echo -e "${GREEN}=== StockAI AWS Status ===${NC}"

# ── 1. Instance State ──
echo -e "\n${CYAN}>>> Instance${NC}"
aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
  --query 'Reservations[0].Instances[0].[InstanceId,State.Name,InstanceType,PublicIpAddress,LaunchTime]' \
  --output table

# ── 2. Elastic IP ──
echo -e "\n${CYAN}>>> Elastic IP${NC}"
aws ec2 describe-addresses \
  --filters "Name=tag:Name,Values=stockai-eip" \
  --region "$REGION" \
  --query 'Addresses[0].[PublicIp,InstanceId,AssociationId,AllocationId]' \
  --output table 2>/dev/null || echo "  No Elastic IP found"

# ── 3. CloudFormation Stack ──
echo -e "\n${CYAN}>>> CloudFormation Stack${NC}"
STACK_STATUS=$(aws cloudformation describe-stacks --stack-name stockai-scheduler \
  --region "$REGION" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "not-found")

if [ "$STACK_STATUS" != "not-found" ]; then
  echo "  Status: $STACK_STATUS"
  aws cloudformation describe-stack-resources --stack-name stockai-scheduler \
    --region "$REGION" --query 'StackResources[].[LogicalResourceId,ResourceType,ResourceStatus]' \
    --output table
else
  echo "  Stack not found"
fi

# ── 4. Lambda Function ──
echo -e "\n${CYAN}>>> Lambda Function${NC}"
LAMBDA_STATUS=$(aws lambda get-function --function-name stockai-scheduler \
  --region "$REGION" --query 'Configuration.[FunctionName,Runtime,Timeout,State]' \
  --output table 2>/dev/null || echo "  Function not found")
echo "$LAMBDA_STATUS"

# ── 5. EventBridge Rules ──
echo -e "\n${CYAN}>>> EventBridge Rules${NC}"
aws events list-rules --name-prefix stockai --region "$REGION" \
  --query 'Rules[].[Name,State,ScheduleExpression]' --output table 2>/dev/null || echo "  No rules found"

# ── 6. Snapshots ──
echo -e "\n${CYAN}>>> EBS Snapshots (last 10)${NC}"
SNAPSHOT_COUNT=$(aws ec2 describe-snapshots --owner-ids self \
  --filters "Name=tag:Purpose,Values=SEBI-audit" \
  --region "$REGION" --query 'length(Snapshots)' --output text 2>/dev/null || echo "0")
echo "  Total snapshots: $SNAPSHOT_COUNT"
aws ec2 describe-snapshots --owner-ids self \
  --filters "Name=tag:Purpose,Values=SEBI-audit" \
  --region "$REGION" --max-items 10 \
  --query 'Snapshots[].[Tags[?Key==`CreatedDate`].Value|[0],SnapshotId,StartTime,State]' \
  --output table 2>/dev/null || echo "  No snapshots found"

# ── 7. Docker Services (if running) ──
echo -e "\n${CYAN}>>> Docker Services${NC}"
INSTANCE_STATE=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --region "$REGION" --query 'Reservations[0].Instances[0].State.Name' --output text)

if [ "$INSTANCE_STATE" == "running" ]; then
  PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
    --region "$REGION" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)

  echo "  Instance running — checking services..."
  ssh -i "${KEY_NAME}.pem" -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
    ec2-user@"$PUBLIC_IP" 'sudo docker compose -f /root/stockai/docker-compose.yml ps' 2>/dev/null || \
    echo "  Could not connect via SSH"

  echo -e "\n  Health check:"
  curl -sf "http://$PUBLIC_IP:8000/api/v1/health" 2>/dev/null || echo "  Health check failed"
else
  echo "  Instance is $INSTANCE_STATE — services not available"
fi

# ── 8. Disk Usage ──
echo -e "\n${CYAN}>>> EBS Volume${NC}"
VOLUME_ID=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'Reservations[0].Instances[0].BlockDeviceMappings[0].Ebs.VolumeId' \
  --output text 2>/dev/null || echo "not-found")

if [ "$VOLUME_ID" != "not-found" ]; then
  aws ec2 describe-volumes --volume-ids "$VOLUME_ID" --region "$REGION" \
    --query 'Volumes[0].[VolumeId,Size,VolumeType,State]' --output table
fi
