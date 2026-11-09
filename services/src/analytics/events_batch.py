"""SQS -> S3. One gzip JSON-lines object per batch, laid out raw/dt=YYYY-MM-DD/hour=HH/<id>.jsonl.gz
(the folder names are Athena partitions)."""
import gzip
import json
import os
import time
import uuid

import boto3


def raw_key(received_at_ms, batch_id=None):
    t = time.gmtime(received_at_ms / 1000)
    return f"raw/dt={time.strftime('%Y-%m-%d', t)}/hour={time.strftime('%H', t)}/{batch_id or uuid.uuid4().hex}.jsonl.gz"


def handler(event, context):
    records = [json.loads(r["body"]) for r in event.get("Records", [])]
    if not records:
        return {"written": 0}
    by_key = {}
    for rec in records:  # events can straddle an hour boundary, so group by the hour they arrived in
        by_key.setdefault(raw_key(rec.get("received_at", int(time.time() * 1000)))
                          .rsplit("/", 1)[0], []).append(rec)
    s3 = boto3.client("s3")
    for prefix, recs in by_key.items():
        body = gzip.compress(("\n".join(json.dumps(r, separators=(",", ":")) for r in recs) + "\n").encode())
        s3.put_object(Bucket=os.environ["ANALYTICS_BUCKET"], Key=f"{prefix}/{uuid.uuid4().hex}.jsonl.gz", Body=body)
    return {"written": len(records)}
