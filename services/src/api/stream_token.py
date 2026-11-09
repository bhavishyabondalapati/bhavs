"""GET /titles/{id}/stream - hand a logged-in user a short-lived URL for a READY title."""
import os

from shared import tokens
from shared.common import error, response, table

TTL_SECONDS = int(os.environ.get("TOKEN_TTL_SECONDS", "14400"))  # 4h: long enough for any film plus pauses


def handler(event, context):
    title_id = (event.get("pathParameters") or {}).get("id", "")
    if not title_id or len(title_id) > 100:
        return error(400, "bad id")
    item = table("TITLES_TABLE").get_item(Key={"id": title_id}).get("Item")
    if not item:
        return error(404, "title not found")
    if item.get("status") != "READY":
        return error(409, "title is not ready for streaming")
    urls = tokens.stream_urls(os.environ["CDN_DOMAIN"], tokens.get_key(), title_id, TTL_SECONDS)
    return response(200, urls)
