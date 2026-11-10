# bhavs

A Netflix-style streaming platform on AWS (portfolio project). Work in progress; the full README
is written in Phase 6. See COSTS.md for the running cost estimate.

## Recommendations (Phase 4)
- Models: popularity baseline, ALS (from scratch, numpy) and a two-tower neural net (PyTorch). Both learned models beat
  popularity by about 2x on MovieLens-1M; the two-tower vs ALS difference is within the confidence interval, so neither is
  claimed better. Details: [ml/RESULTS.md](ml/RESULTS.md).
- **Training path: AWS Fargate** (Spot, ARM64, 2 vCPU / 4 GB) runs weekly via EventBridge Scheduler, or once with
  `make train-cloud`. SageMaker is not used (training quota is 0 on this account); it would be an optional alternative if the
  quota is ever approved.
- Benchmark data credit: MovieLens from [GroupLens](https://grouplens.org/datasets/movielens/) (F. Maxwell Harper and
  Joseph A. Konstan, *The MovieLens Datasets: History and Context*, ACM TiiS 2015). Not redistributed; `ml/data/` is gitignored.

## Search (Phase 5): hybrid keywords + meaning
- `make embed` turns every READY title (name + genres + description) into a 256-number vector with Amazon Bedrock
  Titan Text Embeddings V2 and saves the vectors plus the keyword text as one JSON file in S3.
- `GET /search?q=...` runs two searches inside a Lambda and merges them with reciprocal rank fusion (RRF):
  **meaning** (cosine similarity of the query's Titan vector, so "a lonely dragon" finds Sintel) and **keywords**
  (BM25, so exact words like "Patagonia" or "fence" always count). No vector database: ~20 titles take microseconds.
- Evaluated with `make search-eval` on labelled queries (`ml/search_eval.yaml`, dev/test split). Held-out test set:
  hybrid hit@3 **0.955** / MRR **0.864** vs vector-only 0.636 / 0.492, with no extra false results on the "should find
  nothing" queries (4/5 for both). Small, self-labelled set: see [ml/SEARCH_EVAL.md](ml/SEARCH_EVAL.md) for caveats.
