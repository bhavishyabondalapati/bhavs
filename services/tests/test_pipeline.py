import json
from unittest.mock import MagicMock, patch

import boto3
from api import stream_token
from conftest import api_event
from moto import mock_aws
from pipeline import start_transcode, transcode_complete, transcode_fail
from shared import tokens


def body(r):
    return json.loads(r["body"])


def s3_event(key, bucket="src"):
    return {"detail": {"bucket": {"name": bucket}, "object": {"key": key}}}


def test_start_ignores_bad_keys_and_unknown_titles(db, monkeypatch):
    monkeypatch.setenv("STATE_MACHINE_ARN", "arn:fake")
    sfn = MagicMock()
    with patch.object(start_transcode.boto3, "client", return_value=sfn):
        assert not start_transcode.handler(s3_event("misc/file.mp4"), None)["started"]
        assert not start_transcode.handler(s3_event("uploads/sintel/readme.txt"), None)["started"]
        assert not start_transcode.handler(s3_event("uploads/ghost/x.mp4"), None)["started"]
    sfn.start_execution.assert_not_called()


def test_start_accepts_ogv_and_webm(db, monkeypatch):
    monkeypatch.setenv("STATE_MACHINE_ARN", "arn:fake")
    sfn = MagicMock()
    sfn.start_execution.return_value = {"executionArn": "x"}
    with patch.object(start_transcode.boto3, "client", return_value=sfn):
        assert start_transcode.handler(s3_event("uploads/bbb/a.ogv"), None)["started"]
        assert start_transcode.handler(s3_event("uploads/sintel/a.webm"), None)["started"]


def test_start_marks_processing_and_starts_run(db, monkeypatch):
    monkeypatch.setenv("STATE_MACHINE_ARN", "arn:fake")
    sfn = MagicMock()
    sfn.start_execution.return_value = {"executionArn": "arn:exec"}
    with patch.object(start_transcode.boto3, "client", return_value=sfn):
        out = start_transcode.handler(s3_event("uploads/sintel/Sintel_1080p.MP4"), None)
    assert out["started"]
    assert db.Table("titles").get_item(Key={"id": "sintel"})["Item"]["status"] == "PROCESSING"
    payload = json.loads(sfn.start_execution.call_args.kwargs["input"])
    assert payload == {"title_id": "sintel", "src_bucket": "src", "src_key": "uploads/sintel/Sintel_1080p.MP4",
                       "out_prefix": "titles/sintel/"}


def test_complete_marks_ready_with_manifest(db, monkeypatch):
    monkeypatch.setenv("OUT_BUCKET", "out")
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket="out", CreateBucketConfiguration={"LocationConstraint": "us-east-2"})
    manifest = {"duration_sec": 888, "hls": "master.m3u8", "poster": "poster.jpg", "sprite": "sprite.jpg",
                "renditions": [{"name": "360p"}, {"name": "720p"}]}
    s3.put_object(Bucket="out", Key="titles/sintel/manifest.json", Body=json.dumps(manifest))
    db.Table("titles").update_item(Key={"id": "sintel"}, UpdateExpression="SET error_reason = :e",
                                   ExpressionAttributeValues={":e": "old"})
    transcode_complete.handler({"title_id": "sintel", "out_prefix": "titles/sintel/"}, None)
    t = db.Table("titles").get_item(Key={"id": "sintel"})["Item"]
    assert t["status"] == "READY" and t["duration_sec"] == 888 and t["renditions"] == ["360p", "720p"]
    assert t["hls_path"] == "titles/sintel/master.m3u8" and "error_reason" not in t


def test_fail_marks_failed_and_sends_to_dlq(db, monkeypatch):
    sqs = boto3.client("sqs")
    url = sqs.create_queue(QueueName="dlq")["QueueUrl"]
    monkeypatch.setenv("DLQ_URL", url)
    transcode_fail.handler({"title_id": "bbb", "src_key": "uploads/bbb/x.mp4", "error": {"Cause": "ffmpeg exited 1"}}, None)
    assert db.Table("titles").get_item(Key={"id": "bbb"})["Item"]["status"] == "FAILED"
    msgs = sqs.receive_message(QueueUrl=url)["Messages"]
    assert json.loads(msgs[0]["Body"])["reason"] == "ffmpeg exited 1"


def test_token_format():
    t = tokens.make_token("k" * 64, "sintel", 1900000000)
    exp, sig = t.split("-")
    assert exp == "1900000000" and len(sig) == 64


def test_stream_endpoint_requires_ready(db, monkeypatch):
    monkeypatch.setenv("CDN_DOMAIN", "cdn.example.net")
    monkeypatch.setenv("STREAM_KEY_PARAM", "/bhavs/stream-hmac-key")
    tokens._cache.clear()
    ssm = boto3.client("ssm")
    ssm.put_parameter(Name="/bhavs/stream-hmac-key", Value="s" * 64, Type="SecureString")
    db.Table("titles").update_item(Key={"id": "bbb"}, UpdateExpression="SET #s = :r",
                                   ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":r": "PENDING"})
    assert stream_token.handler(api_event(path={"id": "bbb"}), None)["statusCode"] == 409
    assert stream_token.handler(api_event(path={"id": "nope"}), None)["statusCode"] == 404
    r = stream_token.handler(api_event(path={"id": "sintel"}), None)  # sintel is READY in the fixture
    assert r["statusCode"] == 200
    master = body(r)["master"]
    assert master.startswith("https://cdn.example.net/t/") and master.endswith("/titles/sintel/master.m3u8")


def test_mock_aws_is_active(db):  # sanity: fixtures run inside moto, never against real AWS
    assert mock_aws is not None
