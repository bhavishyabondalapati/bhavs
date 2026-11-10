# bhavs cost tracking

Budget: ~$100 AWS credits, target well under. Alerts at $50 / $80 / $100 actual usage (credits excluded).

| Phase | What bills | Estimated cost | Actual |
|---|---|---|---|
| Setup / Phase 0 | nothing (read-only CLI calls, 2 tiny Bedrock embedding calls) | ~$0.00 | |
| Phase 1 | DynamoDB on-demand, Lambda, API GW, Cognito Essentials, Budgets (first 2 budgets free), CloudWatch logs | <$0.50 for the whole phase; ~$0 idle | |
| Phase 2 | Fargate ARM64 transcode (MediaConvert is blocked), S3 storage, CloudFront | $0.17-$0.43 one-off for the 7 verified films (70 min), ~$0.18/month storage | |
| Phase 3 | SQS, Lambda, Athena, S3 (Firehose is blocked) | few $ | **$2.66 of S3 requests**: see the incident below |
| Phase 4 | Fargate training job (SageMaker quota is 0) | cents per run | ~$0.001 per run |
| Phase 5 | Bedrock Titan V2 embeddings | pennies | < $0.01 |
| Phase 6 | CloudWatch dashboard + 8 alarms (free allowance), X-Ray, load test | $0 idle (else $3.80/mo) | $0 so far |

Idle cost now: about **$0.45/month (~$0.015/day)**, almost all storage. See "Idle cost (final review)" at the end.

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

### Cost Explorer, 2026-11-01 to 2026-11-10 (usage, before credits; Cost Explorer lags ~24 h)
| Service | Cost | Notes |
|---|---|---|
| S3 | $2.66 | 531,855 Tier-1 requests (LIST/PUT); almost all from Athena listing empty folders (incident below). Storage itself is cents. |
| Claude Haiku 4.5 (Bedrock) | $1.61 | **Not bhavs.** All on 2026-11-06; nothing in this repo calls Haiku. Another workload in this account. |
| ECS (Fargate) | $0.087 | All transcodes (17 films plus retries) and training runs. Measured BBB alone ~$0.021. |
| Cost Explorer API | $0.02 | My own cost queries ($0.01 each). |
| Athena, VPC (public IPv4 for tasks), DynamoDB, EC2, CloudFront, ECR | $0.03 together | |
| **bhavs total** | **~$2.80** | of the ~$100 credits |

## Incident: Athena made ~530,000 S3 LIST requests ($2.66), fixed 2026-11-10
- **What happened.** Athena *partition projection* means Athena works out the possible `dt=/hour=` folders from a
  rule instead of a catalogue. The rule started on 2026-01-01, so every query that did not filter on `dt` made Athena
  check ~7,500 hour folders (313 days x 24), nearly all empty. Each of the 5 report queries did that, so one report
  rebuild cost ~37,000 S3 LIST requests (~$0.19). The Phase 3/4 recompaction runs rebuilt the report a dozen times.
- **How it was found.** The Phase 6 cost review: S3 "Requests-Tier1" was 233k on Nov 9 and 309k on Nov 10. Athena query
  statistics showed ~5.4 s of *planning* per report query (the listing) for queries that scan under 1 MB.
- **Fix.** (1) every report query filters `dt >= ?` for the last 30 days (passed as an Athena query parameter, which
  Athena uses to skip folders); (2) the projection starts at the first day with data (2026-10-31); (3) a scheduled run
  rebuilds the report at most every 6 hours. A regression test fails if a report query loses its `dt` filter.
- **After.** Planning dropped to 0.15-0.5 s per query; a full rebuild takes ~9 s instead of 110-165 s. A rebuild now
  lists ~1,300 folders today, at most ~3,600 once 30 days of data exist (~$0.02), at most 4 times a day.
- **Lesson.** "Serverless = $0 idle" hides per-request costs. Check request counts, not just storage and compute.

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

## Phase 5 (semantic search)
- **Bedrock Titan Text Embeddings V2** (256 dims): $0.00002 per 1K input tokens. Indexing 17 titles (~1K tokens) and each
  search query (~5 tokens) cost a tiny fraction of a cent; 10,000 searches is about $0.001. Pay per call, **$0 idle**.
- Index: one 94 KB JSON file in S3 (`search/embeddings.json`), effectively free. No vector database, no OpenSearch.
- New resources: 1 Lambda (`bhavs-api-search`), 1 IAM role, 1 log group (14-day retention), 1 API route. **$0 idle.**

## Phase 6 (reliability and polish)
- CloudWatch dashboard `bhavs` + 8 alarms -> SNS email: inside CloudWatch's always-free allowance (3 dashboards, 10
  alarms; the account had none), so $0. If the allowance does not apply: $3.00 + 8 x $0.10 = **$3.80/month**.
- X-Ray active tracing on all Lambdas and the transcode state machine: first 100k traces/month free; idle traffic is
  ~750 traces/month (hourly compaction + weekly training), so $0.
- SNS email, EventBridge "training failed" rule, security headers (Vercel + CloudFront policy): $0.
- Load test (`make loadtest`, 20 users x 2 min, ~2,500 requests): < $0.01 per run.
- GitHub Actions CI: free for public repos.

## Idle cost (final review, 2026-11-10)
What keeps billing when nobody uses bhavs:

| Item | Size | Monthly |
|---|---|---|
| S3 HLS output (17 films, 4 renditions) | 9.2 GB | $0.21 |
| S3 source uploads (expire 30 days after upload, ~2026-12-09) | 2.3 GB | $0.05 until then |
| ECR images (transcode + train, lifecycle keeps 3 each) | <= 1.7 GB | <= $0.17 |
| Hourly compaction run (~4 S3 requests when idle; no Athena) | 720 runs | ~$0.01 |
| Weekly training on Fargate Spot | 4 runs | ~$0.01 |
| DynamoDB storage, CloudWatch logs (14-day retention), SSM, Glue, Budgets, Cognito (2 users, Essentials) | < 1 MB each | $0 |
| CloudWatch dashboard + alarms | 1 + 8 | $0 (free allowance), else $3.80 |
| **Total** | | **~$0.45/month (~$0.015/day)**, ~$4.25/month without the CloudWatch free allowance |

To stop even that: `make destroy-app` (removes all compute, the dashboard and alarms; keeps data) and, for everything,
`make destroy-persistent`.
