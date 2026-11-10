"""Evaluate search quality: vector-only (the Phase 5 ranking) vs hybrid (cosine + BM25 fused with RRF).

Metrics, over queries that have a right answer:
  hit@3  share of queries with at least one relevant title in the top 3
  MRR    mean of 1/rank of the first relevant title (0 if none returned)
  recall share of ALL relevant titles that were returned at all (matters for "llama" -> three films)
Over queries that should return nothing:
  empty  share of them that correctly returned no results.

Needs AWS (profile sky) once: it reads the title vectors from S3, the catalogue text from DynamoDB and embeds each query
with Bedrock Titan V2 (a few dozen calls = well under a cent). Query vectors are cached in
ml/artifacts/search_eval_vectors.json, so re-runs and floor sweeps are free and reproducible.

Usage: python ml/search_eval.py [--floor 0.3] [--sweep] [--report] [--json ml/artifacts/search_eval.json]
"""
import argparse
import json
import os
import sys
from pathlib import Path

import boto3
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "src"))
from api import search
from shared import embed

CACHE = ROOT / "ml" / "artifacts" / "search_eval_vectors.json"


def load_items():
    """The production search index from S3 (vectors + keyword text)."""
    s = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "sky"), region_name="us-east-2")
    embed._client = s.client("bedrock-runtime")
    bucket = os.environ.get("ANALYTICS_BUCKET") or _bucket()
    index = json.loads(s.client("s3").get_object(Bucket=bucket, Key="search/embeddings.json")["Body"].read())
    titles = {t["id"]: t for t in s.resource("dynamodb").Table("bhavs-titles").scan()["Items"]}
    # Use the text stored in the index (exactly what the Lambda reads); older indexes without it fall back to DynamoDB.
    return [it if "text" in it else {**it, "text": embed.keyword_text(titles[it["id"]])} for it in index["items"]]


def _bucket():
    import subprocess
    return subprocess.check_output(["terraform", f"-chdir={ROOT}/infra/persistent", "output", "-raw", "analytics_bucket"],
                                   text=True).strip()


def query_vectors(queries):
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    missing = [q for q in queries if q not in cache]
    for q in missing:
        cache[q] = embed.embed(q)
    if missing:
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(cache))
        print(f"embedded {len(missing)} new queries")
    return cache


def score(rankers, queries, items, vecs):
    """rankers: {name: fn(q, items, qvec) -> [(score, id)]}. Returns {name: metrics} and per-query ranked ids."""
    out, detail = {}, {}
    for name, fn in rankers.items():
        hits = rr = rec = n_pos = empty = n_neg = 0
        detail[name] = {}
        for c in queries:
            ids = [i for _, i in fn(c["q"], items, vecs[c["q"]])]
            detail[name][c["q"]] = ids
            rel = set(c["relevant"])
            if not rel:
                n_neg += 1
                empty += not ids
                continue
            n_pos += 1
            hits += any(i in rel for i in ids[:3])
            rr += next((1 / r for r, i in enumerate(ids, 1) if i in rel), 0.0)
            rec += len(rel & set(ids)) / len(rel)
        out[name] = {"hit@3": hits / n_pos, "MRR": rr / n_pos, "recall": rec / n_pos,
                     "empty_ok": f"{empty}/{n_neg}", "n_pos": n_pos, "n_neg": n_neg}
    return out, detail


