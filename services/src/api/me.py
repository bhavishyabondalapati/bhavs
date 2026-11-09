"""GET /me - who am I; also records the user on first sight."""
import time

from shared.common import claims, groups, response, table, user_id


def handler(event, context):
    uid = user_id(event)
    c = claims(event)
    now = int(time.time())
    table("USERS_TABLE").update_item(
        Key={"user_id": uid},
        UpdateExpression="SET email = :e, last_seen = :n, created_at = if_not_exists(created_at, :n)",
        ExpressionAttributeValues={":e": c.get("email", ""), ":n": now},
    )
    g = groups(event)
    return response(200, {"user_id": uid, "email": c.get("email", ""), "groups": g, "is_admin": "admin" in g})
