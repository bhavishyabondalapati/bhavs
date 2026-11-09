"""Step Functions failure path (after the Spot attempt AND the on-demand retry failed): mark FAILED, send to the DLQ."""
import json
import os
import time

import boto3
from shared.common import table


def handler(event, context):
    title_id = event.get("title_id", "unknown")
    err = event.get("error") or {}
    reason = (err.get("Cause") or err.get("Error") or "transcode failed")[:500]
    if title_id != "unknown":
        table("TITLES_TABLE").update_item(
            Key={"id": title_id},
            UpdateExpression="SET #s = :f, error_reason = :r",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":f": "FAILED", ":r": reason},
        )
    boto3.client("sqs").send_message(
        QueueUrl=os.environ["DLQ_URL"],
        MessageBody=json.dumps({"title_id": title_id, "src_key": event.get("src_key"), "reason": reason,
                                "failed_at": int(time.time())}),
    )
    return {"title_id": title_id, "status": "FAILED"}
