"""Build the rows the website shows: "Top picks for you", "Because you watched X", and popularity rows.

Cold start: users the model has never seen get only the GLOBAL rows: overall popularity and popularity BY GENRE.
"""
import time
from collections import defaultdict

import numpy as np

WATCHED_PCT = 0.5       # at least this far in (or finished) = "already watched", not recommended again
ANCHOR_PCT = 0.6        # a title counts as a "because you watched" anchor when you got this far or finished it


def popularity(inter, split_train):
    return np.asarray(split_train.astype(bool).sum(axis=0)).ravel()


def global_rows(inter, pop, meta, now):
    ids = inter.item_ids
    order = list(np.argsort(-pop, kind="stable"))
    rows = [{"user_id": "GLOBAL", "row_key": "popular", "label": "Popular on bhavs", "rank": 1,
             "title_ids": [ids[k] for k in order[:12]]}]
    by_genre = defaultdict(list)
    for k in order:
        for g in meta["genres"].get(ids[k], []):
            by_genre[g].append(ids[k])
    for n, (g, tids) in enumerate(sorted(by_genre.items(), key=lambda kv: (-len(kv[1]), kv[0]))):
        if len(tids) >= 2:
            rows.append({"user_id": "GLOBAL", "row_key": f"genre#{g}", "label": f"Popular in {g.title()}",
                         "rank": 10 + n, "title_ids": tids[:12]})
    for r in rows:
        r.update(generated_at=int(now), model="popularity", source="ml-job", synthetic=False)
    return rows


def user_rows(model, inter, train, meta, model_name, now=None, top_k=12, n_because=2, synthetic_prefix="synthetic-"):
    """Personal rows for every user that appears in the training data."""
    now = now or time.time()
    ids, names = inter.item_ids, inter.item_names
    pop = popularity(inter, train)
    pop_order = [ids[k] for k in np.argsort(-pop, kind="stable")]
    vecs = model.item_vectors()
    sims = vecs @ vecs.T
    scores = model.score(np.arange(inter.n_users))
    pct_by = defaultdict(dict)
    for u, i, p in zip(inter.users, inter.items, meta["pct"], strict=True):
        pct_by[u][i] = max(p, pct_by[u].get(i, 0.0))
    last_t = defaultdict(dict)
    for u, i, t in zip(inter.users, inter.items, inter.times, strict=True):
        last_t[u][i] = max(t, last_t[u].get(i, 0.0))

    out = []
    for u in range(inter.n_users):
        uid = inter.user_ids[u]
        seen = {i for i, p in pct_by[u].items() if p >= WATCHED_PCT}
        base = {"user_id": uid, "generated_at": int(now), "model": model_name, "source": "ml-job",
                "synthetic": uid.startswith(synthetic_prefix)}
        cand = [(scores[u][k], k) for k in range(inter.n_items) if k not in seen]
        cand.sort(key=lambda x: -x[0])
        rows = []
        if cand:
            rows.append({**base, "row_key": "top_picks", "label": "Top picks for you", "rank": 1,
                         "title_ids": [ids[k] for _, k in cand[:top_k]]})
        anchors = sorted((i for i, p in pct_by[u].items() if p >= ANCHOR_PCT), key=lambda i: -last_t[u][i])[:n_because]
        for n, a in enumerate(anchors):
            near = [k for k in np.argsort(-sims[a]) if k != a and k not in seen][:10]
            if near:
                rows.append({**base, "row_key": f"because#{ids[a]}", "label": f"Because you watched {names[a]}",
                             "rank": 2 + n, "title_ids": [ids[k] for k in near]})
        fresh = [t for t in pop_order if inter.item_ids.index(t) not in seen][:12]
        rows.append({**base, "row_key": "popular", "label": "Popular on bhavs", "rank": 5, "title_ids": fresh})
        out.append((uid, rows))
    return out
