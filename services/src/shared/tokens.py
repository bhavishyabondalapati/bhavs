"""Stream tokens: HMAC-SHA256(secret, "<exp>:<title_id>"), carried in the URL path.

The CloudFront Function in infra/persistent/cdn/viewer_request.js verifies exactly this format
(tests/test_cdn_function.py runs both sides against each other).
"""
import hashlib
import hmac
import os
import time

import boto3

_cache = {}


def get_key():
    """Fetch the signing key from SSM once per Lambda container."""
    if "key" not in _cache:
        res = boto3.client("ssm").get_parameter(Name=os.environ["STREAM_KEY_PARAM"], WithDecryption=True)
        _cache["key"] = res["Parameter"]["Value"]
    return _cache["key"]


def make_token(key, title_id, exp):
    sig = hmac.new(key.encode(), f"{exp}:{title_id}".encode(), hashlib.sha256).hexdigest()
    return f"{int(exp):010d}-{sig}"


def stream_urls(cdn_domain, key, title_id, ttl_seconds, now=None):
    now = int(now if now is not None else time.time())
    exp = now + ttl_seconds
    base = f"https://{cdn_domain}/t/{make_token(key, title_id, exp)}/titles/{title_id}"
    return {
        "master": f"{base}/master.m3u8",
        "sprite_vtt": f"{base}/sprite.vtt",
        "expires_at": exp,
    }
