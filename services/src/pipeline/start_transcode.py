"""EventBridge (S3 Object Created in the source bucket) -> mark title PROCESSING -> start the Step Functions run.

Expected key layout: uploads/<title_id>/<any file name>.  Anything else is ignored.
"""
import json
import os
import re
import time

import boto3
from shared.common import table

KEY_RE = re.compile(r"^uploads/(?P<id>[\w-]{1,100})/(?P<file>[^/]+\.(mp4|mov|mkv|m4v|webm|avi|ogv))$", re.IGNORECASE)


def handler(event, context):
    detail = event.get("detail", {})
    bucket, key = detail.get("bucket", {}).get("name"), detail.get("object", {}).get("key", "")
    m = KEY_RE.match(key)
    if not bucket or not m:
        print(f"ignored key {key!r}")
        return {"started": False, "reason": "key does not match uploads/<title_id>/<video>"}
    title_id = m["id"]
    if not table("TITLES_TABLE").get_item(Key={"id": title_id}).get("Item"):
        print(f"ignored upload for unknown title {title_id}")
        return {"started": False, "reason": "unknown title"}

    table("TITLES_TABLE").update_item(
        Key={"id": title_id},
        UpdateExpression="SET #s = :p REMOVE error_reason",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":p": "PROCESSING"},
    )
    run = boto3.client("stepfunctions").start_execution(
        stateMachineArn=os.environ["STATE_MACHINE_ARN"],
        name=f"{title_id}-{int(time.time())}"[:80],
        input=json.dumps({"title_id": title_id, "src_bucket": bucket, "src_key": key,
                          "out_prefix": f"titles/{title_id}/"}),
    )
    return {"started": True, "execution": run["executionArn"]}
