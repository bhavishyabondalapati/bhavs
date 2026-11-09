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
