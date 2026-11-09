"""GET /titles - the catalogue (small, so a Scan is fine and costs nothing at this size)."""
from shared.common import public_title, response, table


def handler(event, context):
    t = table("TITLES_TABLE")
    items, kwargs = [], {}
    while True:
        page = t.scan(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    titles = [public_title(i) for i in items if i.get("status") != "FAILED"]
    titles.sort(key=lambda t: (-int(t.get("year", 0)), t.get("title", "")))
    return response(200, {"titles": titles})
