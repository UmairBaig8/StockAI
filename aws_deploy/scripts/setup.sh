#!/bin/bash
set -e
# StockAI AWS — Full Setup: Elastic IP + CloudFormation scheduler
# Usage: bash aws_deploy/scripts/setup.sh
# Prerequisites: AWS CLI authenticated, EC2 instance running

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'

INSTANCE_ID="${INSTANCE_ID:-i-0845fd29ea0f8b328}"
REGION="${AWS_REGION:-us-east-1}"
STACK_NAME="stockai-scheduler"
KEY_NAME="${KEY_NAME:-stockai-key}"

echo -e "${GREEN}=== StockAI AWS Setup ===${NC}"

# ── 1. Verify AWS auth ──
if ! aws sts get-caller-identity &>/dev/null; then
  echo -e "${RED}AWS CLI not authenticated. Run: aws login${NC}"
  exit 1
fi

# ── 2. Verify instance exists ──
STATE=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --region "$REGION" --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null || echo "not-found")

if [ "$STATE" == "not-found" ]; then
  echo -e "${RED}Instance $INSTANCE_ID not found. Run aws-deploy.sh first.${NC}"
  exit 1
fi

echo -e "${CYAN}>>> Instance $INSTANCE_ID state: $STATE${NC}"

# ── 3. Allocate Elastic IP (if not exists) ──
echo -e "\n${CYAN}>>> Checking Elastic IP...${NC}"

EIP_ALLOC=$(aws ec2 describe-addresses \
  --filters "Name=tag:Name,Values=stockai-eip" \
  --region "$REGION" --query 'Addresses[0].AllocationId' --output text 2>/dev/null || echo "")

if [ -z "$EIP_ALLOC" ] || [ "$EIP_ALLOC" == "None" ]; then
  echo "  Allocating new Elastic IP..."
  EIP_ALLOC=$(aws ec2 allocate-address --domain vpc --region "$REGION" \
    --query 'AllocationId' --output text)
  PUBLIC_IP=$(aws ec2 describe-addresses --allocation-ids "$EIP_ALLOC" \
    --region "$REGION" --query 'Addresses[0].PublicIp' --output text)
  aws ec2 create-tags --resources "$EIP_ALLOC" \
    --tags "Key=Name,Value=stockai-eip" "Key=Purpose,Value=StockAI-static-ip"
  echo "  Allocated: $PUBLIC_IP ($EIP_ALLOC)"
else
  PUBLIC_IP=$(aws ec2 describe-addresses --allocation-ids "$EIP_ALLOC" \
    --region "$REGION" --query 'Addresses[0].PublicIp' --output text)
  echo "  Using existing: $PUBLIC_IP ($EIP_ALLOC)"
fi

# ── 4. Associate EIP ──
echo -e "\n${CYAN}>>> Associating Elastic IP...${NC}"

ASSOC_ID=$(aws ec2 describe-addresses --allocation-ids "$EIP_ALLOC" \
  --region "$REGION" --query 'Addresses[0].AssociationId' --output text 2>/dev/null || echo "")

if [ -n "$ASSOC_ID" ] && [ "$ASSOC_ID" != "None" ]; then
  CURRENT_INSTANCE=$(aws ec2 describe-addresses --allocation-ids "$EIP_ALLOC" \
    --region "$REGION" --query 'Addresses[0].InstanceId' --output text)
  if [ "$CURRENT_INSTANCE" == "$INSTANCE_ID" ]; then
    echo "  Already associated with $INSTANCE_ID"
  else
    echo "  Re-associating from $CURRENT_INSTANCE to $INSTANCE_ID..."
    aws ec2 associate-address --instance-id "$INSTANCE_ID" \
      --allocation-id "$EIP_ALLOC" --region "$REGION"
  fi
else
  aws ec2 associate-address --instance-id "$INSTANCE_ID" \
    --allocation-id "$EIP_ALLOC" --region "$REGION"
  echo "  Associated: $PUBLIC_IP → $INSTANCE_ID"
fi

# ── 5. Deploy CloudFormation ──
echo -e "\n${CYAN}>>> Deploying CloudFormation stack...${NC}"

