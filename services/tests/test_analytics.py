import datetime as dt
import gzip
import json
import time

import boto3
from analytics import compact, events_batch
from api import admin_analytics, events
from conftest import api_event


def body(r):
    return json.loads(r["body"])


def test_raw_key_is_partitioned_by_arrival_hour():
    ms = int(dt.datetime(2026, 11, 9, 14, 5, tzinfo=dt.UTC).timestamp() * 1000)
    k = events_batch.raw_key(ms, "abc")
    assert k == "raw/dt=2026-11-09/hour=14/abc.jsonl.gz"


def test_batch_lambda_writes_gzip_jsonl(db, monkeypatch):
    monkeypatch.setenv("ANALYTICS_BUCKET", "lake")
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket="lake", CreateBucketConfiguration={"LocationConstraint": "us-east-2"})
    now = int(time.time() * 1000)
    recs = [{"Body": json.dumps({"type": "play", "received_at": now, "title_id": "sintel"})},
            {"body": json.dumps({"type": "pause", "received_at": now, "title_id": "sintel"})}]
    recs[0]["body"] = recs[0].pop("Body")
    assert events_batch.handler({"Records": recs}, None)["written"] == 2
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket="lake")["Contents"]]
    assert len(keys) == 1 and keys[0].startswith("raw/dt=") and keys[0].endswith(".jsonl.gz")
    lines = gzip.decompress(s3.get_object(Bucket="lake", Key=keys[0])["Body"].read()).decode().strip().split("\n")
    assert [json.loads(x)["type"] for x in lines] == ["play", "pause"]


def test_hours_due_waits_for_hour_end_and_skips_done():
    now = dt.datetime(2026, 11, 9, 15, 3, tzinfo=dt.UTC)
    raw = {("2026-11-09", "13"), ("2026-11-09", "14"), ("2026-11-09", "15")}
    assert compact.hours_due(raw, set(), now) == [("2026-11-09", "13")]        # 14h ended 2 min ago: still in grace
    assert compact.hours_due(raw, {("2026-11-09", "13")}, now) == []
    later = now + dt.timedelta(minutes=10)
    assert compact.hours_due(raw, set(), later) == [("2026-11-09", "13"), ("2026-11-09", "14")]


def test_ctas_targets_one_partition_folder():
    sql = compact.ctas_sql("tmp_x", "lake", "2026-11-09", "14")
    assert "external_location='s3://lake/parquet/dt=2026-11-09/hour=14/'" in sql
    assert "dt='2026-11-09' AND hour='14'" in sql and "format='PARQUET'" in sql


def test_partition_listing(db):
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket="lake", CreateBucketConfiguration={"LocationConstraint": "us-east-2"})
    for k in ("raw/dt=2026-11-09/hour=14/a.jsonl.gz", "raw/dt=2026-11-09/hour=14/b.jsonl.gz", "raw/dt=2026-11-10/hour=01/c.jsonl.gz", "other/x"):
        s3.put_object(Bucket="lake", Key=k, Body=b"x")
    assert compact.list_partitions(s3, "lake", "raw/") == {("2026-11-09", "14"), ("2026-11-10", "01")}


def test_saved_queries_exist_and_read_events_table():
    for name in ("views_per_title", "avg_watch_pct", "drop_off", "bitrate_distribution", "totals"):
        sql = (compact.SQL_DIR / f"{name}.sql").read_text().lower()
        assert "from events" in sql and ";" not in sql


def test_admin_endpoint_requires_admin_group(db, monkeypatch):
    monkeypatch.setenv("ANALYTICS_BUCKET", "lake")
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket="lake", CreateBucketConfiguration={"LocationConstraint": "us-east-2"})
    assert admin_analytics.handler(api_event(groups=""), None)["statusCode"] == 403
    assert body(admin_analytics.handler(api_event(groups="[admin]"), None))["empty"] is True
    s3.put_object(Bucket="lake", Key="reports/analytics.json", Body=json.dumps({"generated_at": 5, "totals": {"events": 9}}))
    assert body(admin_analytics.handler(api_event(groups="[admin]"), None))["totals"]["events"] == 9


def test_events_are_forwarded_to_sqs_with_clean_fields(db, monkeypatch):
    q = boto3.client("sqs").create_queue(QueueName="ev")["QueueUrl"]
    monkeypatch.setenv("EVENTS_QUEUE_URL", q)
    ev = {"type": "heartbeat", "title_id": "sintel", "position": 61.4, "duration": 888, "session_id": "s1",
          "bitrate_kbps": 3000, "rendition": "720p; DROP", "ts": 1}
    assert events.handler(api_event(body=ev), None)["statusCode"] == 202
    rec = json.loads(boto3.client("sqs").receive_message(QueueUrl=q)["Messages"][0]["Body"])
    assert rec["user_id"] == "u1" and rec["rendition"] is None            # junk rendition rejected
    assert rec["ts"] == rec["received_at"]                                  # absurd client clock replaced
    assert rec["bitrate_kbps"] == 3000 and rec["synthetic"] is False


def test_queue_failure_does_not_break_viewer(db, monkeypatch):
    monkeypatch.setenv("EVENTS_QUEUE_URL", "https://sqs.us-east-2.amazonaws.com/000000000000/missing")
    ev = {"type": "play", "title_id": "sintel", "position": 1}
    assert events.handler(api_event(body=ev), None)["statusCode"] == 202
