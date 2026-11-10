"""GET /search?q=... - hybrid (meaning + keywords) search over the catalogue.

How it works (simple version): every title was turned into a vector once (scripts/embed_titles.py) and saved to S3. At
query time we run two searches and merge them:
  1. meaning: embed the query with the same model and rank titles by cosine similarity, so "a lonely dragon" finds
     Sintel even though those words are not in its description;
  2. keywords: BM25 over each title's name, genres and description (shared/textsearch.py), so exact words like "llama"
     or "Koro" always count.
The two ranked lists are merged with reciprocal rank fusion (RRF): each list gives a title 1/(k + rank) points and the
points are added up, so a title that is high in BOTH lists wins, without having to compare cosine scores to BM25
scores (they are on different scales). With ~20 titles all of this runs in plain Python in microseconds, so there is
no vector database to pay for.
"""
import json
import os
import time

import boto3
from botocore.exceptions import ClientError
from shared import embed, textsearch
from shared.common import error, get_titles, response

MIN_SCORE = float(os.environ.get("SEARCH_MIN_SCORE", "0.24"))  # vector-only mode (kept for the eval baseline)
REL_CUTOFF = 0.75  # vector-only mode: keep only results scoring at least 75% of the best one
# hybrid: a cosine below this is treated as "no meaning signal". 0.30 was picked on the DEV queries of
# ml/search_eval.yaml (0.30-0.40 tied best; the lowest was kept so meaning can still help); never tuned on the test set.
VEC_FLOOR = float(os.environ.get("SEARCH_VEC_FLOOR", "0.30"))
RRF_K = 10  # RRF damping; small because lists are short (60 is the usual value for lists of hundreds)
MIN_NAME_CHARS = 3  # a query this long (or longer) contained in a title name counts as a name match
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


def rank_vector(q, items, qvec):
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


def rank_hybrid(q, items, qvec, vec_floor=None):
    """Hybrid ranking: name matches first, then the RRF fusion of the cosine list and the BM25 list.

    "No results" happens only when BOTH signals are weak: every cosine is under the floor AND no word matches.
    """
    floor = VEC_FLOOR if vec_floor is None else vec_floor
    ql = q.lower()
    cos = {it["id"]: embed.dot(qvec, it["vector"]) for it in items}
    by_cos = [i for i in sorted(cos, key=lambda i: -cos[i]) if cos[i] >= floor]
    kw = textsearch.bm25_scores(q, items)
    by_kw = sorted(kw, key=lambda i: -kw[i])
    fused = {}
    for ranking in (by_cos, by_kw):
        for r, i in enumerate(ranking, 1):
            fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r)
    named = [it["id"] for it in items if len(ql) >= MIN_NAME_CHARS and ql in it.get("title", "").lower()]
    out = [(1.0, i) for i in named]
    out += [(s, i) for i, s in sorted(fused.items(), key=lambda x: -x[1]) if i not in named]
    return out[:MAX_RESULTS]


rank = rank_hybrid  # what the handler uses


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
