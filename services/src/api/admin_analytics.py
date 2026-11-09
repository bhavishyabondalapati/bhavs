"""GET /admin/analytics - cached analytics report. Members of the Cognito group "admin" only."""
import os

import boto3
from botocore.exceptions import ClientError
from shared.common import error, groups, response


def handler(event, context):
    if "admin" not in groups(event):
        return error(403, "admins only")
    try:
        obj = boto3.client("s3").get_object(Bucket=os.environ["ANALYTICS_BUCKET"], Key="reports/analytics.json")
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return response(200, {"generated_at": None, "empty": True})
        raise
    return {"statusCode": 200, "headers": {"content-type": "application/json", "cache-control": "no-store"},
            "body": obj["Body"].read().decode()}
