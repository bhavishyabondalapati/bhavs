"""Turn bhavs watch_history + titles into Interactions.

A (user, title) pair counts as a positive when the viewer finished it or got at least 25% in. The engagement weight
(used as ALS confidence and two-tower loss weight) is   max_pct + 0.5*completed + 0.1*extra_plays(<=3).
"""
import math

import numpy as np

from .data import Interactions, _genre_matrix

MIN_PCT = 0.25


def engagement(row):
    """row: a watch_history item (works for real rows that only have position/duration/completed, and synthetic ones)."""
    dur = float(row.get("duration") or 0)
    pct = float(row["max_pct"]) if row.get("max_pct") is not None else (
        1.0 if row.get("completed") else (min(1.0, float(row.get("position", 0)) / dur) if dur else 0.0))
    done = bool(row.get("completed"))
    plays = int(row.get("plays") or 1)
    return pct, done, (pct + 0.5 * done + 0.1 * min(plays - 1, 3))


def load(history_rows, titles):
    """titles: list of dicts with id,title,genres,year,duration_sec (READY ones). Returns (Interactions, meta)."""
    ready = {t["id"]: t for t in titles}
    users, items, times, weights, pcts = [], [], [], [], []
    for r in history_rows:
        if r["title_id"] not in ready:
            continue
        pct, done, w = engagement(r)
        if not done and pct < MIN_PCT:
            continue
        users.append(r["user_id"]), items.append(r["title_id"]), times.append(float(r.get("updated_at", 0)))
        weights.append(w), pcts.append(1.0 if done else pct)
    # every READY title is an item (even with no views), so recommendations can cover the whole catalogue
    iids_full = sorted(ready)
    item_index = {t: k for k, t in enumerate(iids_full)}
    uids = sorted(set(users))
    user_index = {x: k for k, x in enumerate(uids)}
    u = np.array([user_index[x] for x in users], dtype=np.int64)
    i = np.array([item_index[x] for x in items], dtype=np.int64)
    genres = {tid: t.get("genres", []) for tid, t in ready.items()}
    gm = _genre_matrix(iids_full, genres)
    years = np.array([float(ready[t].get("year", 2000)) for t in iids_full], dtype=np.float32)
    dur = np.array([math.log(max(30.0, float(ready[t].get("duration_sec", 600)))) for t in iids_full], dtype=np.float32)
    num = np.stack([(years - years.mean()) / (years.std() + 1e-6), (dur - dur.mean()) / (dur.std() + 1e-6)], axis=1)
    feats = np.concatenate([gm, num], axis=1).astype(np.float32)
    inter = Interactions(u, i, np.array(times), np.array(weights, dtype=np.float32), len(uids), len(iids_full), feats,
                         iids_full, uids, [ready[t]["title"] for t in iids_full])
    meta = {"pct": np.array(pcts), "genres": genres, "titles": ready}
    return inter, meta