EXISTING=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --region "$REGION" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "not-found")

TEMPLATE="aws_deploy/cloudformation/stockai-scheduler.yaml"

if [ ! -f "$TEMPLATE" ]; then
  echo -e "${RED}Template not found: $TEMPLATE${NC}"
  exit 1
fi

if [ "$EXISTING" == "not-found" ]; then
  echo "  Creating new stack..."
  aws cloudformation create-stack \
    --stack-name "$STACK_NAME" \
    --template-body "file://$TEMPLATE" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION"
  echo "  Waiting for creation (~2 min)..."
  aws cloudformation wait stack-create-complete --stack-name "$STACK_NAME" --region "$REGION"
elif [ "$EXISTING" == "CREATE_COMPLETE" ] || [ "$EXISTING" == "UPDATE_COMPLETE" ]; then
  echo "  Stack exists — updating..."
  aws cloudformation update-stack \
    --stack-name "$STACK_NAME" \
    --template-body "file://$TEMPLATE" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION"
  echo "  Waiting for update (~2 min)..."
  aws cloudformation wait stack-update-complete --stack-name "$STACK_NAME" --region "$REGION"
elif [ "$EXISTING" == "ROLLBACK_COMPLETE" ] || [ "$EXISTING" == "DELETE_FAILED" ]; then
  echo "  Stack in $EXISTING state — deleting and recreating..."
  aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$REGION"
  aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$REGION"
  aws cloudformation create-stack \
    --stack-name "$STACK_NAME" \
    --template-body "file://$TEMPLATE" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION"
  aws cloudformation wait stack-create-complete --stack-name "$STACK_NAME" --region "$REGION"
else
  echo -e "${RED}Stack in unexpected state: $EXISTING${NC}"
  exit 1
fi

echo -e "${GREEN}  Stack deployed successfully${NC}"

# ── 6. Update aws_env.md ──
echo -e "\n${CYAN}>>> Updating aws_env.md with static IP...${NC}"

if [ -f "aws_env.md" ]; then
  sed -i '' "s/\*\*Public IP\*\*.*|/**Public IP** | \`$PUBLIC_IP\` (Elastic IP — static) |/" aws_env.md
  sed -i '' "s/34\.236\.237\.163/$PUBLIC_IP/g" aws_env.md
  echo "  Updated aws_env.md"
else
  echo -e "${RED}aws_env.md not found — skipping${NC}"
fi

# ── 7. Verify ──
echo -e "\n${CYAN}>>> Verifying setup...${NC}"

LAMBDA_ARN=$(aws lambda get-function --function-name stockai-scheduler \
  --region "$REGION" --query 'Configuration.FunctionArn' --output text 2>/dev/null || echo "not-found")

EIP_STATUS=$(aws ec2 describe-addresses --allocation-ids "$EIP_ALLOC" \
  --region "$REGION" --query 'Addresses[0].[PublicIp,InstanceId]' --output text)

echo "  Lambda: $LAMBDA_ARN"
echo "  EIP: $EIP_STATUS"

# ── 8. Summary ──
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           StockAI AWS Setup Complete!                ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Static IP:    $PUBLIC_IP${NC}"
echo -e "${GREEN}║  Instance:     $INSTANCE_ID${NC}"
echo -e "${GREEN}║  Scheduler:    Mon-Fri 9:00 AM - 3:30 PM IST${NC}"
echo -e "${GREEN}║  Snapshots:    Daily EBS, 30-day retention${NC}"
echo -e "${GREEN}║  Monthly Cost: ~$18 (vs ~$30 24/7)${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Dashboard:    http://$PUBLIC_IP:8000${NC}"
echo -e "${GREEN}║  SSH:          ssh -i ${KEY_NAME}.pem ec2-user@$PUBLIC_IP${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Test start:  aws lambda invoke --function-name stockai-scheduler --payload '{\"action\":\"start\"}' /dev/stdout"
echo "  Test stop:   aws lambda invoke --function-name stockai-scheduler --payload '{\"action\":\"stop\"}' /dev/stdout"
echo "  Status:      bash aws_deploy/scripts/status.sh"
echo "  Teardown:    bash aws_deploy/scripts/teardown.sh"
