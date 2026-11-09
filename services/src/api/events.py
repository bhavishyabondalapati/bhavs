"""POST /events - player events (play, pause, seek, heartbeat, complete).

Phase 1: keeps watch_history up to date (resume position + completion).
Phase 3 adds forwarding every event to SQS for analytics.
"""
import json
import math
import time
from decimal import Decimal

from shared.common import error, response, table, user_id

EVENT_TYPES = {"play", "pause", "seek", "heartbeat", "complete"}
COMPLETE_AT = 0.95  # watched >= 95% counts as finished


def _num(v, lo=0, hi=10**6):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or f < lo or f > hi:
        return None
    return Decimal(str(round(f, 1)))


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
    return response(202, {"ok": True})
