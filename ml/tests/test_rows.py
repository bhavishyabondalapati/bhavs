import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bhavs_rec import bhavs_data, data, rows
from bhavs_rec.als import ALS

TITLES = [{"id": f"t{k}", "title": f"Title {k}", "genres": g, "year": 2010 + k, "duration_sec": 300 + 60 * k}
          for k, g in enumerate([["comedy"], ["comedy"], ["sci-fi"], ["sci-fi"], ["drama"], ["drama"]])]


def history():
    rng = np.random.default_rng(1)
    out = []
    for u in range(30):
        liked = [0, 1, 4] if u < 15 else [2, 3, 5]
        for k, t in enumerate(rng.permutation(liked)[:2]):
            out.append({"user_id": f"u{u:02d}", "title_id": f"t{t}", "position": 0, "duration": 300, "completed": True,
                        "plays": 1, "max_pct": 1.0, "updated_at": 1000 + k})
    out.append({"user_id": "u00", "title_id": "t3", "position": 10, "duration": 300, "completed": False, "max_pct": 0.05, "updated_at": 5})
    return out


def test_engagement_handles_real_rows_without_extra_fields():
    pct, done, w = bhavs_data.engagement({"position": 150, "duration": 300, "completed": False})
    assert pct == 0.5 and not done and w == 0.5
    assert bhavs_data.engagement({"position": 0, "duration": 300, "completed": True})[0] == 1.0


def test_low_engagement_is_not_a_positive():
    inter, _ = bhavs_data.load(history(), TITLES)
    t3 = inter.item_ids.index("t3")
    u0 = inter.user_ids.index("u00")
    assert not any(u == u0 and i == t3 for u, i in zip(inter.users, inter.items, strict=True))


def test_rows_exclude_watched_and_cover_cold_start():
    inter, meta = bhavs_data.load(history(), TITLES)
    split = data.full_split(inter)
    model = ALS(factors=4, reg=0.5, alpha=10, iterations=8).fit(split)
    per_user = dict(rows.user_rows(model, inter, split.train, meta, "als", now=1))
    u = per_user["u00"]
    watched = {r["title_id"] for r in history() if r["user_id"] == "u00" and r["max_pct"] >= 0.5}
    top = next(r for r in u if r["row_key"] == "top_picks")
    assert not watched & set(top["title_ids"]) and top["rank"] == 1
    assert any(r["label"].startswith("Because you watched ") for r in u)
    for r in u:
        assert not watched & set(r["title_ids"])
    glob = rows.global_rows(inter, rows.popularity(inter, split.train), meta, 1)
    keys = {r["row_key"] for r in glob}
    assert "popular" in keys and "genre#comedy" in keys and all(r["user_id"] == "GLOBAL" for r in glob)


def test_taste_groups_get_their_own_titles():
    inter, meta = bhavs_data.load(history(), TITLES)
    split = data.full_split(inter)
    model = ALS(factors=4, reg=0.5, alpha=10, iterations=10).fit(split)
    per_user = dict(rows.user_rows(model, inter, split.train, meta, "als", now=1))
    # u01 likes {0,1,4}; they should not be told to watch the other group's titles above their own taste's leftovers
    top = next(r for r in per_user["u01"] if r["row_key"] == "top_picks")["title_ids"]
    assert top[0] in {"t0", "t1", "t4"}
