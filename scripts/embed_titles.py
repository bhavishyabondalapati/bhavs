"""Build the search index: embed every READY title with Bedrock Titan V2 and save it to S3.

Cost: ~20 titles x ~60 tokens x $0.00002 per 1K tokens = a fraction of a cent. Re-run after adding titles.
Usage: python scripts/embed_titles.py [--dry-run]
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "src"))
import boto3
from shared import embed

KEY = "search/embeddings.json"


def build(titles):
    return [{"id": t["id"], "title": t["title"], "vector": embed.embed(embed.title_text(t))}
            for t in sorted(titles, key=lambda t: t["id"]) if t.get("status") == "READY"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    s = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "sky"), region_name="us-east-2")
    embed._client = s.client("bedrock-runtime")
    ddb, s3 = s.resource("dynamodb"), s.client("s3")
    bucket = os.environ.get("ANALYTICS_BUCKET") or _bucket()
    titles = ddb.Table("bhavs-titles").scan()["Items"]
    items = build(titles)
    print(f"embedded {len(items)} READY titles ({embed.DIMENSIONS} dims each)")
    if a.dry_run:
        return
    body = json.dumps({"model": embed.MODEL_ID, "dimensions": embed.DIMENSIONS, "items": items})
    s3.put_object(Bucket=bucket, Key=KEY, Body=body.encode(), ContentType="application/json")
    print(f"wrote s3://{bucket}/{KEY} ({len(body) / 1024:.0f} KB)")


def _bucket():
    import subprocess
    return subprocess.check_output(["terraform", "-chdir=infra/persistent", "output", "-raw", "analytics_bucket"], text=True).strip()


if __name__ == "__main__":
    main()
