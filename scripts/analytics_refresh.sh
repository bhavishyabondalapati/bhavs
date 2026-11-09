#!/usr/bin/env bash
# Compact any finished hours of raw events into Parquet and rebuild the cached admin report.
# Runs the same Lambda the hourly schedule runs. May take a few invocations if many hours are pending.
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-sky}"
FN=$(terraform -chdir=infra/app output -raw analytics_compact_function)
for i in 1 2 3 4 5 6; do
  aws lambda invoke --region us-east-2 --function-name "$FN" --cli-read-timeout 900 \
    --payload '{}' --cli-binary-format raw-in-base64-out /tmp/bhavs_compact.json >/dev/null
  cat /tmp/bhavs_compact.json; echo
  # Lambda processes a bounded number of hours per run; stop when nothing was compacted.
  if grep -q '"compacted": \[\]' /tmp/bhavs_compact.json; then break; fi
done
