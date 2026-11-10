"""MovieLens benchmark: popularity vs ALS vs two-tower, same split, same metrics.

  python ml/benchmark.py --dataset ml-latest-small          # fast iteration (small grid, 3 seeds for two-tower)
  python ml/benchmark.py --dataset ml-1m --seeds 3          # final numbers

Hyper-parameters are chosen on the VALIDATION item (second-to-last interaction); the TEST item (last) is only
scored once, with the chosen settings. Results are written to ml/artifacts/results-<dataset>.json.
"""
import argparse
import itertools
import json
import statistics
import time
from pathlib import Path

import numpy as np
from bhavs_rec import data, metrics
from bhavs_rec.als import ALS
from bhavs_rec.popularity import Popularity
from bhavs_rec.two_tower import TwoTower, pick_device

HERE = Path(__file__).parent
ALS_GRID = [{"factors": f, "reg": r, "alpha": a} for f, r, a in itertools.product([32, 64], [0.05, 0.5], [10, 40])]
TT_GRID = [{"dim": d, "lr": lr, "temp": t} for d, lr, t in itertools.product([64], [1e-3, 3e-3], [0.05, 0.1])]


def val_fn(split):
    return lambda model: metrics.evaluate(model.score, split, split.val_item)


def test_metrics(model, split):
    return metrics.evaluate(model.score, split, split.test_item, exclude_extra=split.val_item)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="ml-latest-small")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--als-iters", type=int, default=12)
    ap.add_argument("--tt-epochs", type=int, default=40)
    ap.add_argument("--quick", action="store_true", help="smaller grids (smoke test)")
    a = ap.parse_args()

    root = HERE / "data"
    folder = next(p for p in root.glob(f"{a.dataset}*") if (p / a.dataset).is_dir())
    t0 = time.time()
    inter = data.load_movielens(folder, a.dataset)
    split = data.leave_last_out(inter)
    n_eval = int((split.test_item >= 0).sum())
    print(f"{a.dataset}: {inter.n_users} users, {inter.n_items} items, {len(inter.users)} positives "
          f"(rating>=4); train {len(split.train_u)}; evaluating {n_eval} users  [load {time.time() - t0:.1f}s]", flush=True)
    out = {"dataset": a.dataset, "device": pick_device(), "users": inter.n_users, "items": inter.n_items,
           "positives": len(inter.users), "train_pairs": len(split.train_u), "eval_users": n_eval,
           "split": "per-user temporal leave-last-out (test = last positive, val = second-to-last)",
           "models": {}}

    pop = Popularity().fit(split)
    out["models"]["popularity"] = {"val": val_fn(split)(pop), "test": test_metrics(pop, split), "params": {}}
    print("popularity", out["models"]["popularity"]["test"], flush=True)

    best = None
    als_grid = ALS_GRID[:2] if a.quick else ALS_GRID
    for params in als_grid:
        t = time.time()
        m = ALS(iterations=a.als_iters, **params).fit(split)
        v = val_fn(split)(m)["recall@10"]
        print(f"  ALS {params} val recall@10 {v:.4f} ({time.time() - t:.0f}s)", flush=True)
        if best is None or v > best[0]:
            best = (v, params, m)
    m = best[2]
    out["models"]["als"] = {"val": val_fn(split)(m), "test": test_metrics(m, split),
                            "params": {**best[1], "iterations": a.als_iters}, "grid_size": len(als_grid)}
    print("als", out["models"]["als"]["test"], flush=True)

    best = None
    tt_grid = TT_GRID[:2] if a.quick else TT_GRID
    for params in tt_grid:
        t = time.time()
        m = TwoTower(epochs=a.tt_epochs, seed=0, **params).fit(split, item_features=inter.item_features, eval_fn=val_fn(split))
        print(f"  two-tower {params} val recall@10 {m.best_val:.4f} ({time.time() - t:.0f}s)", flush=True)
        if best is None or m.best_val > best[0]:
            best = (m.best_val, params)
    runs = []
    for seed in range(a.seeds):
        m = TwoTower(epochs=a.tt_epochs, seed=seed, **best[1]).fit(split, item_features=inter.item_features, eval_fn=val_fn(split))
        runs.append({"seed": seed, "val": val_fn(split)(m), "test": test_metrics(m, split)})
        print(f"  two-tower seed {seed}: test {runs[-1]['test']}", flush=True)
    summary = {k: {"mean": statistics.mean(r["test"][k] for r in runs),
                   "std": statistics.pstdev(r["test"][k] for r in runs)} for k in ("recall@10", "ndcg@10")}
    out["models"]["two_tower"] = {"test": {"recall@10": summary["recall@10"]["mean"], "ndcg@10": summary["ndcg@10"]["mean"],
                                           "users_evaluated": n_eval},
                                  "test_std": {k: v["std"] for k, v in summary.items()}, "seeds": a.seeds,
                                  "val": {"recall@10": statistics.mean(r["val"]["recall@10"] for r in runs)},
                                  "params": {**best[1], "epochs_max": a.tt_epochs}, "grid_size": len(tt_grid)}
    out["total_seconds"] = round(time.time() - t0)
    (HERE / "artifacts").mkdir(exist_ok=True)
    (HERE / "artifacts" / f"results-{a.dataset}.json").write_text(json.dumps(out, indent=2))
    print(json.dumps({k: v["test"] for k, v in out["models"].items()}, indent=1))
    print(f"total {out['total_seconds']}s")
    np.set_printoptions()


if __name__ == "__main__":
    main()
