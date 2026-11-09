"""Ingest films into bhavs.

  python scripts/ingest/ingest.py                 # DRY RUN: match files, probe them, print the cost estimate
  python scripts/ingest/ingest.py --upload        # seed metadata + upload -> starts the transcode pipeline (costs money)

Files are looked up in ./media-src (override with --media-dir): either put them there yourself or use
scripts/fetch_films.sh. Names may be anything that contains the film id or title (e.g. Sintel.2010.1080p.mkv).
"""
import argparse
import os
import sys
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import media
import seed_titles

ROOT = Path(__file__).resolve().parents[2]


def report(films, matches, unmatched, infos):
    print(f"\n{'film':<28}{'file':<44}{'res':>11}{'min':>7}{'size':>9}")
    for f in films:
        p = matches.get(f["id"])
        if not p:
            print(f"{f['id']:<28}{'(no file found)':<44}")
            continue
        i = infos[f["id"]]
        print(f"{f['id']:<28}{p.name[:42]:<44}{i['width']}x{i['height']:<5}{i['duration'] / 60:>7.1f}{i['size'] / 1e6:>7.0f}MB")
    for p in unmatched:
        print(f"{'?':<28}{p.name[:42]:<44}(does not match any film in films.yaml; ignored)")


def print_estimate(e):
    print(f"""
Estimated cost to transcode {e['films']} films ({e['content_minutes']:.0f} min of video)
  Fargate ARM64 4 vCPU / 8 GB at ${e['task_rate_hr']:.4f}/hour (on-demand price; Spot is usually cheaper, unverified)
  compute time : {e['run_hours_low']:.1f} - {e['run_hours_high']:.1f} task-hours
  compute cost : ${e['compute_low']:.2f} - ${e['compute_high']:.2f}
  other        : ~${e['other']:.2f} (Step Functions, Lambda, EventBridge)
  ----------------------------------------------
  TOTAL        : ${e['total_low']:.2f} - ${e['total_high']:.2f} one-off
  storage      : ~{e['output_gb']:.1f} GB renditions + {e['source_gb']:.1f} GB sources = ~${e['storage_per_month']:.2f}/month
""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--media-dir", default=str(ROOT / "media-src"))
    ap.add_argument("--films", default=str(ROOT / "films.yaml"))
    ap.add_argument("--only", nargs="*", help="film ids to ingest (default: all that have files)")
    ap.add_argument("--upload", action="store_true", help="actually upload (this STARTS the paid transcode pipeline)")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    a = ap.parse_args()

    films = seed_titles.load_films(a.films)
    if a.only:
        films = [f for f in films if f["id"] in a.only]
    if not Path(a.media_dir).is_dir():
        sys.exit(f"{a.media_dir} does not exist. Run scripts/fetch_films.sh or create it and drop videos in.")
    matches, unmatched = media.match_files(films, a.media_dir)
    infos = {fid: media.probe(p) for fid, p in matches.items()}
    report(films, matches, unmatched, infos)
    if not matches:
        sys.exit("\nNo matching files found.")
    print_estimate(media.estimate(list(infos.values())))
    if not a.upload:
        print("Dry run only. Nothing was uploaded. Re-run with --upload to start the pipeline.")
        return

    if not a.yes and input("Upload and start transcoding? [y/N] ").strip().lower() != "y":
        sys.exit("Aborted.")
    session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "sky"), region_name="us-east-2")
    acct = session.client("sts").get_caller_identity()["Account"]
    bucket = f"bhavs-source-{acct}"
    table = session.resource("dynamodb").Table(os.environ.get("TITLES_TABLE", "bhavs-titles"))
    seed_titles.seed(table, [f for f in films if f["id"] in matches])   # metadata first, so the title exists
    s3 = session.client("s3")
    for fid, path in matches.items():
        key = f"uploads/{fid}/{path.name}"
        print(f"uploading {path.name} -> s3://{bucket}/{key}")
        s3.upload_file(str(path), bucket, key)
    print("Done. Watch progress in the Step Functions console or: aws stepfunctions list-executions --state-machine-arn <arn>")


if __name__ == "__main__":
    main()
