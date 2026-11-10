"""Datasets + the evaluation split.

Interactions are IMPLICIT: a (user, item) pair is a positive. For MovieLens a positive is a rating >= 4.
The split is a per-user TEMPORAL leave-last-out: sort each user's positives by time, hold out the last as
TEST and the second-to-last as VALIDATION; everything earlier is TRAIN. No future information leaks into training.
"""
import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import sparse

POSITIVE_RATING = 4.0


@dataclass
class Interactions:
    users: np.ndarray        # int64 internal ids
    items: np.ndarray
    times: np.ndarray        # float seconds
    weights: np.ndarray      # engagement strength (1.0 for plain implicit)
    n_users: int
    n_items: int
    item_features: np.ndarray   # [n_items, F] float32 (genre multi-hot + optional numerics)
    item_ids: list           # internal -> original id (str)
    user_ids: list
    item_names: list


@dataclass
class Split:
    train: sparse.csr_matrix     # [n_users, n_items] weights
    train_u: np.ndarray
    train_i: np.ndarray
    train_w: np.ndarray
    train_t: np.ndarray
    val_item: np.ndarray         # [n_users] held-out item or -1
    test_item: np.ndarray
    n_users: int
    n_items: int


def _reindex(raw_users, raw_items):
    uids, u = np.unique(np.asarray(raw_users), return_inverse=True)
    iids, i = np.unique(np.asarray(raw_items), return_inverse=True)
    return u.astype(np.int64), i.astype(np.int64), [str(x) for x in uids], [str(x) for x in iids]


def _genre_matrix(item_ids, genres_by_item):
    genres = sorted({g for gs in genres_by_item.values() for g in gs})
    gidx = {g: k for k, g in enumerate(genres)}
    mat = np.zeros((len(item_ids), len(genres)), dtype=np.float32)
    for row, iid in enumerate(item_ids):
        for g in genres_by_item.get(iid, []):
            mat[row, gidx[g]] = 1.0
    return mat


def load_movielens(root, name):
    """name: ml-latest-small | ml-1m | ml-25m. `root` is the directory holding the unzipped dataset folder."""
    base = Path(root) / name
    if name == "ml-1m":
        with open(base / "ratings.dat", encoding="latin-1") as f:
            rows = [ln.rstrip("\n").split("::") for ln in f]
        with open(base / "movies.dat", encoding="latin-1") as f:
            movies = {r[0]: (r[1], r[2].split("|")) for r in (ln.rstrip("\n").split("::") for ln in f)}
    else:
        with open(base / "ratings.csv", newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            next(r)
            rows = list(r)
        with open(base / "movies.csv", newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            next(r)
            movies = {row[0]: (row[1], row[2].split("|")) for row in r}
    arr = np.array(rows, dtype=object)
    keep = arr[:, 2].astype(np.float32) >= POSITIVE_RATING
    arr = arr[keep]
    u, i, uids, iids = _reindex(arr[:, 0], arr[:, 1])
    t = arr[:, 3].astype(np.float64)
    genres = {mid: [g for g in gs if g != "(no genres listed)"] for mid, (_, gs) in movies.items()}
    return Interactions(u, i, t, np.ones(len(u), dtype=np.float32), len(uids), len(iids),
                        _genre_matrix(iids, genres), iids, uids, [movies.get(x, (x, []))[0] for x in iids])


def leave_last_out(inter, min_positives=5):
    """Temporal per-user split (see module docstring). Users with fewer than `min_positives` stay in TRAIN only."""
    order = np.lexsort((inter.items, inter.times, inter.users))   # by user, then time, then item (stable ties)
    u, i, t, w = inter.users[order], inter.items[order], inter.times[order], inter.weights[order]
    starts = np.r_[0, np.flatnonzero(np.diff(u)) + 1]
    ends = np.r_[starts[1:], len(u)]
    val = np.full(inter.n_users, -1, dtype=np.int64)
    test = np.full(inter.n_users, -1, dtype=np.int64)
    is_train = np.ones(len(u), dtype=bool)
    for s, e in zip(starts, ends, strict=True):
        if e - s >= min_positives:
            test[u[s]], val[u[s]] = i[e - 1], i[e - 2]
            is_train[e - 2:e] = False
    tu, ti, tw, tt = u[is_train], i[is_train], w[is_train], t[is_train]
    mat = sparse.csr_matrix((tw, (tu, ti)), shape=(inter.n_users, inter.n_items), dtype=np.float32)
    return Split(mat, tu, ti, tw, tt, val, test, inter.n_users, inter.n_items)


def full_split(inter):
    """Production training: ALL interactions are train, nothing is held out."""
    mat = sparse.csr_matrix((inter.weights, (inter.users, inter.items)), shape=(inter.n_users, inter.n_items), dtype=np.float32)
    none = np.full(inter.n_users, -1, dtype=np.int64)
    return Split(mat, inter.users, inter.items, inter.weights, inter.times, none, none.copy(), inter.n_users, inter.n_items)
