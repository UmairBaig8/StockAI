#!/bin/bash
set -e
# StockAI AWS — View Service Logs
# Usage: bash aws_deploy/scripts/logs.sh [memory|engine|orchestrator|all] [lines]

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
INSTANCE_ID="${INSTANCE_ID:-i-0845fd29ea0f8b328}"
REGION="${AWS_REGION:-us-east-1}"
KEY_NAME="${KEY_NAME:-stockai-key}"
SERVICE="${1:-all}"
LINES="${2:-50}"

PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --region "$REGION" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text 2>/dev/null || echo "")

if [ -z "$PUBLIC_IP" ] || [ "$PUBLIC_IP" == "None" ]; then
  echo -e "${RED}Cannot get instance IP. Is it running?${NC}"
  exit 1
fi

SSH_CMD="ssh -i ${KEY_NAME}.pem -o StrictHostKeyChecking=no ec2-user@${PUBLIC_IP}"

echo -e "${GREEN}=== StockAI Logs ($SERVICE, last $LINES lines) ===${NC}"
echo "  Instance: $PUBLIC_IP"
echo ""

case "$SERVICE" in
  memory)
    $SSH_CMD "sudo docker logs stockai-memory-1 --tail $LINES"
    ;;
  engine)
    $SSH_CMD "sudo docker logs stockai-engine-1 --tail $LINES"
    ;;
  orchestrator)
    $SSH_CMD "sudo docker logs stockai-orchestrator-1 --tail $LINES"
    ;;
  redis)
    $SSH_CMD "sudo docker logs stockai-redis-1 --tail $LINES"
    ;;
  postgres)
    $SSH_CMD "sudo docker logs stockai-postgres-1 --tail $LINES"
    ;;
  all)
    echo -e "${CYAN}--- Memory ---${NC}"
    $SSH_CMD "sudo docker logs stockai-memory-1 --tail $LINES" 2>/dev/null || echo "  Container not found"
    echo ""
    echo -e "${CYAN}--- Engine ---${NC}"
    $SSH_CMD "sudo docker logs stockai-engine-1 --tail $LINES" 2>/dev/null || echo "  Container not found"
    echo ""
    echo -e "${CYAN}--- Orchestrator ---${NC}"
    $SSH_CMD "sudo docker logs stockai-orchestrator-1 --tail $LINES" 2>/dev/null || echo "  Container not found"
    ;;
  *)
    echo -e "${RED}Unknown service: $SERVICE${NC}"
    echo "  Usage: bash aws_deploy/scripts/logs.sh [memory|engine|orchestrator|redis|postgres|all] [lines]"
    exit 1
    ;;
esac
