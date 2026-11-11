# bhavs

A small Netflix-style streaming platform on AWS, built as a learning and portfolio project. You sign in, browse 17
open-licence Blender films in personalised rows, search by describing a film ("a lonely dragon"), and watch with
adaptive-bitrate HLS that resumes where you stopped. Behind it: a serverless video pipeline, a playback-analytics lake,
a recommender benchmarked on MovieLens, hybrid semantic search, and CloudWatch monitoring. Idle cost is about
$0.45/month.

**Live:** https://bhavs.vercel.app (sign-up needs an email confirmation code). Architecture: [docs/architecture.md](docs/architecture.md).
Costs: [COSTS.md](COSTS.md). ML results: [ml/RESULTS.md](ml/RESULTS.md). Search eval: [ml/SEARCH_EVAL.md](ml/SEARCH_EVAL.md).

## 1. What it does
- **Watch:** Cognito sign-up/sign-in; browse rows (Continue watching, Top picks, Because you watched X, genres); a
  player that switches between 360p and 1080p with your bandwidth and resumes where you left off.
- **Upload -> stream automatically:** drop a film in S3 and Step Functions transcodes it on Fargate into a 4-rung HLS
  ladder with poster and thumbnails, then marks it READY. Streams are protected by short-lived signed URLs.
- **Learn from viewing:** playback events flow to an S3 data lake, are compacted hourly to Parquet, and power an
  admin analytics page (views, watch %, drop-off, bitrates) and a weekly recommender training job.

