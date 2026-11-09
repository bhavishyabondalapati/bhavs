#!/usr/bin/env bash
# Generate a fresh HMAC key and store it in BOTH places that need it:
#   * SSM Parameter Store (SecureString)  -> read by the Lambda that mints stream tokens
#   * CloudFront KeyValueStore            -> read by the CloudFront Function that verifies them
# The key is never printed, written to disk, or committed. Re-running rotates it (old tokens stop working).
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-sky}" AWS_PAGER=""
PARAM=/bhavs/stream-hmac-key
KVS_ARN=$(terraform -chdir=infra/persistent output -raw stream_kvs_arn)

KEY=$(openssl rand -hex 32)
aws ssm put-parameter --region us-east-2 --name "$PARAM" --type SecureString --overwrite \
  --value "$KEY" --tags Key=Project,Value=bhavs >/dev/null 2>&1 || \
aws ssm put-parameter --region us-east-2 --name "$PARAM" --type SecureString --overwrite --value "$KEY" >/dev/null
aws ssm add-tags-to-resource --region us-east-2 --resource-type Parameter --resource-id "$PARAM" --tags Key=Project,Value=bhavs >/dev/null 2>&1 || true

ETAG=$(aws cloudfront-keyvaluestore describe-key-value-store --kvs-arn "$KVS_ARN" --query ETag --output text)
aws cloudfront-keyvaluestore put-key --kvs-arn "$KVS_ARN" --key hmac_key --value "$KEY" --if-match "$ETAG" >/dev/null
echo "Stream key rotated in SSM ($PARAM) and CloudFront KeyValueStore."
