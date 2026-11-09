#!/usr/bin/env bash
# Build the ARM64 ffmpeg image with local Docker and push it to ECR (Graviton Fargate runs it natively).
# Uses `docker push` with retries: buildx's own --push dropped connections on this machine's Docker proxy,
# while plain push resumes already-uploaded layers on each retry.
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-sky}"
REPO=$(terraform -chdir=infra/persistent output -raw ecr_repository_url)
REGISTRY=$(echo "$REPO" | cut -d/ -f1)
IMG="${REPO}:latest"

docker buildx build --platform linux/arm64 -t "$IMG" --load services/transcode
for attempt in 1 2 3 4 5; do
  aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null
  if docker push "$IMG"; then echo "pushed $IMG"; exit 0; fi
  echo "push attempt $attempt failed, retrying (finished layers are kept)..."
done
echo "push failed" >&2; exit 1
