# bhavs cost tracking

Budget: ~$100 AWS credits, target well under. Alerts at $50 / $80 / $100 actual usage (credits excluded).

| Phase | What bills | Estimated cost | Actual |
|---|---|---|---|
| Setup / Phase 0 | nothing (read-only CLI calls, 2 tiny Bedrock embedding calls) | ~$0.00 | |
| Phase 1 | DynamoDB on-demand, Lambda, API GW, Cognito (all free tier / pennies) | <$1 | |
| Phase 2 | MediaConvert (main cost), S3 storage | TBD from your files | |
| Phase 3 | Firehose, Athena, S3 | few $ | |
| Phase 4 | SageMaker CPU training job | cents per run | |
| Phase 5 | Bedrock embeddings | pennies | |
| Phase 6 | CloudWatch dashboard ($3/mo), alarms, load test | few $ | |

Idle cost right now: $0.
