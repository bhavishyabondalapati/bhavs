"""GET /search?q=... - semantic search over the catalogue.

How it works (simple version): every title was turned into a vector once (scripts/embed_titles.py) and saved to S3. At
query time we turn the search text into a vector with the same model and rank titles by cosine similarity, so
"a lonely dragon" finds Sintel even though those words are not in its description. With ~20 titles, comparing against
all of them in plain Python takes microseconds, so there is no vector database to pay for.
"""
import json
import os
import time

import boto3
from botocore.exceptions import ClientError
from shared import embed
from shared.common import error, get_titles, response

MIN_SCORE = float(os.environ.get("SEARCH_MIN_SCORE", "0.24"))  # floor: below this nothing is "really related"
REL_CUTOFF = 0.75  # ...and keep only results scoring at least 75% of the best one (tuned by eye on 17 titles)
MAX_RESULTS = 8
MAX_QUERY_CHARS = 200
INDEX_TTL = 300  # seconds a warm Lambda keeps the index before re-reading S3

_index = {"at": 0.0, "items": []}
_query_cache = {}  # tiny in-memory cache: repeated searches cost nothing


def _s3():
    return boto3.client("s3")


def load_index():
    if time.time() - _index["at"] > INDEX_TTL:
        obj = _s3().get_object(Bucket=os.environ["ANALYTICS_BUCKET"], Key=os.environ["EMBEDDINGS_KEY"])
        data = json.loads(obj["Body"].read())
        _index["items"], _index["at"] = data["items"], time.time()
    return _index["items"]


def _query_vector(q):
    key = q.lower()
    if key not in _query_cache:
        if len(_query_cache) > 256:
            _query_cache.clear()
        _query_cache[key] = embed.embed(q)
    return _query_cache[key]


def rank(q, items, qvec):
    """Titles whose NAME contains the query come first (exact beats fuzzy); the rest are ordered by cosine similarity.

    The similarity cut-off is relative to the best *semantic* score, so a name match never hides related titles.
    """
    ql = q.lower()
    sims = sorted(((embed.dot(qvec, it["vector"]), it) for it in items), key=lambda x: -x[0])
    best = sims[0][0] if sims else 0.0
    named, related = [], []
    for score, it in sims:
        if ql in it.get("title", "").lower():
            named.append((1.0, it["id"]))
        elif score >= MIN_SCORE and score >= REL_CUTOFF * best:
            related.append((score, it["id"]))
    return (named + related)[:MAX_RESULTS]


def handler(event, context):
    q = ((event.get("queryStringParameters") or {}).get("q") or "").strip()
    if len(q) < 2:
        return error(400, "query too short")
    if len(q) > MAX_QUERY_CHARS:
        return error(400, "query too long")
    try:
        items = load_index()
    except ClientError:  # e.g. the index file does not exist yet
        return error(503, "search index not built yet")
    scored = rank(q, items, _query_vector(q))
    titles = {t["id"]: t for t in get_titles([i for _, i in scored])}
    results = [{**titles[i], "score": round(s, 3)} for s, i in scored if i in titles and titles[i].get("status") == "READY"]
    return response(200, {"query": q, "results": results})
