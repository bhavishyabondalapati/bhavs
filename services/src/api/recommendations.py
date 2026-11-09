"""GET /me/recommendations - rows written by the ML job.

Cold start: users with no personal rows get the GLOBAL rows (popularity, popularity by genre).
If even those are missing (before the first training run) fall back to 'Latest additions'.
"""
from boto3.dynamodb.conditions import Key
from shared.common import get_titles, response, table, user_id


def _rows(pk):
    items = table("RECS_TABLE").query(KeyConditionExpression=Key("user_id").eq(pk))["Items"]
    return sorted(items, key=lambda r: int(r.get("rank", 99)))


def handler(event, context):
    uid = user_id(event)
    rows, cold = _rows(uid), False
    if not rows:
        rows, cold = _rows("GLOBAL"), True
    out = []
    for r in rows:
        titles = get_titles(list(r.get("title_ids", [])))
        if titles:
            out.append({"key": r["row_key"], "label": r.get("label", r["row_key"]), "titles": titles})
    if not out:
        items = table("TITLES_TABLE").scan()["Items"]
        items = [i for i in items if i.get("status") != "FAILED"]
        items.sort(key=lambda i: -int(i.get("year", 0)))
        titles = get_titles([i["id"] for i in items][:20])
        if titles:
            out = [{"key": "latest", "label": "Latest additions", "titles": titles}]
        cold = True
    return response(200, {"rows": out, "cold_start": cold})
