"""Train on bhavs watch data and publish recommendation rows.

  python ml/train.py --source dynamodb --model auto        # production run (also what the cloud job runs)
  python ml/train.py --source dynamodb --dry-run           # train + print, write nothing

Entry point for: `make train`, the weekly EventBridge Scheduler job, and the SageMaker/Fargate container.
"""
import argparse
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).parent))
from bhavs_rec import bhavs_data, data, metrics, rows
from bhavs_rec.als import ALS
from bhavs_rec.popularity import Popularity
from bhavs_rec.two_tower import TwoTower

HERE = Path(__file__).parent


def scan(table):
    items, kw = [], {}
    while True:
        page = table.scan(**kw)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            return items
        kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def plain(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, list):
        return [plain(x) for x in o]
    if isinstance(o, dict):
        return {k: plain(v) for k, v in o.items()}
    return o


def make_model(name, n_items):
    # Tiny catalogue (dozens of titles), so small factor counts; MovieLens-scale settings would just overfit.
    if name == "two_tower":
        return TwoTower(dim=16, epochs=40, lr=3e-3, temp=0.1, batch=256, hist_len=30, eval_every=1000)
    return ALS(factors=min(8, max(2, n_items - 1)), reg=0.5, alpha=10, iterations=15)


def sanity_check(inter):
    """Leave-last-out on the (synthetic) bhavs data. With ~17 titles this only shows the pipeline discriminates;
    it is NOT a benchmark (that is MovieLens, see RESULTS.md)."""
    split = data.leave_last_out(inter, min_positives=4)
    n = int((split.test_item >= 0).sum())
    if n < 20:
        return {"note": "too little data", "eval_users": n}
    out = {"eval_users": n, "n_items": inter.n_items}
    for nm, m in (("popularity", Popularity()), ("als", make_model("als", inter.n_items)), ("two_tower", make_model("two_tower", inter.n_items))):
        m.fit(split, item_features=inter.item_features)
        out[nm] = metrics.evaluate(m.score, split, split.test_item, exclude_extra=split.val_item)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="auto", choices=["auto", "als", "two_tower"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    a = ap.parse_args()

    sess = boto3.Session(profile_name=a.profile or None, region_name="us-east-2")
    ddb = sess.resource("dynamodb")
    t0 = time.time()
    titles = [plain(t) for t in scan(ddb.Table("bhavs-titles")) if t.get("status") == "READY"]
    hist = [plain(h) for h in scan(ddb.Table("bhavs-watch-history"))]
    inter, meta = bhavs_data.load(hist, titles)
    print(f"{inter.n_users} users, {inter.n_items} READY titles, {len(inter.users)} positive interactions", flush=True)
    if inter.n_users < 5:
        sys.exit("Not enough watch data to train (need >= 5 users with views).")

    name = a.model
    if name == "auto":
        best = HERE / "best_model.txt"
        name = best.read_text().strip() if best.exists() else "als"
    print("model:", name, flush=True)
    sanity = sanity_check(inter)
    print("offline sanity check (synthetic, tiny catalogue):", json.dumps(sanity, default=float), flush=True)

    full = data.full_split(inter)
    model = make_model(name, inter.n_items).fit(full, item_features=inter.item_features)
    now = time.time()
    per_user = rows.user_rows(model, inter, full.train, meta, name, now)
    glob = rows.global_rows(inter, rows.popularity(inter, full.train), meta, now)
    total = sum(len(r) for _, r in per_user) + len(glob)
    print(f"generated {total} rows for {len(per_user)} users + GLOBAL", flush=True)
    for uid, rr in per_user[:2]:
        for r in rr:
            print(f"  {uid} {r['rank']} {r['label']}: {r['title_ids'][:4]}...", flush=True)

    summary = {"model": name, "users": inter.n_users, "titles": inter.n_items, "interactions": len(inter.users),
               "rows": total, "sanity": sanity, "seconds": round(time.time() - t0, 1), "generated_at": int(now)}
    (HERE / "artifacts").mkdir(exist_ok=True)
    (HERE / "artifacts" / "bhavs-run.json").write_text(json.dumps(summary, indent=2, default=float))
    if a.dry_run:
        return
    if os.environ.get("RESULTS_BUCKET"):
        sess.client("s3").put_object(Bucket=os.environ["RESULTS_BUCKET"], Key=f"ml/runs/{int(now)}.json",
                                     Body=json.dumps(summary, default=float))
    table = ddb.Table("bhavs-recommendations")
    old = [x for x in scan(table) if x.get("source") == "ml-job"]
    with table.batch_writer() as w:
        for x in old:
            w.delete_item(Key={"user_id": x["user_id"], "row_key": x["row_key"]})
        for _, rr in per_user:
            for r in rr:
                w.put_item(Item=json.loads(json.dumps(r, default=float), parse_float=Decimal))
        for r in glob:
            w.put_item(Item=json.loads(json.dumps(r, default=float), parse_float=Decimal))
    print(f"replaced {len(old)} old rows with {total} new rows in bhavs-recommendations", flush=True)


if __name__ == "__main__":
    main()
