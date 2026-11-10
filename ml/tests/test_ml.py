import sys
from pathlib import Path

import numpy as np
from scipy import sparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bhavs_rec import data, metrics
from bhavs_rec.als import ALS
from bhavs_rec.popularity import Popularity
from bhavs_rec.two_tower import TwoTower


def toy(n_users=40, n_items=30, seed=0):
    """Two taste groups: users 0..19 like items 0..14, users 20..39 like items 15..29, in time order."""
    rng = np.random.default_rng(seed)
    u, i, t = [], [], []
    for user in range(n_users):
        pool = np.arange(15) if user < 20 else np.arange(15, 30)
        for k, item in enumerate(rng.choice(pool, size=10, replace=False)):
            u.append(user), i.append(int(item)), t.append(float(k))
    u, i, t = map(np.array, (u, i, t))
    return data.Interactions(u, i, t, np.ones(len(u), np.float32), n_users, n_items,
                             np.zeros((n_items, 0), np.float32), [str(x) for x in range(n_items)],
                             [str(x) for x in range(n_users)], [str(x) for x in range(n_items)])


def test_split_is_temporal_and_leak_free():
    inter = toy()
    s = data.leave_last_out(inter)
    for user in range(inter.n_users):
        mine = inter.times[inter.users == user]
        its = inter.items[inter.users == user]
        order = np.argsort(mine)
        assert s.test_item[user] == its[order][-1] and s.val_item[user] == its[order][-2]
        assert s.train[user, s.test_item[user]] == 0 and s.train[user, s.val_item[user]] == 0   # nothing held-out in train
    assert s.train.nnz == len(inter.users) - 2 * inter.n_users


def test_metrics_known_values():
    split = type("S", (), {"train": sparse.csr_matrix((3, 5), dtype=np.float32)})()
    scores = np.array([[5, 4, 3, 2, 1], [1, 2, 3, 4, 5], [1, 1, 1, 1, 1]], dtype=np.float32)
    r = metrics.evaluate(lambda u: scores[u], split, np.array([0, 0, 0]), k=2)
    # user0: rank0 -> hit, ndcg 1.0 ; user1: rank4 -> miss ; user2: all tied -> pessimistic rank 4 -> miss
    assert abs(r["recall@10"] - 1 / 3) < 1e-9 and abs(r["ndcg@10"] - 1 / 3) < 1e-9


def test_metrics_exclude_train_items():
    train = sparse.csr_matrix(np.array([[0, 1, 0]], dtype=np.float32))
    split = type("S", (), {"train": train})()
    r = metrics.evaluate(lambda u: np.array([[1.0, 9.0, 2.0]]), split, np.array([2]), k=1)
    assert r["recall@10"] == 1.0   # item 1 has the top score but is already in train, so item 2 ranks first


def test_models_beat_popularity_on_structured_data():
    inter = toy()
    s = data.leave_last_out(inter)
    ev = lambda m: metrics.evaluate(m.score, s, s.test_item, exclude_extra=s.val_item)["recall@10"]
    pop = ev(Popularity().fit(s))
    als = ev(ALS(factors=8, reg=0.1, alpha=10, iterations=8).fit(s))
    tt = ev(TwoTower(dim=16, epochs=60, batch=128, lr=5e-3, device="cpu", eval_every=100).fit(s))
    assert als > pop and tt > pop


def test_als_scores_group_items_higher():
    inter = toy()
    s = data.leave_last_out(inter)
    m = ALS(factors=8, iterations=8).fit(s)
    sc = m.score(np.array([0]))[0]
    assert sc[:15].mean() > sc[15:].mean()
