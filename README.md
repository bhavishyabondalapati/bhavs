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
