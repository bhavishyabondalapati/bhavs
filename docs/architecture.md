# bhavs architecture (through Phase 2)

```mermaid
flowchart LR
  subgraph Web["Vercel: Next.js"]
    UI[Browser] -->|httpOnly cookie| BFF[Next.js route handlers<br/>auth + allow-listed API proxy]
  end
  BFF -->|Bearer ID token| APIGW[API Gateway HTTP API<br/>Cognito JWT authorizer]
  BFF -->|sign up / in| COG[(Cognito user pool)]
  APIGW --> L[6+ API Lambdas<br/>one IAM role each]
  L --> DDB[(DynamoDB<br/>titles, users, watch_history, recommendations)]
  L -->|GET /titles/id/stream| TOK[stream_token Lambda<br/>HMAC key from SSM]

  subgraph Pipeline["Video pipeline (app stack)"]
    SRC[(S3 source bucket)] -->|Object Created| EB[EventBridge rule]
    EB --> START[start_transcode Lambda]
    START --> SFN{{Step Functions}}
    SFN -->|1st attempt| SPOT[Fargate Spot ARM64<br/>ffmpeg HLS ladder]
    SFN -.->|retry once on failure| OD[Fargate on-demand ARM64]
    SPOT --> OUT
    OD --> OUT[(S3 output bucket<br/>private, OAC only)]
    SFN -->|success| READY[transcode_complete Lambda<br/>title -> READY]
    SFN -->|both failed| FAIL[transcode_fail Lambda<br/>title -> FAILED]
    FAIL --> DLQ[(SQS DLQ)]
    READY --> DDB
    FAIL --> DDB
  end

  subgraph CDN["Streaming (persistent stack)"]
    PLAYER[Player / hls.js] -->|/t/&lt;exp&gt;-&lt;hmac&gt;/titles/id/master.m3u8| CF[CloudFront]
    CF --> FN[CloudFront Function<br/>verifies token via KeyValueStore]
    FN --> OUT
  end
  TOK -.->|signed URL| PLAYER
```

## Why these choices
- **Token in the URL path, not a header or cookie.** The web app (vercel.app) and CloudFront (cloudfront.net) are
  different sites: third-party cookies are blocked and custom headers would trigger CORS preflight. HLS playlists use
  *relative* URLs, so every playlist and segment automatically inherits `/t/<token>/`. The function strips the token
  before the cache lookup, so all viewers share one cached copy.
- **Token = HMAC-SHA256(secret, "<expiry>:<title id>").** It is bound to one title and expires (4 h). The secret is
  in SSM (for the minting Lambda) and a CloudFront KeyValueStore (for the verifying function), never in git or
  Terraform state. `scripts/rotate_stream_key.sh` rotates both.
- **MediaConvert and Firehose are blocked by an Organization SCP**, so: ffmpeg on Fargate (Spot first, one on-demand
  retry), and (Phase 3) SQS -> batch Lambda -> S3 -> Athena instead of Firehose. See docs/ACCESS.md.
- **Switching to signed cookies later** only touches `infra/persistent/cdn.tf`, the viewer-request function and the
  `stream_token` Lambda; the pipeline and player URLs do not change.
