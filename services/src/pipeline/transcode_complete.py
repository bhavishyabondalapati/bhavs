"""Step Functions success path: read the manifest the transcoder wrote and mark the title READY."""
import json
import os

import boto3
from shared.common import table


def apply_manifest(titles, title_id, manifest):
    """Write the transcode result onto the title. Also used by the local-transcode fallback script."""
    prefix = f"titles/{title_id}/"
    titles.update_item(
        Key={"id": title_id},
        UpdateExpression=("SET #s = :ready, duration_sec = :d, renditions = :r, hls_path = :h, "
                          "poster_path = :p, sprite_path = :sp REMOVE error_reason"),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":ready": "READY", ":d": int(manifest["duration_sec"]),
            ":r": [r["name"] for r in manifest["renditions"]],
            ":h": prefix + manifest["hls"], ":p": prefix + manifest["poster"], ":sp": prefix + manifest["sprite"],
        },
    )


def handler(event, context):
    title_id, prefix = event["title_id"], event["out_prefix"]
    obj = boto3.client("s3").get_object(Bucket=os.environ["OUT_BUCKET"], Key=prefix + "manifest.json")
    manifest = json.loads(obj["Body"].read())
    apply_manifest(table("TITLES_TABLE"), title_id, manifest)
    return {"title_id": title_id, "status": "READY"}
