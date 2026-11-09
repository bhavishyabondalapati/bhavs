"""Helpers shared by every API Lambda: DynamoDB access, JSON responses, auth claims."""
import json
import os
from decimal import Decimal

import boto3

_resource = None


def ddb():
    """Lazily created DynamoDB resource (lazy so tests can start a mock first)."""
    global _resource
    if _resource is None:
        _resource = boto3.resource("dynamodb")
    return _resource


def table(env_name):
    return ddb().Table(os.environ[env_name])


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")


def response(status, body, headers=None):
    h = {"content-type": "application/json", "cache-control": "no-store"}
    h.update(headers or {})
    return {"statusCode": status, "headers": h, "body": json.dumps(body, default=_default)}


def error(status, message):
    return response(status, {"error": message})


def claims(event):
    return (event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}) or {}).get("claims", {}) or {}


def user_id(event):
    return claims(event).get("sub")


def groups(event):
    """API Gateway delivers cognito:groups as a string like '[admin]' or 'admin'."""
    raw = claims(event).get("cognito:groups", "")
    if isinstance(raw, list):
        return raw
    return [g for g in str(raw).strip("[]").replace(",", " ").split() if g]


def get_titles(ids):
    """Batch fetch titles by id, returned in the order requested (missing ids skipped)."""
    ids = list(dict.fromkeys(ids))[:100]
    if not ids:
        return []
    name = os.environ["TITLES_TABLE"]
    res = ddb().batch_get_item(RequestItems={name: {"Keys": [{"id": i} for i in ids]}})
    by_id = {t["id"]: public_title(t) for t in res["Responses"].get(name, [])}
    return [by_id[i] for i in ids if i in by_id]


# Fields the browser may see (never internal storage keys).
PUBLIC_FIELDS = (
    "id", "title", "year", "genres", "description", "duration_sec", "status",
    "poster_path", "sprite_path", "license_name", "license_url", "credit", "renditions", "hls_path",
)


def public_title(item):
    return {k: item[k] for k in PUBLIC_FIELDS if k in item}
