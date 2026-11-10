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
  if grep -q errorMessage /tmp/bhavs_compact.json; then echo 'Lambda reported an error (see above)' >&2; exit 1; fi
  # Lambda processes a bounded number of hours per run; stop when nothing was compacted.
  if grep -q '"compacted": \[\]' /tmp/bhavs_compact.json; then break; fi
done
# Scheduled runs rebuild the report at most every few hours (Athena cost); a manual refresh wants it now.
if grep -q '"report": "deferred' /tmp/bhavs_compact.json; then
  aws lambda invoke --region us-east-2 --function-name "$FN" --cli-read-timeout 900 \
    --payload '{"report_only": true}' --cli-binary-format raw-in-base64-out /tmp/bhavs_compact.json >/dev/null
  cat /tmp/bhavs_compact.json; echo
fi
