"""GET /me/continue-watching - unfinished titles, most recent first, with resume position."""
from boto3.dynamodb.conditions import Key
from shared.common import get_titles, response, table, user_id

MIN_SECONDS = 5  # ignore accidental clicks


def handler(event, context):
    uid = user_id(event)
    rows = table("HISTORY_TABLE").query(KeyConditionExpression=Key("user_id").eq(uid))["Items"]
    open_rows = [r for r in rows if not r.get("completed") and float(r.get("position", 0)) >= MIN_SECONDS]
    open_rows.sort(key=lambda r: int(r.get("updated_at", 0)), reverse=True)
    open_rows = open_rows[:20]
    titles = {t["id"]: t for t in get_titles([r["title_id"] for r in open_rows])}
    out = [
        {"title": titles[r["title_id"]], "position": r["position"], "duration": r.get("duration"),
         "updated_at": r.get("updated_at")}
        for r in open_rows if r["title_id"] in titles
    ]
    return response(200, {"items": out})
