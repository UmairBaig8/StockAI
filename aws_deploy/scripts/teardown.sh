#!/bin/bash
set -e
# StockAI AWS — Teardown: destroy all scheduler resources
# Usage: bash aws_deploy/scripts/teardown.sh [--keep-snapshots]

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
REGION="${AWS_REGION:-us-east-1}"
STACK_NAME="stockai-scheduler"
KEEP_SNAPSHOTS=false

if [ "$1" == "--keep-snapshots" ]; then
  KEEP_SNAPSHOTS=true
fi

echo -e "${RED}=== StockAI AWS Teardown ===${NC}"
echo -e "${RED}WARNING: This will delete all scheduler resources.${NC}"

if [ "$KEEP_SNAPSHOTS" == false ]; then
  read -p "Delete EBS snapshots too? (y/N): " confirm
  if [ "$confirm" != "y" ]; then
    KEEP_SNAPSHOTS=true
  fi
fi

# ── 1. Delete CloudFormation stack ──
echo -e "\n${CYAN}>>> Deleting CloudFormation stack...${NC}"
EXISTING=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --region "$REGION" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "not-found")

if [ "$EXISTING" != "not-found" ]; then
  aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION"
  echo "  Waiting for deletion..."
  aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION"
  echo -e "${GREEN}  Stack deleted${NC}"
else
  echo "  Stack not found — skipping"
fi

# ── 2. Delete IAM role (CloudFormation may leave it) ──
echo -e "\n${CYAN}>>> Cleaning up IAM role...${NC}"
ROLE_EXISTS=$(aws iam get-role --role-name stockai-lambda-role --region "$REGION" 2>/dev/null && echo "yes" || echo "no")
if [ "$ROLE_EXISTS" == "yes" ]; then
  # Detach managed policies
  aws iam list-attached-role-policies --role-name stockai-lambda-role \
    --query 'AttachedPolicies[].PolicyArn' --output text | tr '\t' '\n' | while read -r policy; do
    aws iam detach-role-policy --role-name stockai-lambda-role --policy-arn "$policy"
  done
  # Delete inline policies
  aws iam list-role-policies --role-name stockai-lambda-role \
    --query 'PolicyNames[]' --output text | tr '\t' '\n' | while read -r policy; do
    aws iam delete-role-policy --role-name stockai-lambda-role --policy-name "$policy"
  done
  aws iam delete-role --role-name stockai-lambda-role
  echo -e "${GREEN}  IAM role deleted${NC}"
else
  echo "  IAM role not found — skipping"
fi

# ── 3. Delete snapshots (optional) ──
if [ "$KEEP_SNAPSHOTS" == false ]; then
  echo -e "\n${RED}>>> Deleting EBS snapshots...${NC}"
  SNAPSHOTS=$(aws ec2 describe-snapshots --owner-ids self \
    --filters "Name=tag:Purpose,Values=SEBI-audit" \
    --region "$REGION" --query 'Snapshots[*].SnapshotId' --output text 2>/dev/null || echo "")

  if [ -n "$SNAPSHOTS" ] && [ "$SNAPSHOTS" != "None" ]; then
    echo "$SNAPSHOTS" | tr '\t' '\n' | while read -r snap_id; do
      if [ -n "$snap_id" ]; then
        aws ec2 delete-snapshot --snapshot-id "$snap_id" --region "$REGION"
        echo "  Deleted: $snap_id"
      fi
    done
    echo -e "${GREEN}  Snapshots deleted${NC}"
  else
    echo "  No snapshots found — skipping"
  fi
else
  echo -e "\n${CYAN}>>> Keeping EBS snapshots (SEBI audit trail)${NC}"
fi

# ── 4. Release Elastic IP ──
echo -e "\n${CYAN}>>> Releasing Elastic IP...${NC}"
EIP_ALLOC=$(aws ec2 describe-addresses \
  --filters "Name=tag:Name,Values=stockai-eip" \
  --region "$REGION" --query 'Addresses[0].AllocationId' --output text 2>/dev/null || echo "")

if [ -n "$EIP_ALLOC" ] && [ "$EIP_ALLOC" != "None" ]; then
  ASSOC_ID=$(aws ec2 describe-addresses --allocation-ids "$EIP_ALLOC" \
    --region "$REGION" --query 'Addresses[0].AssociationId' --output text 2>/dev/null || echo "")
  if [ -n "$ASSOC_ID" ] && [ "$ASSOC_ID" != "None" ]; then
    aws ec2 disassociate-address --association-id "$ASSOC_ID" --region "$REGION"
  fi
  aws ec2 release-address --allocation-id "$EIP_ALLOC" --region "$REGION"
  echo -e "${GREEN}  Elastic IP released${NC}"
else
  echo "  No Elastic IP found — skipping"
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         StockAI AWS Teardown Complete        ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Scheduler:     DELETED${NC}"
echo -e "${GREEN}║  IAM Role:      DELETED${NC}"
echo -e "${GREEN}║  Elastic IP:    RELEASED${NC}"
if [ "$KEEP_SNAPSHOTS" == false ]; then
  echo -e "${GREEN}║  Snapshots:     DELETED${NC}"
else
  echo -e "${GREEN}║  Snapshots:     KEPT (SEBI audit)${NC}"
fi
echo -e "${GREEN}║  EC2 Instance:  UNCHANGED${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo "  EC2 instance $INSTANCE_ID is still running."
echo "  To terminate: aws ec2 terminate-instances --instance-ids $INSTANCE_ID --region $REGION"
