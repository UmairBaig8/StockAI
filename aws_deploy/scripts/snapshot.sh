#!/bin/bash
set -e
# StockAI AWS — Manual EBS Snapshot
# Usage: bash aws_deploy/scripts/snapshot.sh [description]

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
INSTANCE_ID="${INSTANCE_ID:-i-0845fd29ea0f8b328}"
REGION="${AWS_REGION:-us-east-1}"
DESC="${1:-StockAI manual snapshot $(date +%Y-%m-%d) (SEBI audit)}"

echo -e "${GREEN}=== StockAI Manual Snapshot ===${NC}"

# Get volume ID
VOLUME_ID=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'Reservations[0].Instances[0].BlockDeviceMappings[0].Ebs.VolumeId' \
  --output text)

echo "  Volume: $VOLUME_ID"
echo "  Description: $DESC"

# Create snapshot
SNAPSHOT_ID=$(aws ec2 create-snapshot \
  --volume-id "$VOLUME_ID" \
  --description "$DESC" \
  --region "$REGION" \
  --query 'SnapshotId' --output text)

echo "  Snapshot ID: $SNAPSHOT_ID"

# Tag it
TAG_DATE=$(date +%Y-%m-%d)
aws ec2 create-tags \
  --resources "$SNAPSHOT_ID" \
  --tags \
    "Key=Name,Value=stockai-$TAG_DATE" \
    "Key=Purpose,Value=SEBI-audit" \
    "Key=InstanceId,Value=$INSTANCE_ID" \
    "Key=CreatedDate,Value=$TAG_DATE"

echo -e "${GREEN}  Snapshot created and tagged${NC}"

# Wait for completion
echo -e "\n${CYAN}>>> Waiting for snapshot completion...${NC}"
aws ec2 wait snapshot-completed --snapshot-ids "$SNAPSHOT_ID" --region "$REGION"
echo -e "${GREEN}  Snapshot complete${NC}"
