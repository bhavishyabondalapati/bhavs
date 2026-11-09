"""POST /events - player events (play, pause, seek, heartbeat, complete).

1. keeps watch_history up to date (resume position + completion)
2. forwards a cleaned copy of every event to SQS -> S3 -> Athena (analytics)
"""
import json
import math
import os
import re
import time
from decimal import Decimal

import boto3
from shared.common import error, response, table, user_id

EVENT_TYPES = {"play", "pause", "seek", "heartbeat", "complete"}
COMPLETE_AT = 0.95  # watched >= 95% counts as finished
RENDITION_RE = re.compile(r"^\d{3,4}p$")
MAX_SKEW_MS = 24 * 3600 * 1000  # distrust client clocks more than a day off


def _num(v, lo=0, hi=10**6):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or f < lo or f > hi:
        return None
    return Decimal(str(round(f, 1)))


def _analytics_record(uid, body, etype, title_id, position, duration, now_ms):
    ts = body.get("ts")
    ts = int(ts) if isinstance(ts, (int, float)) and abs(ts - now_ms) <= MAX_SKEW_MS else now_ms
    bitrate = _num(body.get("bitrate_kbps"), 0, 100_000)
    rendition = body.get("rendition")
    session = str(body.get("session_id") or "")[:64]
    return {
        "ts": ts, "received_at": now_ms, "type": etype, "user_id": uid, "title_id": title_id,
        "session_id": session or None, "position": float(position),
        "duration": float(duration) if duration else None,
        "bitrate_kbps": int(bitrate) if bitrate is not None else None,
        "rendition": rendition if isinstance(rendition, str) and RENDITION_RE.match(rendition) else None,
        "synthetic": False,
    }


def _forward(record):
    url = os.environ.get("EVENTS_QUEUE_URL")
    if not url:
        return
    try:
        boto3.client("sqs").send_message(QueueUrl=url, MessageBody=json.dumps(record))
    except Exception as exc:  # noqa: BLE001 - analytics must never fail the viewer's request
        print(f"analytics enqueue failed: {exc!r}")


def handler(event, context):
    uid = user_id(event)
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return error(400, "invalid json")
    etype = body.get("type")
    title_id = body.get("title_id")
    position = _num(body.get("position"))
    duration = _num(body.get("duration"))
    if etype not in EVENT_TYPES or not isinstance(title_id, str) or not title_id or len(title_id) > 100:
        return error(400, "type and title_id required")
    if position is None:
        return error(400, "position must be a non-negative number of seconds")

    if not table("TITLES_TABLE").get_item(Key={"id": title_id}).get("Item"):
        return error(404, "unknown title")

    finished = etype == "complete" or (duration and duration > 0 and position / duration >= COMPLETE_AT)
    now = int(time.time())
    expr = "SET #p = :p, updated_at = :n, completed = :c, last_event = :e"
    vals = {":p": Decimal(0) if finished else position, ":n": now, ":c": bool(finished), ":e": etype}
    if duration:
        expr += ", #d = :d"
        vals[":d"] = duration
    table("HISTORY_TABLE").update_item(
        Key={"user_id": uid, "title_id": title_id},
        UpdateExpression=expr,
        ExpressionAttributeNames={"#p": "position", **({"#d": "duration"} if duration else {})},
        ExpressionAttributeValues=vals,
    )
    _forward(_analytics_record(uid, body, etype, title_id, position, duration, int(time.time() * 1000)))
    return response(202, {"ok": True})
