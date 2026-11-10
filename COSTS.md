# bhavs cost tracking

Budget: ~$100 AWS credits, target well under. Alerts at $50 / $80 / $100 actual usage (credits excluded).

| Phase | What bills | Estimated cost | Actual |
|---|---|---|---|
| Setup / Phase 0 | nothing (read-only CLI calls, 2 tiny Bedrock embedding calls) | ~$0.00 | |
| Phase 1 | DynamoDB on-demand, Lambda, API GW, Cognito Essentials, Budgets (first 2 budgets free), CloudWatch logs | <$0.50 for the whole phase; ~$0 idle | |
| Phase 2 | Fargate ARM64 transcode (MediaConvert is blocked), S3 storage, CloudFront | $0.17-$0.43 one-off for the 7 verified films (70 min), ~$0.18/month storage | |
| Phase 3 | Firehose, Athena, S3 | few $ | |
| Phase 4 | SageMaker CPU training job | cents per run | |
| Phase 5 | Bedrock embeddings | pennies | |
| Phase 6 | CloudWatch dashboard ($3/mo), alarms, load test | few $ | |

Idle cost right now: $0.

## Budgets
- `bhavs-usage` (account-wide, credits excluded): alerts at $50 / $80 / $100 actual. It also counts your other projects in this account.
- **Tag-filtered budget (Project=bhavs): NOT possible from this account.** This account is a member of an AWS
  Organization and `ce:ListCostAllocationTags` / activation is denied ("Linked account doesn't have access to cost
  allocation tags"). Only the Organization's management account can activate the `Project` tag. If it is activated
  later, add a second `aws_budgets_budget` with `cost_filter { name = "TagKeyValue" values = ["user:Project$bhavs"] }`.

## Actuals
| When | Item | Cost |
|---|---|---|
| Phase 1 deploy | 53 resources, all pay-per-use, nothing billing while idle | ~$0.00 |
| Vercel | Hobby project `bhavs` | $0 |

## Phase 2 decisions and estimates
- **Compute: Fargate ARM64 (Graviton), Spot first, one on-demand retry.** Verified in AWS docs (ECS API reference
  `CapacityProviderStrategyItem`, and the Sept 2024 announcement): `FARGATE_SPOT` supports Linux ARM64 on platform
  version 1.4.0+, in all commercial regions. So no x86 image was needed.
- **Task size:** 4 vCPU / 8 GB. Price used: $0.03238 per vCPU-hour + $0.00356 per GB-hour (ARM, N. Virginia list
  price; the us-east-2 rate was not on the page I could read, and is normally the same) + $0.005/hour public IPv4
  = **$0.163/hour**. The Spot discount is not verified, so every figure is the on-demand price (Spot should be lower).
- **Speed assumption (NOT yet measured):** encoding the 4-rung ladder runs at 0.5x-1.5x realtime on 4 Graviton
  vCPUs, plus ~2 min overhead per film. The first real run replaces this with a measured number.
- **Estimate for the 7 verified films (70 min of video):** 1.0-2.6 task-hours = **$0.17-$0.43** total, ~$0.01
  for Step Functions/Lambda/EventBridge. Storage: ~6.1 GB of renditions + 1.6 GB sources = ~$0.18/month.
- **Idle cost of everything added in Phase 2: ~$0.** ECR image (79 MB compressed) ~ $0.01/month. CloudFront,
  Step Functions, SQS, EventBridge, ECS cluster and Lambda all bill per use. CloudFront's free tier (1 TB/month
  egress) covers this project.
- Docker note: pushing one large image layer through Docker Desktop's proxy failed repeatedly, so the Dockerfile
  uses Alpine and splits the install into several small layers (the image is 79 MB compressed vs ~550 MB).

## First real transcode: Big Buck Bunny (measured, 2026-11-09)
| | Measured |
|---|---|
| Video length | 10.6 min (635 s), 1920x1080 WebM, 300 MB |
| Capacity used | FARGATE_SPOT, ARM64, 4 vCPU / 8 GB, platform 1.4.0 (first attempt succeeded, no on-demand retry) |
| Billed task time | 7 min 42 s (image pull started 14:37:00, task stopped 14:44:42) |
| End to end (upload -> READY) | 8 min 10 s = **1.3x realtime** overall; ffmpeg itself ran at **1.6x realtime** (48 fps) |
| Cost, on-demand-equivalent | 0.1283 h x $0.158 + public IPv4 + 10 GB extra storage = **~$0.021** (Spot is cheaper; the real bill shows in Cost Explorer ~24 h later) |
| Output | 895 MB total: 360p 77 MB, 540p 156 MB, 720p 251 MB, 1080p 410 MB (433 objects) |
| vs. estimate | estimated $0.026-$0.064 -> actual (on-demand basis) $0.021: slightly better than the optimistic end |

The speed assumption in the cost model (0.5x-1.5x realtime) was slightly pessimistic: real speed was 1.6x.

## Phase 3 additions (idle cost ~ $0)
- SQS (events + DLQ), 3 Lambdas, Glue database + 2 tables (partition projection, no crawler), Athena workgroup `bhavs`
  (1 GB scan cap per query = at most $0.005), hourly EventBridge Scheduler: all per-use.
- Athena: $5 per TB scanned, 10 MB minimum per query. The 5 report queries scan well under 10 MB each, so
  a full report refresh costs ~$0.00025. The hourly job only rebuilds the report when new hours were compacted.
- S3 analytics bucket: a few MB of gzip/Parquet.

## Catalogue transcodes (17 films, measured)
- 17 titles, 2.2 GB of sources, ~108 min of video; all on Fargate Spot ARM64, 4 vCPU / 8 GB.
- Retries cost extra: **hero**, **coffee-run** and **caminandes-gran-dillama** were transcoded twice because of problems
  on *my* side (a corrupted local download for all three, plus a filename-matching bug that fed Gran Dillama the wrong
  film). Roughly 5 extra task-runs of a few minutes each, i.e. a few cents. Both bugs are fixed and tested.
- Estimated total for all runs: ~$0.30 on-demand-equivalent. The real figure shows in Cost Explorer ~24 h later.

## Phase 4 (recommendations)
- **Local (free):** the MovieLens benchmark (small + 1M) runs on the Mac (Apple GPU via `mps`): ~6.5 min for ml-1m.
- **Cloud training job** (run 2026-11-09, Fargate Spot ARM64): Fargate ARM64, **2 vCPU / 4 GB** (SageMaker `ml.m5.large` quota is 0, request still
  `CASE_OPENED`). Price: 2 x $0.03238 + 4 x $0.00356 + $0.005 (IPv4) = **$0.084/hour** on-demand. A run is ~3 min including
  the ~1.6 GB image pull, so **~$0.004 per run on-demand** (Spot cheaper). Weekly = ~$0.02/month.
- ECR `bhavs-train` image (CPU PyTorch, ~0.5 GB compressed): ~$0.05/month. Weekly schedule (Sundays 06:00 UTC) is **ENABLED** (~$0.02/month).
- First cloud run: attempt 1 trained fine but crashed writing a local summary file (read-only dir in the container; no
  rows written). Fixed, image rebuilt, attempt 2 exited 0 in about 1 minute of task time (~$0.001 on-demand-equivalent each).
  Cloud rows matched the local run (746 rows; one adjacent swap in a top-4 list from CPU vs Apple-GPU float differences).
- SageMaker `ml.m5.large` quota case is left open. Fargate is the documented training path; SageMaker is optional if approved.