def fmt(metrics):
    lines = ["| Ranker | hit@3 | MRR | recall (all relevant returned) | no-result queries correctly empty |", "|---|---|---|---|---|"]
    for name, m in metrics.items():
        lines.append(f"| {name} | {m['hit@3']:.3f} | {m['MRR']:.3f} | {m['recall']:.3f} | {m['empty_ok']} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--floor", type=float, default=None)
    ap.add_argument("--sweep", action="store_true", help="sweep the cosine floor on the DEV set only")
    ap.add_argument("--show", action="store_true", help="print the cosine range per query (dev set)")
    ap.add_argument("--json", default=None)
    ap.add_argument("--report", action="store_true", help="write ml/SEARCH_EVAL.md")
    a = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "ml" / "search_eval.yaml").read_text())
    items = load_items()
    vecs = query_vectors([c["q"] for c in cfg["dev"] + cfg["test"]])

    if a.show or a.sweep:
        for c in cfg["dev"]:
            cs = sorted((embed.dot(vecs[c["q"]], it["vector"]) for it in items), reverse=True)
            kw = search.textsearch.bm25_scores(c["q"], items)
            print(f"{c['q'][:34]:36} {'POS' if c['relevant'] else 'neg'} top cos {cs[0]:.3f} {cs[1]:.3f} {cs[2]:.3f}"
                  f"  bm25 matches {len(kw)}")
    if a.sweep:
        for f in [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]:
            m, _ = score({"hybrid": lambda q, i, v, f=f: search.rank_hybrid(q, i, v, vec_floor=f)}, cfg["dev"], items, vecs)
            print(f"floor {f:.2f} (dev): {m['hybrid']}")
        return

    floor = a.floor if a.floor is not None else search.VEC_FLOOR
    rankers = {"vector-only (Phase 5)": search.rank_vector,
               f"hybrid (BM25 + cosine, RRF, floor {floor})": lambda q, i, v: search.rank_hybrid(q, i, v, vec_floor=floor)}
    m, detail = score(rankers, cfg["test"], items, vecs)
    print(f"TEST set: {m[next(iter(m))]['n_pos']} queries with answers, {m[next(iter(m))]['n_neg']} that should return nothing")
    print(fmt(m))
    names = list(rankers)
    for c in cfg["test"]:
        rel = set(c["relevant"])
        def tag(ids, rel=rel):
            return ", ".join(("*" if i in rel else "") + i for i in ids[:4]) or "(none)"
        print(f"- {c['q']!r}  expected {sorted(rel) or 'nothing'}\n    vec: {tag(detail[names[0]][c['q']])}\n    hyb: {tag(detail[names[1]][c['q']])}")
    if a.json:
        Path(a.json).write_text(json.dumps({"metrics": m, "floor": floor}, indent=1))
    if a.report:
        write_report(m, cfg, floor)


def write_report(metrics, cfg, floor):
    n = metrics[next(iter(metrics))]
    (ROOT / "ml" / "SEARCH_EVAL.md").write_text(f"""# Search evaluation (generated by `make search-eval`)

Compares the Phase 5 **vector-only** search with the **hybrid** search (BM25 keywords + Titan V2 cosine, merged with
reciprocal rank fusion) on the bhavs catalogue ({len(cfg['test'])} held-out test queries in `ml/search_eval.yaml`:
{n['n_pos']} with a right answer, {n['n_neg']} where the right answer is *no results*).

{fmt(metrics)}

- **hit@3**: share of queries with a relevant title in the top 3. **MRR**: mean of 1/rank of the first relevant title.
  **all relevant returned**: share of relevant titles returned at all (e.g. "llama" has three).
- The only tuned value, the cosine floor ({floor}), was picked on the separate **dev** queries; the test queries were
  scored once.

**Caveats (read these before quoting the numbers).**
- Tiny and home-made: {len(cfg['test'])} queries over 17 titles, and the relevance labels were written by the person who
  built the system. This is a sanity check that hybrid is better *on this catalogue*, not a general benchmark.
- Several test queries ("a lonely dragon", "robots in the future", "cooking pasta recipe", "stock market news") were
  among those used to hand-pick the vector-only cut-offs in Phase 5. That favours the vector-only baseline, so the gap
  shown is, if anything, understated.
- Short catalogue descriptions (several are one generic line) limit both methods: "one minute short" fails for both
  because the matching description says "one-minute".
""")
    print("wrote ml/SEARCH_EVAL.md")


if __name__ == "__main__":
    main()
