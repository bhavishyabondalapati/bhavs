"""Full-ranking evaluation (every item is a candidate, no sampled negatives) with ONE held-out item per user.

recall@K  = fraction of users whose held-out item is in their top K      (== hit rate for one held-out item)
NDCG@K    = mean of 1/log2(rank+2) when the item is in the top K, else 0 (rank is 0-based)
Items the user already interacted with in TRAIN (and VAL, when testing) are excluded from the candidates.
Ties are resolved pessimistically (a tied item counts as ranked above the target) so a constant scorer can't win.
"""
import numpy as np


def evaluate(score_fn, split, target, exclude_extra=None, k=10, batch=2048):
    """score_fn(user_ids ndarray) -> [B, n_items] float array. target: held-out item per user (-1 = skip)."""
    users = np.flatnonzero(target >= 0)
    hits, ndcg = 0.0, 0.0
    for s in range(0, len(users), batch):
        ub = users[s:s + batch]
        scores = np.array(score_fn(ub), dtype=np.float32, copy=True)
        rows = split.train[ub].tocoo()
        scores[rows.row, rows.col] = -np.inf
        if exclude_extra is not None:
            m = exclude_extra[ub]
            ok = m >= 0
            scores[np.flatnonzero(ok), m[ok]] = -np.inf
        tgt = target[ub]
        tscore = scores[np.arange(len(ub)), tgt]
        rank = (scores >= tscore[:, None]).sum(axis=1) - 1     # pessimistic ties
        in_top = rank < k
        hits += in_top.sum()
        ndcg += (1.0 / np.log2(rank[in_top] + 2)).sum()
    n = max(1, len(users))
    return {"recall@10": hits / n, "ndcg@10": ndcg / n, "users_evaluated": len(users)}
