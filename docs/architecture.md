# bhavs architecture

```mermaid
flowchart LR
  subgraph Vercel["Vercel: Next.js 16"]
    UI[Browser] -->|httpOnly cookies| BFF[Route handlers<br/>auth + allow-listed API proxy<br/>CSP nonce per request]
  end
  BFF -->|sign up / sign in| COG[(Cognito user pool)]
  BFF -->|Bearer ID token| APIGW[API Gateway HTTP API<br/>JWT authorizer, 25 rps throttle]

  subgraph API["API (app stack): 9 Lambdas, one IAM role each"]
    APIGW --> L[titles, me, continue-watching,<br/>recommendations, events, admin]
    APIGW --> TOK[stream_token<br/>HMAC key from SSM]
    APIGW --> SRCH[search: BM25 + Titan cosine, RRF]
  end
  L --> DDB[(DynamoDB<br/>titles, users, watch_history,<br/>recommendations)]
  SRCH -->|embed query| BR[Bedrock<br/>Titan Text Embeddings V2]
  SRCH -->|vectors + text| IDX[(S3 search/embeddings.json)]

  subgraph Video["Video pipeline"]
    SRC[(S3 source)] -->|Object Created| EB[EventBridge] --> START[start Lambda] --> SFN{{Step Functions}}
    SFN -->|try 1| SPOT[Fargate Spot ARM64<br/>ffmpeg: 4-rung HLS ladder]
    SFN -.->|retry| OD[Fargate on-demand ARM64]
    SPOT & OD --> OUT[(S3 output<br/>private, OAC only)]
    SFN -->|ok| READY[mark READY] --> DDB
    SFN -->|both failed| FAIL[mark FAILED] --> DLQ[(SQS DLQ)]
  end

  subgraph Stream["Streaming"]
    PLAYER[hls.js player] -->|/t/exp-hmac/titles/id/...| CF[CloudFront]
    CF --> FN[CloudFront Function<br/>checks token via KeyValueStore] --> OUT
  end
  TOK -.->|signed URL| PLAYER

  subgraph Analytics["Analytics"]
    L -->|play/pause/heartbeat| Q[SQS events] --> BATCH[batch Lambda] --> RAW[(S3 raw JSONL<br/>dt/hour)]
    SCHED[Scheduler hourly] --> COMP[compact Lambda] -->|CTAS| PQ[(S3 Parquet)]
    COMP -->|5 report queries, last 30 days| ATH[Athena + Glue<br/>partition projection] --> REP[(reports/analytics.json)]
  end

  subgraph ML["Recommendations"]
    WEEK[Scheduler weekly] --> TRAIN[Fargate Spot ARM64<br/>two-tower / ALS] -->|rows| DDB
  end

  subgraph Ops["Observability"]
    CW[CloudWatch dashboard<br/>+ 8 alarms] --> SNS[SNS email]
    XR[X-Ray traces<br/>Lambdas + state machine]
  end
```

## Why these choices
- **Token in the URL path, not a header or cookie.** The web app (vercel.app) and CloudFront (cloudfront.net) are
  different sites: third-party cookies are blocked and custom headers would trigger CORS preflight. HLS playlists use
  *relative* URLs, so every playlist and segment automatically inherits `/t/<token>/`. The function strips the token
  before the cache lookup, so all viewers share one cached copy.
- **Token = HMAC-SHA256(secret, "<expiry>:<title id>").** It is bound to one title and expires (4 h). The secret is
  in SSM (for the minting Lambda) and a CloudFront KeyValueStore (for the verifying function), never in git or
  Terraform state. `scripts/rotate_stream_key.sh` rotates both.
- **MediaConvert, Firehose and Kinesis are blocked by an Organization SCP**, so: ffmpeg on Fargate (Spot first, one
  on-demand retry), and SQS -> batch Lambda -> S3 -> Athena instead of Firehose. See docs/ACCESS.md.
- **Training on Fargate, not SageMaker**: the account's SageMaker training quota is 0. The same container would run as
  a SageMaker training job if the quota is ever approved.
- **No vector database**: ~20 titles fit in one JSON file; ranking them in plain Python takes microseconds.
- **Three Terraform stacks**: `bootstrap` (state bucket), `persistent` (data, auth, CDN; kept), `app` (compute; can be
  destroyed and recreated without losing data).
