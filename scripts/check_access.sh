#!/usr/bin/env bash
# Phase 0: verify this AWS account can use every service bhavs needs.
# Read-only except one tiny Bedrock embedding call (a fraction of a cent).
# Usage: scripts/check_access.sh   (or: make check-access)
set -uo pipefail

export AWS_PROFILE="${AWS_PROFILE:-sky}"
export AWS_REGION="us-east-2"
export AWS_DEFAULT_REGION="us-east-2"
export AWS_PAGER=""

PASS=0; FAIL=0; WARN=0
BLOCKED=()

ok()   { printf "  \033[32mPASS\033[0m  %s\n" "$1"; PASS=$((PASS+1)); }
bad()  { printf "  \033[31mFAIL\033[0m  %s\n        -> fallback: %s\n" "$1" "$2"; FAIL=$((FAIL+1)); BLOCKED+=("$1"); }
warn() { printf "  \033[33mWARN\033[0m  %s\n" "$1"; WARN=$((WARN+1)); }

# run <label> <fallback> <cmd...> : PASS if the command exits 0
run() {
  local label="$1" fallback="$2"; shift 2
  local out
  if out=$("$@" 2>&1); then ok "$label"; else
    bad "$label  [$(echo "$out" | tr '\n' ' ' | cut -c1-140)]" "$fallback"
  fi
}

echo "Profile=$AWS_PROFILE Region=$AWS_REGION"
if ! ID=$(aws sts get-caller-identity --query Account --output text 2>&1); then
  echo "Credentials not working: $ID"
  echo "Run: aws login --profile $AWS_PROFILE"
  exit 2
fi
echo "Account: $ID"
aws sts get-caller-identity --query Arn --output text

echo; echo "== Video: MediaConvert =="
run "MediaConvert describe-endpoints" \
  "ffmpeg inside a container Lambda/Fargate (needs your approval) or transcode locally and upload HLS" \
  aws mediaconvert describe-endpoints --max-results 1
EP=$(aws mediaconvert describe-endpoints --query 'Endpoints[0].Url' --output text 2>/dev/null)
if [ -n "${EP:-}" ] && [ "$EP" != "None" ]; then
  run "MediaConvert list-queues (account endpoint)" "see above" \
    aws mediaconvert list-queues --endpoint-url "$EP" --max-items 1
fi

echo; echo "== Embeddings: Bedrock =="
if aws bedrock list-foundation-models --by-output-modality EMBEDDING \
     --query 'modelSummaries[].modelId' --output text >/tmp/bhavs_models.txt 2>&1; then
  ok "Bedrock lists embedding models: $(tr '\t' ' ' </tmp/bhavs_models.txt | cut -c1-110)"
else
  bad "Bedrock list-foundation-models" "small open-source model (e.g. all-MiniLM-L6-v2) in a container Lambda"
fi
BODY=$(mktemp); OUT=$(mktemp)
echo '{"inputText":"short sci-fi with robots","dimensions":256,"normalize":true}' > "$BODY"
for M in amazon.titan-embed-text-v2:0 cohere.embed-english-v3; do
  B="$BODY"
  [ "$M" = cohere.embed-english-v3 ] && { B=$(mktemp); echo '{"texts":["short sci-fi with robots"],"input_type":"search_query"}' > "$B"; }
  if err=$(aws bedrock-runtime invoke-model --model-id "$M" --body fileb://"$B" \
        --content-type application/json "$OUT" 2>&1); then
    ok "Bedrock invoke $M (vector returned)"
  else
    warn "Bedrock invoke $M failed: $(echo "$err" | tr '\n' ' ' | cut -c1-130)"
  fi
done
rm -f "$BODY" "$OUT"

echo; echo "== Analytics: Firehose / Glue / Athena / S3 =="
run "Firehose list-delivery-streams" \
  "API writes JSONL straight to S3 via Lambda batching; Glue crawler/ETL converts to Parquet" \
  aws firehose list-delivery-streams --limit 1
