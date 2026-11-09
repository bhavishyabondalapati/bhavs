"""GET /titles/{id}"""
from shared.common import error, public_title, response, table


def handler(event, context):
    title_id = (event.get("pathParameters") or {}).get("id", "")
    if not title_id or len(title_id) > 100:
        return error(400, "bad id")
    item = table("TITLES_TABLE").get_item(Key={"id": title_id}).get("Item")
    if not item:
        return error(404, "title not found")
    return response(200, {"title": public_title(item)})