## 2. Tools and libraries, and why
| Tool | Why |
|---|---|
| **Terraform** (3 stacks, S3 state with native locking) | Everything is code; the compute stack can be destroyed and rebuilt without touching data. |
| **AWS Lambda (Python 3.12, arm64)** + **API Gateway HTTP API** | Pay per request, $0 idle; arm64 is ~20% cheaper. HTTP API is cheaper than REST API and has a built-in JWT authorizer. |
| **Amazon Cognito** | Managed sign-up, email confirmation and JWTs; free at this scale. |
| **DynamoDB** (on-demand) | Key-value access patterns (title by id, a user's history); no servers, no idle cost. |
| **S3 + CloudFront** (+ CloudFront Function, KeyValueStore) | Cheap storage and global caching; a tiny edge function checks the stream token on every request. |
| **ffmpeg on ECS Fargate (Spot, ARM64)** + **Step Functions** | MediaConvert is blocked in this account; Spot is ~70% cheaper, and Step Functions gives retry-on-demand and failure handling without code. |
| **SQS -> Lambda -> S3 -> Athena + Glue** | Firehose is blocked here; this is the do-it-yourself equivalent. Athena bills per query, so an idle lake costs nothing. |
| **NumPy, SciPy, PyTorch (Apple `mps` locally)** | ALS written from scratch in NumPy to understand it; the two-tower model in PyTorch, trained on the Mac GPU. |
| **Amazon Bedrock: Titan Text Embeddings V2** | Embeddings by API call, no model hosting; a fraction of a cent for the whole catalogue. |
| **Next.js 16 (App Router) on Vercel** + **hls.js** | Server components keep tokens server-side (httpOnly cookies, a proxy for API calls); hls.js does ABR in browsers without native HLS. |
| **CloudWatch, X-Ray, SNS** | Dashboard, alarms emailed to you, request traces; inside the free allowance. |
| **pytest + moto, Playwright, Locust, ruff, GitHub Actions** | Unit tests with faked AWS, browser E2E, load testing, linting, CI. |

## 3. File structure
```
.env.example                  placeholder settings (copy to .env, never commit .env)
.github/workflows/ci.yml      CI: ruff + pytest, web lint/typecheck/build + signed-out E2E, terraform fmt/validate
.gitignore                    keeps secrets, data, builds and test output out of git
COSTS.md                      every estimate, measured cost, the Athena cost incident, and idle cost
Makefile                      all commands (make help)
README.md                     this file
films.yaml                    the 17 films: metadata, licences, verified download sources
pytest.ini / ruff.toml        test paths / lint settings
requirements.txt              Python packages for scripts and tests
docs/ACCESS.md                Phase 0 account checks and the fallbacks for blocked services
docs/architecture.md          architecture diagram and design reasons

infra/bootstrap/main.tf       Terraform state bucket (versioned, encrypted)
infra/persistent/main.tf      persistent stack: providers and remote state
infra/persistent/variables.tf budget email, budget thresholds, web origins
infra/persistent/terraform.tfvars.example  placeholder for the budget email
infra/persistent/budget.tf    account-wide AWS Budget with $50/$80/$100 alerts
infra/persistent/cognito.tf   user pool, web app client, admin group
infra/persistent/dynamodb.tf  titles, users, watch_history, recommendations tables
infra/persistent/storage.tf   source/output/analytics buckets, ECR repos, lifecycle rules, EventBridge notifications
infra/persistent/cdn.tf       CloudFront distribution, OAC, token function, KeyValueStore, security/CORS headers
infra/persistent/cdn/viewer_request.js  CloudFront Function that verifies stream tokens
infra/persistent/outputs.tf   ids and ARNs the app stack reads
infra/app/main.tf             app stack: providers, remote state, shared settings
infra/app/api.tf              HTTP API, JWT authorizer, throttling, the 9 API Lambdas with one IAM role each
infra/app/pipeline.tf         transcode pipeline: EventBridge, Lambdas, Step Functions, Fargate task, DLQ
infra/app/analytics.tf        events queue, batch + compaction Lambdas, Glue tables, Athena workgroup, saved queries
infra/app/ml.tf               training task definition, roles, weekly schedule
infra/app/observability.tf    dashboard, 8 alarms, SNS topic, training-failure rule, X-Ray permissions

services/src/shared/common.py       DynamoDB helpers, JSON responses, JWT claims
services/src/shared/tokens.py       stream token signing (HMAC-SHA256)
services/src/shared/embed.py        Bedrock Titan embedding call and indexed text
services/src/shared/textsearch.py   BM25 keyword scoring (pure Python)
services/src/api/titles_list.py     GET /titles
services/src/api/titles_get.py      GET /titles/{id}
services/src/api/me.py              GET /me (who am I, admin?)
services/src/api/continue_watching.py  GET /me/continue-watching
services/src/api/recommendations.py GET /me/recommendations (personal rows, cold-start fallback)
services/src/api/stream_token.py    GET /titles/{id}/stream (signed playback URL)
services/src/api/events.py          POST /events (resume position + analytics event)
services/src/api/search.py          GET /search (hybrid keyword + meaning search)
services/src/api/admin_analytics.py GET /admin/analytics (admins only)
services/src/pipeline/start_transcode.py     S3 upload -> start the state machine
services/src/pipeline/transcode_complete.py  mark READY with renditions from manifest.json
services/src/pipeline/transcode_fail.py      mark FAILED, send to DLQ
services/src/analytics/events_batch.py       SQS batch -> gzip JSONL in S3
services/src/analytics/compact.py            hourly JSONL -> Parquet, then rebuild the report
services/src/analytics/sql/*.sql             the 5 report queries (views, watch %, drop-off, bitrates, totals)
services/transcode/transcode.py     ffmpeg HLS ladder, poster, thumbnail sprite, upload
services/transcode/Dockerfile       ARM64 Alpine ffmpeg image
services/tests/conftest.py          moto fixtures (fake DynamoDB/S3)
services/tests/test_api.py          API handlers
services/tests/test_pipeline.py     transcode start/complete/fail, stream tokens
services/tests/test_transcode.py    ladder logic + a real ffmpeg run on a synthetic clip
services/tests/test_cdn_function.py runs the real CloudFront JS in node against Python-signed tokens
services/tests/test_analytics.py    event batching, partitions, admin endpoint
services/tests/test_compact.py      compaction + report rebuild with a fake Athena (incl. cost regression guard)
services/tests/test_search.py       search ranking, BM25, Bedrock request shape

scripts/check_access.sh       Phase 0: checks every AWS service bhavs needs
scripts/fetch_films.sh        verifies (and downloads) the open films from Wikimedia Commons
scripts/record_sources.py     writes verified sources into films.yaml
scripts/seed_titles.py        loads films.yaml into DynamoDB
scripts/ingest/ingest.py      matches local files to titles, estimates cost, uploads (starts the pipeline)
scripts/ingest/media.py       filename matching and ffprobe helpers
scripts/transcode_local.py    free fallback: transcode on the Mac and publish
scripts/build_transcode.sh    build + push the transcode image
scripts/build_train.sh        build + push the training image
scripts/train_cloud.sh        run the training job once on Fargate
scripts/embed_titles.py       build the search index (Titan vectors + keyword text) in S3
scripts/analytics_refresh.sh  compact now and rebuild the admin report
scripts/simulate_users/model.py     seeded model of synthetic viewers (tastes, times of day, networks)
scripts/simulate_users/simulate.py  write/purge ~200 SYNTHETIC users and their events
scripts/rotate_stream_key.sh  rotate the stream HMAC key (SSM + KeyValueStore)
scripts/make_admin.sh         add a user to the admin group
scripts/test_*.py             tests for ingest matching, sources, seeding, simulator

ml/bhavs_rec/data.py          MovieLens loading, temporal leave-last-out split
ml/bhavs_rec/metrics.py       full-ranking recall@10 / NDCG@10
ml/bhavs_rec/popularity.py    popularity baseline
ml/bhavs_rec/als.py           implicit ALS from scratch (NumPy)
ml/bhavs_rec/two_tower.py     two-tower model (PyTorch, mps/cpu)
ml/bhavs_rec/bhavs_data.py    bhavs watch history -> implicit feedback
ml/bhavs_rec/rows.py          builds "Top picks" / "Because you watched" / popular rows
ml/benchmark.py               runs the MovieLens benchmark grid
ml/make_results.py            writes RESULTS.md and best_model.txt
ml/train.py                   production training: DynamoDB -> model -> recommendation rows
ml/search_eval.py / .yaml     search evaluation script and labelled queries (dev/test split)
ml/RESULTS.md / SEARCH_EVAL.md  generated results
ml/best_model.txt             model the production job uses
ml/artifacts_ml1m.log         log of the ml-1m benchmark run
ml/Dockerfile                 training image (CPU PyTorch, ARM64)
ml/requirements.txt           ML packages
ml/tests/                     split, metrics and row-building tests

loadtest/locustfile.py        Locust load test against the real API
loadtest/requirements.txt     Locust

web/src/proxy.ts              per-request Content-Security-Policy nonce
web/next.config.ts            security headers
web/src/app/page.tsx          browse page (rows)
web/src/app/title/[id]/page.tsx  title details
web/src/app/watch/[id]/page.tsx  player page with resume
web/src/app/search/page.tsx   search results
web/src/app/admin/page.tsx    analytics (admins only)
web/src/app/login|signup/page.tsx  auth pages
web/src/app/api/auth/*        sign-up, confirm, login, logout route handlers (set httpOnly cookies)
web/src/app/api/session/refresh/route.ts  refreshes tokens, then returns to the page
web/src/app/api/bhavs/[...path]/route.ts  allow-listed proxy from the browser to the API
web/src/components/*.tsx      Header (with search), Row, TitleCard, Poster, Player (hls.js), AuthForm, SignOutButton
web/src/lib/*.ts              Cognito calls, session cookies, server API client, types, event sender
web/e2e/public.spec.ts        signed-out E2E: pages, redirects, security headers, proxy guard
web/e2e/journey.spec.ts       full E2E: login -> browse -> search -> play -> resume
web/playwright.config.ts      Playwright projects
web/vercel.json               Vercel region (Cleveland, next to us-east-2)
```

## 4. Setup
```bash
conda create -n bhavs python=3.12 -y
conda activate bhavs
pip install -r requirements.txt
pip install -r ml/requirements.txt          # numpy, scipy, torch (uses the Apple GPU via mps)
pip install -r loadtest/requirements.txt    # only for the load test
cd web && npm install && npx playwright install chromium && cd ..
cp .env.example .env                        # fill in your values (never commit .env)
aws login --profile sky                     # AWS credentials for us-east-2
```
First deploy (each `make deploy-*` shows the plan and asks before applying):
```bash
make check-access && make bootstrap && make deploy-persistent && make deploy-app
make stream-key && make seed-titles && make build-transcode && make build-train
make fetch-films DOWNLOAD=1 && make ingest   # downloads and transcodes the films (~$0.10-$0.40)
make embed                                   # search index
```

## 5. How to run
- **Website:** https://bhavs.vercel.app, or locally: `cd web && npm run dev` (needs `web/.env.local` from `web/.env.example`).
- **Tests:** `make test` (81 Python tests, AWS faked with moto), `make lint`, `cd web && npm run lint`.
- **E2E:** `make e2e URL=https://bhavs.vercel.app` (signed out, no secrets) and `make e2e-journey` (test account from .env).
- **Load test:** `make loadtest` (20 users for 2 minutes; `USERS=60` shows the API throttle returning 429s).
- **ML:** `make ml-benchmark DATASET=ml-1m` (needs MovieLens in `ml/data/`), `make train` (local), `make train-cloud`.
- **Search eval:** `make search-eval`. **Analytics now:** `make analytics-refresh`. **Synthetic viewers:** `make simulate`.
- **Monitoring:** `terraform -chdir=infra/app output -raw dashboard_url`.
- **Tear down:** `make destroy-app` (compute only, data kept); `make destroy-persistent` (everything, asks for a phrase).

## 6. How it was built
0. **Account check:** found MediaConvert, Firehose, Kinesis and cost-allocation tags blocked by the Organization; picked fallbacks.
1. **Foundation:** Terraform state, Cognito, DynamoDB, API Gateway + Lambdas, Next.js on Vercel with cookie auth.
2. **Video pipeline:** ffmpeg container on Fargate Spot ARM64, Step Functions with on-demand retry and DLQ, CloudFront
   with a token-checking CloudFront Function. Measured: Big Buck Bunny (10.6 min) transcoded in 7m42s for ~$0.02.
3. **Player and analytics:** hls.js with ABR and resume; events -> SQS -> S3 -> hourly Parquet -> Athena -> admin page;
   a seeded simulator of 200 synthetic viewers, clearly labelled.
4. **Recommendations:** popularity vs ALS vs two-tower on MovieLens with a temporal split; weekly Fargate training job
   writing personal rows.
5. **Search:** Titan embeddings, then a hybrid with BM25 after an eval showed vector-only missed exact-word queries.
6. **Reliability:** dashboard, alarms, X-Ray, CSP + security headers, Playwright E2E, Locust, CI, more unit tests, and
   a cost review that found and fixed an Athena request-cost bug.

## 7. Key concepts (interview notes)
- **Adaptive bitrate (HLS):** the film is cut into 6-second segments at 4 qualities; the player measures bandwidth and
  picks a quality per segment. Measured on the live site: 360p -> 1080p in ~10 s, and down to 360p within ~1 s of
  throttling to 1 Mbit/s.
- **Signed URLs at the edge:** HMAC(secret, expiry:title) in the path; a CloudFront Function recomputes it in under a
  millisecond, so private video is still cached and served by the CDN.
- **Serverless trade-offs:** $0 idle, but you pay per request. The Athena incident (COSTS.md) is the concrete example:
  ~530k S3 LIST requests from an over-wide partition projection, found by reading Cost Explorer by usage type.
- **Event pipeline and data lake:** at-least-once delivery (SQS + DLQ), raw JSONL partitioned by arrival hour,
  idempotent compaction to Parquet (columnar, compressed), query-per-use with Athena.
- **Recommender evaluation:** implicit feedback, temporal leave-last-out (no peeking at the future), full ranking (no
  sampled negatives), tuning on validation and scoring the test once, and always comparing against popularity.
- **ALS vs two-tower:** matrix factorisation solved in closed form per user/item, vs two neural networks trained with
  in-batch softmax (with logQ correction for popular items). On ML-1M both beat popularity ~2x and are within each
  other's confidence interval.
- **Hybrid search:** embeddings capture meaning, BM25 captures exact words; reciprocal rank fusion combines ranks
  without comparing incompatible scores. Evaluated with a dev/test split so the one tuned value was not fitted to the test.
- **Least privilege:** one IAM role per Lambda with only its table/prefix/model; secrets in SSM, never in code or state.
- **Defence in depth on the web:** httpOnly cookies, an allow-listed proxy, nonce-based CSP with `strict-dynamic`,
  `frame-ancestors 'none'`, HSTS.

## Results
**MovieLens ml-1m** (6,034 users, temporal leave-last-out, full ranking; [ml/RESULTS.md](ml/RESULTS.md)):

| Model | recall@10 | NDCG@10 |
|---|---|---|
| Popularity (baseline) | 0.0426 | 0.0205 |
| ALS | 0.0776 | 0.0397 |
| Two-tower | 0.0843 (±0.0016 over 3 seeds) | 0.0418 |

Both learned models beat popularity by about 2x. The difference between ALS and the two-tower is within the 95%
confidence interval, so neither is claimed to be better; production uses the two-tower as a tie-break.

**Search** (27 held-out queries on the bhavs catalogue; [ml/SEARCH_EVAL.md](ml/SEARCH_EVAL.md)): hybrid hit@3 0.955 /
MRR 0.864 vs vector-only 0.636 / 0.492, with the same 4/5 "should return nothing" queries correctly empty. Small,
self-labelled set: a sanity check, not a benchmark.

**End-to-end (Playwright, production, 2026-11-10):** the full journey passed (sign in, browse, search "a lonely
dragon", play Sintel through the token-checked CDN, pause, resume from the saved position), and all 9 signed-out
checks (redirects, admin hidden, security headers, CSP nonce, API proxy guard) passed, locally, in CI and on production.

**Load test** (Locust, 20 simulated viewers for 2 minutes against the real API, 2026-11-10; `make loadtest`):

| Endpoint | Requests | p50 | p95 | p99 | Max |
|---|---|---|---|---|---|
| `GET /titles` | 753 | 72 ms | 100 ms | 250 ms | 1.1 s |
| `GET /me/continue-watching` | 533 | 74 ms | 95 ms | 140 ms | 0.9 s |
| `GET /me/recommendations` | 533 | 160 ms | 200 ms | 330 ms | 1.3 s |
| `GET /search` | 323 | 65 ms | 170 ms | 330 ms | 2.4 s |
| `GET /titles/{id}` | 324 | 66 ms | 88 ms | 200 ms | 0.2 s |
| `GET /titles/{id}/stream` | 157 | 64 ms | 84 ms | 250 ms | 1.4 s |
| **All** | **2,623** | **74 ms** | **170 ms** | **250 ms** | **2.4 s** |

0 failures at ~22 requests/s (just under the API's 25 rps throttle). **The max values are Lambda cold starts**: the
Lambda logs show 7 cold starts in 2,625 invocations, when a burst needed a new instance of a function. Starting the
Python runtime took ~180-270 ms. Most of the delay is the first request on the new instance, which creates the AWS SDK
clients and opens connections; for search it also loads the index from S3 and makes the first Bedrock call (2.05 s in
total inside Lambda, 2.4 s as Locust measured it). Warm requests spend 13-29 ms in the handler (114 ms for
recommendations, which reads two tables). Provisioned concurrency would remove cold starts but bills ~$3+/month per
function even when idle, which this project avoids.

**Video:** 17 films, 4 renditions each (9.2 GB), all READY; Big Buck Bunny transcode 7m42s on Fargate Spot (~$0.02).
**Cost so far:** ~$2.80 of usage for bhavs (COSTS.md), idle ~$0.45/month.

## Demo checklist (screen recording)
1. Sign in at bhavs.vercel.app; show the rows (Continue watching, Top picks, Because you watched X).
2. Search "a lonely dragon" -> Sintel; "stubborn fence" -> Llama Drama; "cooking pasta recipe" -> nothing.
3. Play a film; open the quality menu; in DevTools throttle to "Fast 3G" and watch it drop to 360p, then recover.
4. Stop mid-film, go back to browse: it is in Continue watching; reopen it: "Resuming from m:ss".
5. DevTools Network: a segment URL contains `/t/<expiry>-<signature>/`; change one character -> 403 from CloudFront.
6. Admin account: the analytics page (views, watch %, drop-off heatmap, bitrate mix) with the synthetic-data banner.
7. AWS console: upload a film to the source bucket -> the Step Functions execution graph -> title turns READY.
8. CloudWatch dashboard `bhavs` and an X-Ray trace of a search request; `make loadtest` output with p50/p95.
9. GitHub Actions run passing; `ml/RESULTS.md` table.

## Credits and licences
- Films: Blender Foundation / Blender Studio open movies under Creative Commons (each film's licence and credit are in
  `films.yaml` and shown on its page). Downloaded from Wikimedia Commons.
- MovieLens data: F. Maxwell Harper and Joseph A. Konstan, *The MovieLens Datasets: History and Context*, ACM TiiS 5(4),
  2015, from [GroupLens](https://grouplens.org/datasets/movielens/). Used for research only and not redistributed
  (`ml/data/` is gitignored).
