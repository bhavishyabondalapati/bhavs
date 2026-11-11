# Service constraints and fallbacks

Before building, `make check-access` tested every AWS service the design needed (run it to
reproduce in your own account). Some services were not available in the account used for this
project (blocked by an AWS Organizations service control policy, or a quota of zero), so the
design uses a fallback for each. These constraints explain several architecture choices.

| Service | Status | Decision |
|---|---|---|
| MediaConvert | BLOCKED (SCP) | Fargate ffmpeg task (or local ffmpeg) |
| Kinesis Firehose | BLOCKED (SCP) | SQS -> batch Lambda -> S3, Athena converts to Parquet |
| Kinesis Data Streams | BLOCKED (SCP) | same as above |
| SageMaker training, CPU | quota = 0 (adjustable) | Fargate fallback |
| SageMaker training, GPU | ml.g5.xlarge quota = 1 | expensive, last resort |
| Bedrock embeddings | OK: Titan Text Embeddings v2 | used for search as planned |
| Glue, Athena, S3, Cognito, DynamoDB, API GW, Lambda, EventBridge, Scheduler, CloudFront, SSM, X-Ray, CloudWatch, Budgets, Cost Explorer | OK | as planned |
| ECR, ECS/Fargate, SQS, Step Functions, Batch, Lambda layers | OK | used by fallbacks |
| Route 53 / ACM | OK but unused | Option B: *.cloudfront.net, no custom domain |

## Fallbacks chosen
- Transcode: ffmpeg on Fargate Spot (ARM64, verified supported), on-demand retry, `make transcode-local` as free fallback.
- Events: POST /events -> SQS -> batch Lambda -> S3 -> hourly Athena INSERT into partitioned Parquet.
- SageMaker: the CPU training quota was 0, so the training container runs on Fargate instead. No GPU instances.
- Streaming auth: Option B (path token + CloudFront Function) on the default cloudfront.net domain. No Route 53 / ACM.
- `download.blender.org` is behind a bot challenge, so films are fetched from Wikimedia Commons instead (see scripts/fetch_films.sh).
