#!/usr/bin/env bash
# Build the ARM64 training image locally and push it to ECR (same retry approach as build_transcode.sh).
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-sky}"
REPO=$(terraform -chdir=infra/persistent output -raw train_ecr_repository_url)
REGISTRY=$(echo "$REPO" | cut -d/ -f1)
IMG="${REPO}:latest"

python ml/make_results.py >/dev/null   # refreshes ml/best_model.txt, which the image bundles
docker buildx build --platform linux/arm64 -t "$IMG" --load ml
for attempt in 1 2 3 4 5 6; do
  aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null
  if docker push "$IMG"; then echo "pushed $IMG"; exit 0; fi
  echo "push attempt $attempt failed, retrying (finished layers are kept)..."
done
echo "push failed" >&2
exit 1
