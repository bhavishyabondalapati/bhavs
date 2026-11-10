#!/usr/bin/env bash
# Run the recommender training job ONCE in the cloud (Fargate; SageMaker training quota is 0 on this account).
# Same container the weekly schedule uses. Prints the task ARN; follow logs with:  aws logs tail /ecs/bhavs-train --follow
# COST: 2 vCPU / 4 GB ARM64 Fargate (Spot) for a few minutes = well under one cent.
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-sky}"
APP="terraform -chdir=infra/app output -raw"
SUBNETS=$($APP task_subnets 2>/dev/null || terraform -chdir=infra/app output -json task_subnets | python3 -c "import sys,json;print(','.join(json.load(sys.stdin)))")
if [ "${SUBNETS#\[}" != "$SUBNETS" ]; then
  SUBNETS=$(terraform -chdir=infra/app output -json task_subnets | python3 -c "import sys,json;print(','.join(json.load(sys.stdin)))")
fi
SG=$($APP task_security_group)
aws ecs run-task --region us-east-2 --cluster "$($APP ecs_cluster)" \
  --task-definition "$($APP train_task_definition)" \
  --capacity-provider-strategy capacityProvider=FARGATE_SPOT,weight=1 \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=ENABLED}" \
  --query 'tasks[0].taskArn' --output text
