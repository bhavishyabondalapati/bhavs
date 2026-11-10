"""The hourly compaction Lambda end to end: S3 is moto, Athena is a small fake (moto cannot run SQL)."""
import datetime as dt
import json

import boto3
import pytest
from analytics import compact


class FakeAthena:
    """Records every SQL statement. Each query is RUNNING once, then SUCCEEDED (or FAILED if it contains 'BOOM')."""

    def __init__(self, result_pages=None):
        self.sql, self.params, self._polls, self.result_pages = [], [], {}, result_pages or {}

    def start_query_execution(self, QueryString, WorkGroup, QueryExecutionContext, ExecutionParameters=None):
        self.sql.append(QueryString)
        self.params.append(ExecutionParameters)
        qid = f"q{len(self.sql)}"
        self._polls[qid] = 0
        return {"QueryExecutionId": qid}

    def get_query_execution(self, QueryExecutionId):
        self._polls[QueryExecutionId] += 1
        sql = self.sql[int(QueryExecutionId[1:]) - 1]
        state = "RUNNING" if self._polls[QueryExecutionId] == 1 else ("FAILED" if "BOOM" in sql else "SUCCEEDED")
        return {"QueryExecution": {"Status": {"State": state, "StateChangeReason": "bad sql"}}}

    def get_query_results(self, QueryExecutionId, NextToken=None):
        pages = self.result_pages.get("default", [[["title_id", "views"], ["sintel", "12"]]])
        i = int(NextToken or 0)
        page = {"ResultSet": {"Rows": [{"Data": [{"VarCharValue": v} for v in row]} for row in pages[i]]}}
        if i + 1 < len(pages):
            page["NextToken"] = str(i + 1)
        return page


@pytest.fixture
def lake(db, monkeypatch):
    monkeypatch.setenv("ANALYTICS_BUCKET", "lake")
    monkeypatch.setenv("WORKGROUP", "bhavs")
    monkeypatch.setattr(compact.time, "sleep", lambda s: None)
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket="lake", CreateBucketConfiguration={"LocationConstraint": "us-east-2"})
    athena = FakeAthena()
    real_client = boto3.client
    monkeypatch.setattr(compact.boto3, "client", lambda name, **kw: athena if name == "athena" else real_client(name, **kw))
    return s3, athena


def test_run_polls_until_done_and_raises_on_failure(lake):
    _, athena = lake
    assert compact.run(athena, "SELECT 1", "bhavs") == "q1"
    with pytest.raises(RuntimeError, match="FAILED"):
        compact.run(athena, "SELECT BOOM", "bhavs")


def test_rows_follow_pagination_and_use_the_header():
    athena = FakeAthena({"default": [[["title_id", "views"], ["sintel", "12"]], [["bbb", "3"]]]})
    assert compact.rows(athena, "q1") == [{"title_id": "sintel", "views": "12"}, {"title_id": "bbb", "views": "3"}]


def test_numbers_are_coerced_but_ids_stay_text():
    assert compact.num("12") == 12 and compact.num("0.5") == 0.5 and compact.num(None) is None and compact.num("x") == "x"


def test_handler_compacts_due_hours_then_writes_the_report(lake):
    s3, athena = lake
    s3.put_object(Bucket="lake", Key="raw/dt=2026-01-01/hour=10/a.jsonl.gz", Body=b"x")  # long over: due
    out = compact.handler({}, None)
    assert out == {"compacted": ["2026-01-01/10"], "report": "skipped (no parquet data yet)"}  # moto: CTAS wrote nothing
    ctas, drop = athena.sql[0], athena.sql[1]
    assert ctas.startswith("CREATE TABLE") and "parquet/dt=2026-01-01/hour=10/" in ctas
    assert drop.startswith("DROP TABLE IF EXISTS")

    s3.put_object(Bucket="lake", Key="parquet/dt=2026-01-01/hour=10/part-0.parquet", Body=b"x")  # what CTAS writes
    out = compact.handler({}, None)
    assert out == {"compacted": [], "report": "written"}  # nothing new, but no report yet -> build it
    report = json.loads(s3.get_object(Bucket="lake", Key=compact.REPORT_KEY)["Body"].read())
    assert report["views_per_title"] == [{"title_id": "sintel", "views": 12}]
    assert set(report) >= {"generated_at", "avg_watch_pct", "drop_off", "bitrate_distribution", "totals"}


def test_idle_hour_skips_athena_entirely(lake):
    s3, athena = lake
    s3.put_object(Bucket="lake", Key="parquet/dt=2026-01-01/hour=10/part-0.parquet", Body=b"x")
    s3.put_object(Bucket="lake", Key=compact.REPORT_KEY, Body=b"{}")
    assert compact.handler({}, None) == {"compacted": [], "report": "unchanged (already includes all data)"}
    assert athena.sql == []  # saves ~5 Athena queries every idle hour


def test_report_only_and_force_hours(lake):
    s3, athena = lake
    s3.put_object(Bucket="lake", Key="parquet/dt=2026-01-01/hour=10/part-0.parquet", Body=b"x")
    assert compact.handler({"report_only": True}, None)["report"] == "written"
    assert not any(q.startswith("CREATE TABLE") for q in athena.sql)
    athena.sql.clear()
    out = compact.handler({"force_hours": ["2026-01-01/10"]}, None)
    assert out["compacted"] == ["2026-01-01/10"] and athena.sql[0].startswith("CREATE TABLE")


def test_report_queries_are_limited_to_the_report_window(lake):
    """Regression guard: without a dt filter each rebuild made Athena LIST ~7,500 S3 folders (~$0.20-0.40 a time)."""
    s3, athena = lake
    s3.put_object(Bucket="lake", Key="parquet/dt=2026-01-01/hour=10/part-0.parquet", Body=b"x")
    compact.build_report(athena, "bhavs", now=dt.datetime(2026, 11, 10, tzinfo=dt.UTC))
    assert len(athena.sql) == 5
    assert all(p == ["'2026-10-11'"] for p in athena.params)  # 30 days before 2026-11-10, as a SQL literal
    for name in ("views_per_title", "avg_watch_pct", "drop_off", "bitrate_distribution", "totals"):
        sql = (compact.SQL_DIR / f"{name}.sql").read_text()
        assert "dt >= ?" in sql and sql.count("?") == 1, name


def test_report_decision():
    t = dt.datetime(2026, 11, 10, 12, tzinfo=dt.UTC)
    hour = dt.timedelta(hours=1)
    assert compact.report_decision(None, t, t) == "build"                                 # no report yet
    assert compact.report_decision(t, t - hour, t) == "unchanged"                         # report has all data
    assert compact.report_decision(t - 2 * hour, t - hour, t, min_hours=6) == "deferred"  # new data, rebuilt recently
    assert compact.report_decision(t - 7 * hour, t - hour, t, min_hours=6) == "build"     # new data, report is old
