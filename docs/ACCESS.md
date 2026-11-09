# Phase 0: account access report (account in us-east-2, profile `sky`)

Run `make check-access` to reproduce. Blocks below are **explicit denies from an Organization
Service Control Policy**, so they cannot be fixed from inside this account.

| Service | Status | Decision |
|---|---|---|
| MediaConvert | BLOCKED (SCP) | Fargate ffmpeg task (or local ffmpeg) |
| Kinesis Firehose | BLOCKED (SCP) | SQS -> batch Lambda -> S3, Athena converts to Parquet |
| Kinesis Data Streams | BLOCKED (SCP) | same as above |
| SageMaker training, CPU | quota = 0 (adjustable) | request increase; Fargate fallback |
| SageMaker training, GPU | ml.g5.xlarge quota = 1 | expensive, last resort |
| Bedrock embeddings | OK: Titan Text Embeddings v2 | Phase 5 as planned |
| Glue, Athena, S3, Cognito, DynamoDB, API GW, Lambda, EventBridge, Scheduler, CloudFront, SSM, X-Ray, CloudWatch, Budgets, Cost Explorer | OK | as planned |
| ECR, ECS/Fargate, SQS, Step Functions, Batch, Lambda layers | OK | used by fallbacks |
| Route 53 / ACM | OK but unused | Option B: *.cloudfront.net, no custom domain |
