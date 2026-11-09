"""Hourly job: raw JSONL -> partitioned Parquet (via Athena CTAS), then refresh the cached admin report.

Idempotent: an hour that already has Parquet is skipped; only hours that are fully over are compacted.
Event: {} (scheduled)  |  {"report_only": true}  |  {"force_hours": ["2026-11-01/18"]}
"""
import datetime as dt
import json
import os
import re
import time
from pathlib import Path

import boto3

DB = "bhavs_analytics"
SQL_DIR = Path(__file__).parent / "sql"
COLUMNS = "ts, received_at, type, user_id, title_id, session_id, position, duration, bitrate_kbps, rendition, synthetic"
MAX_HOURS_PER_RUN = 30  # bounds runtime; scripts/analytics_refresh.sh simply invokes again until nothing is left
REPORT_KEY = "reports/analytics.json"
PART_RE = re.compile(r"^(?:raw|parquet)/dt=(\d{4}-\d{2}-\d{2})/hour=(\d{2})/")


def list_partitions(s3, bucket, prefix):
    found, token = set(), None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix, **({"ContinuationToken": token} if token else {})}
        page = s3.list_objects_v2(**kw)
        for o in page.get("Contents", []):
            m = PART_RE.match(o["Key"])
            if m:
                found.add((m.group(1), m.group(2)))
        token = page.get("NextContinuationToken")
        if not token:
            return found


def hours_due(raw, done, now, grace_minutes=5):
    """Hours that are over (plus a short grace period for late events) and not yet compacted."""
    cutoff = now - dt.timedelta(minutes=grace_minutes)
    out = []
    for d, h in sorted(raw - done):
        end = dt.datetime.strptime(f"{d} {h}", "%Y-%m-%d %H").replace(tzinfo=dt.UTC) + dt.timedelta(hours=1)
        if end <= cutoff:
            out.append((d, h))
    return out


def ctas_sql(table, bucket, d, h):
    return (f"CREATE TABLE {DB}.{table} WITH (format='PARQUET', write_compression='SNAPPY', "
            f"external_location='s3://{bucket}/parquet/dt={d}/hour={h}/') AS "
            f"SELECT {COLUMNS} FROM {DB}.events_raw WHERE dt='{d}' AND hour='{h}'")


def run(athena, sql, workgroup, database=DB, timeout=600):
    qid = athena.start_query_execution(QueryString=sql, WorkGroup=workgroup,
                                       QueryExecutionContext={"Database": database})["QueryExecutionId"]
    t0 = time.time()
    while True:
        st = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if st["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        if time.time() - t0 > timeout:
            raise TimeoutError(sql[:80])
        time.sleep(1.5)
    if st["State"] != "SUCCEEDED":
        raise RuntimeError(f"athena {st['State']}: {st.get('StateChangeReason')} :: {sql[:120]}")
    return qid


def rows(athena, qid):
    out, token, header = [], None, None
    while True:
        page = athena.get_query_results(QueryExecutionId=qid, **({"NextToken": token} if token else {}))
        for r in page["ResultSet"]["Rows"]:
            vals = [c.get("VarCharValue") for c in r["Data"]]
            if header is None:
                header = vals
            else:
                out.append(dict(zip(header, vals, strict=False)))
        token = page.get("NextToken")
        if not token:
            return out


def num(v):
    try:
        f = float(v)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return v


def build_report(athena, workgroup):
    report = {"generated_at": int(time.time())}
    for name in ("views_per_title", "avg_watch_pct", "drop_off", "bitrate_distribution", "totals"):
        sql = (SQL_DIR / f"{name}.sql").read_text()
        data = [{k: (v if k in ("title_id", "rendition") else num(v)) for k, v in r.items()} for r in rows(athena, run(athena, sql, workgroup))]
        report[name] = data[0] if name == "totals" and data else data
    return report


def _exists(s3, bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except s3.exceptions.ClientError:
        return False


def handler(event, context):
    bucket, wg = os.environ["ANALYTICS_BUCKET"], os.environ["WORKGROUP"]
    s3, athena = boto3.client("s3"), boto3.client("athena")
    compacted = []
    if not event.get("report_only"):
        raw = list_partitions(s3, bucket, "raw/")
        done = list_partitions(s3, bucket, "parquet/")
        todo = hours_due(raw, done, dt.datetime.now(dt.UTC))
        for spec in event.get("force_hours", []):
            d, h = spec.split("/")
            todo.append((d, h))
        for d, h in todo[:MAX_HOURS_PER_RUN]:
            table = f"tmp_{d.replace('-', '')}_{h}_{int(time.time())}"
            run(athena, ctas_sql(table, bucket, d, h), wg)
            run(athena, f"DROP TABLE IF EXISTS {DB}.{table}", wg)
            compacted.append(f"{d}/{h}")
    if not list_partitions(s3, bucket, "parquet/"):
        return {"compacted": compacted, "report": "skipped (no parquet data yet)"}
    if not compacted and not event.get("report_only") and _exists(s3, bucket, REPORT_KEY):
        return {"compacted": [], "report": "unchanged (nothing new to compact)"}  # saves ~5 Athena queries per idle hour
    report = build_report(athena, wg)
    s3.put_object(Bucket=bucket, Key=REPORT_KEY, Body=json.dumps(report), ContentType="application/json")
    return {"compacted": compacted, "report": "written"}