run "Kinesis Data Streams list-streams" "SQS buffer + batch Lambda writing to S3" aws kinesis list-streams --limit 1
run "ECR describe-repositories (container fallbacks)" "none" aws ecr describe-repositories --max-items 1
run "ECS list-clusters (Fargate fallback)" "none" aws ecs list-clusters --max-items 1
run "SQS list-queues" "none" aws sqs list-queues --max-items 1
run "Glue get-databases" "none needed for Athena DDL: create tables with Athena CREATE EXTERNAL TABLE" \
  aws glue get-databases --max-results 1
run "Athena list-work-groups" "query the S3 data locally with DuckDB" \
  aws athena list-work-groups --max-results 1
run "S3 list-buckets" "none (S3 is required)" aws s3api list-buckets --max-items 1

echo; echo "== ML: SageMaker =="
run "SageMaker list-training-jobs" \
  "container-image Lambda (15 min / 10 GB) or train locally on mps and upload artifacts" \
  aws sagemaker list-training-jobs --max-results 1
Q=$(aws service-quotas list-service-quotas --service-code sagemaker --max-results 100 \
     --query "Quotas[?contains(QuotaName,'ml.m5.large for training job usage')].[QuotaName,Value]" \
     --output text 2>/dev/null | head -1)
if [ -z "$Q" ]; then
  # paginate fully
  Q=$(aws service-quotas list-service-quotas --service-code sagemaker \
     --query "Quotas[?contains(QuotaName,'ml.m5.large for training job usage')].[QuotaName,Value]" \
     --output text 2>/dev/null | head -1)
fi
if [ -n "$Q" ]; then
  VAL=$(echo "$Q" | awk '{print $NF}')
  if awk "BEGIN{exit !($VAL>=1)}"; then ok "SageMaker quota: $Q"; else
    bad "SageMaker ml.m5.large training quota is $VAL" "request quota increase, try ml.m5.xlarge/ml.c5.xlarge, or container Lambda"; fi
else
  warn "Could not read SageMaker training quota (service-quotas may be restricted)"
fi

echo; echo "== Platform services Terraform will use =="
run "Cognito list-user-pools"        "none (required)"           aws cognito-idp list-user-pools --max-results 1
run "DynamoDB list-tables"           "none (required)"           aws dynamodb list-tables --max-items 1
run "API Gateway v2 get-apis"        "Lambda function URLs + CloudFront" aws apigatewayv2 get-apis --max-items 1
run "Lambda list-functions"          "none (required)"           aws lambda list-functions --max-items 1
run "EventBridge list-rules"         "S3 notifications direct to Lambda" aws events list-rules --limit 1
run "EventBridge Scheduler"          "EventBridge rule with schedule expression" aws scheduler list-schedules --max-results 1
run "CloudFront list-distributions"  "S3 presigned URLs (no signed cookies)" aws cloudfront list-distributions --max-items 1
run "SSM Parameter Store"            "Secrets Manager (~\$0.40/mo/secret)" aws ssm describe-parameters --max-results 1
run "CloudWatch list-dashboards"     "none (nice to have)"       aws cloudwatch list-dashboards
run "X-Ray get-sampling-rules"       "skip tracing"              aws xray get-sampling-rules --max-items 1
run "Route 53 list-hosted-zones"     "Option B (token header) instead of custom stream domain" aws route53 list-hosted-zones --max-items 1
run "ACM list-certificates (us-east-1 needed for CloudFront)" \
  "you said us-east-1 is blocked: CloudFront certs MUST live in us-east-1 -> see report" \
  aws acm list-certificates --region us-east-1 --max-items 1
run "Budgets describe-budgets"       "billing alarms in CloudWatch (us-east-1 only)" aws budgets describe-budgets --account-id "$ID" --max-items 1
run "Cost Explorer get-cost-and-usage" "Budgets only" aws ce get-cost-and-usage \
  --time-period Start=$(date -v-2d +%F 2>/dev/null || date -d '-2 day' +%F),End=$(date +%F) \
  --granularity DAILY --metrics UnblendedCost

echo; echo "== Summary =="
echo "pass=$PASS warn=$WARN fail=$FAIL"
if [ "$FAIL" -gt 0 ]; then
  printf 'Blocked:\n'; printf '  - %s\n' "${BLOCKED[@]}"; exit 1
fi
