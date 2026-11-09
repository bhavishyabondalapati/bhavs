"""Create ~200 SYNTHETIC viewers with varied behaviour and load them into bhavs.

  python scripts/simulate_users/simulate.py                 # simulate + write to AWS
  python scripts/simulate_users/simulate.py --dry-run       # just print summary statistics
  python scripts/simulate_users/simulate.py --purge         # remove all synthetic data (then re-run to regenerate)

Everything written is marked synthetic: user ids `synthetic-NNNN`, `synthetic=true` on events and rows, and
raw event files named `synthetic-*.jsonl.gz`. Real users and real events are never touched by --purge.
"""
import argparse
import gzip
import json
import os
import sys
import time
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model


def dec(o):
    return json.loads(json.dumps(o), parse_float=Decimal)


def summarize(res):
    kinds = defaultdict(int)
    for e in res.events:
        kinds[e["type"]] += 1
    print(f"users={len(res.users)} events={len(res.events)} history_rows={len(res.history)}")
    print("event types:", dict(kinds))
    sessions = {e["session_id"] for e in res.events}
    done = sum(1 for e in res.events if e["type"] == "complete")
    print(f"sessions={len(sessions)} completed={done} ({100 * done / max(1, len(sessions)):.0f}%)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=200)
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--purge", action="store_true")
    a = ap.parse_args()

    session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "sky"), region_name="us-east-2")
    ddb, s3 = session.resource("dynamodb"), session.client("s3")
    acct = session.client("sts").get_caller_identity()["Account"]
    lake = f"bhavs-analytics-{acct}"

    if a.purge:
        purge(ddb, s3, lake)
        return

    titles = [t for t in ddb.Table("bhavs-titles").scan()["Items"] if t.get("status") == "READY"]
    titles = [{"id": t["id"], "genres": list(t.get("genres", [])), "duration_sec": int(t["duration_sec"])} for t in titles]
    if len(titles) < 3:
        sys.exit("Need at least 3 READY titles to simulate viewing.")
    print(f"simulating {a.users} SYNTHETIC users over {a.days} days across {len(titles)} READY titles (seed {a.seed})")
    res = model.simulate(titles, a.users, a.days, a.seed, end_ts=time.time())
    summarize(res)
    if a.dry_run:
        return

    purge(ddb, s3, lake, quiet=True)   # idempotent: regenerate from scratch
    by_part = defaultdict(list)
    for e in res.events:
        t = time.gmtime(e["ts"] / 1000)
        by_part[(time.strftime("%Y-%m-%d", t), time.strftime("%H", t))].append(e)
    for (d, h), evs in by_part.items():
        body = gzip.compress(("\n".join(json.dumps(x, separators=(",", ":")) for x in evs) + "\n").encode())
        s3.put_object(Bucket=lake, Key=f"raw/dt={d}/hour={h}/synthetic-{d}-{h}.jsonl.gz", Body=body)
    print(f"wrote {len(by_part)} raw event files to s3://{lake}/raw/")
    with ddb.Table("bhavs-users").batch_writer() as w:
        for u in res.users:
            w.put_item(Item={"user_id": u.user_id, "email": f"{u.user_id}@synthetic.invalid", "created_at": int(time.time()),
                             "synthetic": True, "cluster": u.cluster})
    with ddb.Table("bhavs-watch-history").batch_writer() as w:
        for r in res.history:
            w.put_item(Item=dec(r))
    print("wrote users + watch_history rows (synthetic=true). Next: make analytics-refresh")


def purge(ddb, s3, lake, quiet=False):
    n = 0
    for tname, keys in (("bhavs-users", ("user_id",)), ("bhavs-watch-history", ("user_id", "title_id")),
                        ("bhavs-recommendations", ("user_id", "row_key"))):
        t = ddb.Table(tname)
        kw = {"FilterExpression": "begins_with(user_id, :p)", "ExpressionAttributeValues": {":p": "synthetic-"}}
        while True:
            page = t.scan(**kw)
            with t.batch_writer() as w:
                for it in page["Items"]:
                    w.delete_item(Key={k: it[k] for k in keys})
                    n += 1
            if "LastEvaluatedKey" not in page:
                break
            kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    gone = 0
    for prefix in ("raw/", "parquet/", "reports/"):   # parquet + reports are derived: they get rebuilt from raw
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=lake, Prefix=prefix):
            for o in page.get("Contents", []):
                if prefix != "raw/" or "/synthetic-" in o["Key"]:
                    s3.delete_object(Bucket=lake, Key=o["Key"])
                    gone += 1
    if not quiet:
        print(f"purged {n} synthetic DynamoDB rows and {gone} S3 objects (raw synthetic files + derived parquet/reports)")


if __name__ == "__main__":
    main()
