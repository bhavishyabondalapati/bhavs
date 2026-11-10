"""Hourly job: raw JSONL -> partitioned Parquet (via Athena CTAS), then refresh the cached admin report.

Idempotent: an hour that already has Parquet is skipped; only hours that are fully over are compacted.
Event: {} (scheduled)  |  {"report_only": true}  |  {"force_hours": ["2026-11-01/18"]}

Cost note: Athena lists every hour folder a query could touch. The report queries therefore filter on the last
REPORT_DAYS days (a literal date passed as a query parameter, which Athena uses to prune), and a scheduled run
rebuilds the report at most every REPORT_MIN_HOURS. Without these, each rebuild made ~37,000 S3 LIST requests.
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
REPORT_DAYS = int(os.environ.get("REPORT_DAYS", "30"))
REPORT_MIN_HOURS = float(os.environ.get("REPORT_MIN_HOURS", "6"))
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


def run(athena, sql, workgroup, database=DB, timeout=600, params=None):
    kw = {"ExecutionParameters": params} if params else {}
    qid = athena.start_query_execution(QueryString=sql, WorkGroup=workgroup,
                                       QueryExecutionContext={"Database": database}, **kw)["QueryExecutionId"]
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


def report_since(now):
    return (now - dt.timedelta(days=REPORT_DAYS)).strftime("%Y-%m-%d")


def build_report(athena, workgroup, now=None):
    since = report_since(now or dt.datetime.now(dt.UTC))
    report = {"generated_at": int(time.time()), "since": since, "days": REPORT_DAYS}
    for name in ("views_per_title", "avg_watch_pct", "drop_off", "bitrate_distribution", "totals"):
        sql = (SQL_DIR / f"{name}.sql").read_text()
        qid = run(athena, sql, workgroup, params=[f"'{since}'"])
        data = [{k: (v if k in ("title_id", "rendition") else num(v)) for k, v in r.items()} for r in rows(athena, qid)]
        report[name] = data[0] if name == "totals" and data else data
    return report


def _report_modified(s3, bucket):
    """When the cached report was last written, or None if there is none yet."""
    try:
        return s3.head_object(Bucket=bucket, Key=REPORT_KEY)["LastModified"]
    except s3.exceptions.ClientError:
        return None


def newest_parquet(s3, bucket):
    """LastModified of the newest Parquet file (None if there is no Parquet yet)."""
    newest, token = None, None
    while True:
        page = s3.list_objects_v2(Bucket=bucket, Prefix="parquet/", **({"ContinuationToken": token} if token else {}))
        for o in page.get("Contents", []):
            newest = o["LastModified"] if newest is None or o["LastModified"] > newest else newest
        token = page.get("NextContinuationToken")
        if not token:
            return newest


def report_decision(report_modified, parquet_newest, now, min_hours=None):
    """'build', 'unchanged' (report already includes all Parquet) or 'deferred' (newer data, but rebuilt recently)."""
    if report_modified is None:
        return "build"
    if report_modified >= parquet_newest:
        return "unchanged"
    if (now - report_modified).total_seconds() / 3600 < (REPORT_MIN_HOURS if min_hours is None else min_hours):
        return "deferred"
    return "build"


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
    parquet_newest = newest_parquet(s3, bucket)
    if parquet_newest is None:
        return {"compacted": compacted, "report": "skipped (no parquet data yet)"}
    if not event.get("report_only"):
        decision = report_decision(_report_modified(s3, bucket), parquet_newest, dt.datetime.now(dt.UTC))
        if decision == "unchanged":
            return {"compacted": compacted, "report": "unchanged (already includes all data)"}  # no Athena at all
        if decision == "deferred":
            return {"compacted": compacted, "report": f"deferred (rebuilt at most every {REPORT_MIN_HOURS:g} h)"}
    report = build_report(athena, wg)
    s3.put_object(Bucket=bucket, Key=REPORT_KEY, Body=json.dumps(report), ContentType="application/json")
    return {"compacted": compacted, "report": "written"}
