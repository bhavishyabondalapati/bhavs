# bhavs cost tracking

Budget: ~$100 AWS credits, target well under. Alerts at $50 / $80 / $100 actual usage (credits excluded).

| Phase | What bills | Estimated cost | Actual |
|---|---|---|---|
| Setup / Phase 0 | nothing (read-only CLI calls, 2 tiny Bedrock embedding calls) | ~$0.00 | |
| Phase 1 | DynamoDB on-demand, Lambda, API GW, Cognito Essentials, Budgets (first 2 budgets free), CloudWatch logs | <$0.50 for the whole phase; ~$0 idle | |
| Phase 2 | MediaConvert (main cost), S3 storage | TBD from your files | |
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
