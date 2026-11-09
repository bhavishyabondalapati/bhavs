"""FREE fallback: transcode on this Mac with the SAME code the Fargate task runs, then publish the result.

  python scripts/transcode_local.py                 # every film that has a file in media-src/
  python scripts/transcode_local.py --only sintel

Uploads the HLS output to the output bucket and marks the title READY, exactly as the cloud pipeline would.
Costs only a few cents of S3 requests; no Fargate. Use it if Spot/Fargate misbehaves or to save the compute cost.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
for sub in ("scripts/ingest", "scripts", "services/transcode", "services/src"):
    sys.path.insert(0, str(ROOT / sub))
import media
import seed_titles
import transcode
from pipeline.transcode_complete import apply_manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--media-dir", default=str(ROOT / "media-src"))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--keep", action="store_true", help="keep the local output folder (build/transcode/<id>)")
    a = ap.parse_args()

    films = seed_titles.load_films(ROOT / "films.yaml")
    if a.only:
        films = [f for f in films if f["id"] in a.only]
    matches, _ = media.match_files(films, a.media_dir)
    if not matches:
        sys.exit("No matching files in media-src/.")

    session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "sky"), region_name="us-east-2")
    bucket = f"bhavs-output-{session.client('sts').get_caller_identity()['Account']}"
    s3 = session.client("s3")
    table = session.resource("dynamodb").Table(os.environ.get("TITLES_TABLE", "bhavs-titles"))
    seed_titles.seed(table, [f for f in films if f["id"] in matches])

    for fid, src in matches.items():
        out = ROOT / "build" / "transcode" / fid
        shutil.rmtree(out, ignore_errors=True)
        print(f"== {fid}: transcoding {src.name}", flush=True)
        manifest = transcode.transcode(src, out, fid)
        print(f"   uploading to s3://{bucket}/titles/{fid}/", flush=True)
        transcode.upload_dir(s3, bucket, f"titles/{fid}/", out)
        apply_manifest(table, fid, manifest)
        print(f"   READY ({manifest['duration_sec']}s, {[r['name'] for r in manifest['renditions']]})")
        if not a.keep:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    main()
