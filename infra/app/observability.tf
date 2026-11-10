# Phase 6 observability: one CloudWatch dashboard, 8 alarms -> SNS email, a "training job failed" EventBridge rule,
# and X-Ray tracing on every Lambda + the transcode state machine.
#
# Cost (us-east-2): CloudWatch always-free covers 3 dashboards and 10 standard alarms; this stack adds 1 dashboard and
# 8 alarms, and the account had none before, so $0. Outside the free allowance it would be $3.00/month (dashboard) +
# 8 x $0.10 = $0.80/month (alarms). SNS email: first 1,000/month free. EventBridge rules for AWS service events: free.
# X-Ray: first 100,000 traces/month free, then $5 per million.

variable "alert_email" {
  description = "Email for alarm notifications (TF_VAR_alert_email, set from .env by the Makefile). Empty = no subscription."
  type        = string
  default     = ""
}

locals {
  api_fn_names = [for k in keys(local.functions) : "bhavs-api-${k}"]
  # Every Lambda role, so all of them can write X-Ray traces.
  lambda_roles = merge(
    { for k, r in aws_iam_role.fn : "api-${k}" => r.name },
    { for k, r in aws_iam_role.pipeline : "pipeline-${k}" => r.name },
    {
      start        = aws_iam_role.start.name
      events_batch = aws_iam_role.events_batch.name
      compact      = aws_iam_role.compact.name
      sfn          = aws_iam_role.sfn.name
    },
  )
  cdn_id = local.p.cdn_distribution_id
  tables = [local.p.titles_table, local.p.users_table, local.p.watch_history_table, local.p.recommendations_table]
}

# ---------- X-Ray ----------
# X-Ray write actions do not support resource-level permissions, so "*" is the narrowest possible resource.
resource "aws_iam_policy" "xray_write" {
  name = "bhavs-xray-write"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "xray" {
  for_each   = local.lambda_roles
  role       = each.value
  policy_arn = aws_iam_policy.xray_write.arn
}

# ---------- Alerts ----------
resource "aws_sns_topic" "alerts" {
  name = "bhavs-alerts"
}

data "aws_caller_identity" "obs" {}

resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "CloudWatchAlarms"
        Effect    = "Allow"
        Principal = { Service = "cloudwatch.amazonaws.com" }
        Action    = "sns:Publish"
        Resource  = aws_sns_topic.alerts.arn
        Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.obs.account_id } }
      },
      {
        Sid       = "EventBridgeTrainFailed"
        Effect    = "Allow"
        Principal = { Service = "events.amazonaws.com" }
        Action    = "sns:Publish"
        Resource  = aws_sns_topic.alerts.arn
        Condition = { ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.train_failed.arn } }
      },
    ]
  })
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

locals {
  alarms = {
    "api-5xx" = {
      desc      = "API returned 5 or more 5xx responses in 5 minutes"
      ns        = "AWS/ApiGateway", metric = "5xx", stat = "Sum", dims = { ApiId = aws_apigatewayv2_api.http.id }
      threshold = 5, op = "GreaterThanOrEqualToThreshold", periods = 1
    }
    "api-latency-p95" = {
      desc      = "API p95 latency above 2 s for 15 minutes"
      ns        = "AWS/ApiGateway", metric = "Latency", stat = "p95", dims = { ApiId = aws_apigatewayv2_api.http.id }
      threshold = 2000, op = "GreaterThanThreshold", periods = 3
    }
    "lambda-errors" = {
      desc      = "5 or more Lambda errors (all functions) in 5 minutes"
      ns        = "AWS/Lambda", metric = "Errors", stat = "Sum", dims = {}
      threshold = 5, op = "GreaterThanOrEqualToThreshold", periods = 1
    }
    "lambda-throttles" = {
      desc      = "Any Lambda throttled (account concurrency exhausted)"
      ns        = "AWS/Lambda", metric = "Throttles", stat = "Sum", dims = {}
      threshold = 1, op = "GreaterThanOrEqualToThreshold", periods = 1
    }
    "transcode-failed" = {
      desc      = "A transcode workflow failed (both Spot and on-demand attempts)"
      ns        = "AWS/States", metric = "ExecutionsFailed", stat = "Sum", dims = { StateMachineArn = aws_sfn_state_machine.transcode.arn }
      threshold = 1, op = "GreaterThanOrEqualToThreshold", periods = 1
    }
    "transcode-dlq" = {
      desc      = "Failed transcode messages are waiting in the DLQ"
      ns        = "AWS/SQS", metric = "ApproximateNumberOfMessagesVisible", stat = "Maximum", dims = { QueueName = aws_sqs_queue.dlq.name }
      threshold = 1, op = "GreaterThanOrEqualToThreshold", periods = 1
    }
    "events-dlq" = {
      desc      = "Playback events could not be written to S3 and are in the DLQ"
      ns        = "AWS/SQS", metric = "ApproximateNumberOfMessagesVisible", stat = "Maximum", dims = { QueueName = aws_sqs_queue.events_dlq.name }
      threshold = 1, op = "GreaterThanOrEqualToThreshold", periods = 1
    }
    "events-backlog" = {
      desc      = "Oldest playback event waiting more than 15 minutes (batch Lambda stuck)"
      ns        = "AWS/SQS", metric = "ApproximateAgeOfOldestMessage", stat = "Maximum", dims = { QueueName = aws_sqs_queue.events.name }
      threshold = 900, op = "GreaterThanThreshold", periods = 1
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "a" {
  for_each            = local.alarms
  alarm_name          = "bhavs-${each.key}"
  alarm_description   = each.value.desc
  namespace           = each.value.ns
  metric_name         = each.value.metric
  dimensions          = each.value.dims
  statistic           = startswith(each.value.stat, "p") ? null : each.value.stat
  extended_statistic  = startswith(each.value.stat, "p") ? each.value.stat : null
  period              = 300
  evaluation_periods  = each.value.periods
  threshold           = each.value.threshold
  comparison_operator = each.value.op
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# The weekly training job is an ECS task, not a Lambda: alert when it stops with a non-zero exit code.
resource "aws_cloudwatch_event_rule" "train_failed" {
  name        = "bhavs-train-failed"
  description = "Recommender training task stopped with a non-zero exit code"
  event_pattern = jsonencode({
    source        = ["aws.ecs"]
    "detail-type" = ["ECS Task State Change"]
    detail = {
      lastStatus = ["STOPPED"]
      group      = ["family:bhavs-train"]
      containers = { exitCode = [{ "anything-but" = 0 }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "train_failed" {
  rule = aws_cloudwatch_event_rule.train_failed.name
  arn  = aws_sns_topic.alerts.arn
  input_transformer {
    input_paths    = { task = "$.detail.taskArn", reason = "$.detail.stoppedReason" }
    input_template = "\"bhavs training task <task> failed: <reason>. Logs: aws logs tail /ecs/bhavs-train --since 1h\""
  }
}

# ---------- Dashboard ----------
locals {
  r          = "us-east-2"
  fn_metrics = { for m in ["Invocations", "Errors"] : m => [for f in local.api_fn_names : ["AWS/Lambda", m, "FunctionName", f]] }
  dashboard = {
    widgets = [
      { type = "text", x = 0, y = 0, width = 24, height = 2, properties = { markdown = "# bhavs\nAPI, playback pipeline, analytics and search. Alarms email `bhavs-alerts`. Traces: X-Ray (Lambdas + transcode state machine). CloudFront metrics come from us-east-1 (global service)." } },
      { type = "alarm", x = 0, y = 2, width = 24, height = 3, properties = { title = "Alarms", alarms = [for a in aws_cloudwatch_metric_alarm.a : a.arn] } },

      { type = "metric", x = 0, y = 5, width = 8, height = 6, properties = { title = "API requests and errors (5 min)", region = local.r, stat = "Sum", period = 300, view = "timeSeries",
      metrics = [["AWS/ApiGateway", "Count", "ApiId", aws_apigatewayv2_api.http.id], [".", "4xx", ".", "."], [".", "5xx", ".", "."]] } },
      { type = "metric", x = 8, y = 5, width = 8, height = 6, properties = { title = "API latency (ms)", region = local.r, period = 300, view = "timeSeries",
      metrics = [["AWS/ApiGateway", "Latency", "ApiId", aws_apigatewayv2_api.http.id, { stat = "p50" }], ["...", { stat = "p95" }], ["...", { stat = "p99" }]] } },
      { type = "metric", x = 16, y = 5, width = 8, height = 6, properties = { title = "Search: Lambda p95 (ms) and Titan embedding latency", region = local.r, period = 300, view = "timeSeries",
      metrics = [["AWS/Lambda", "Duration", "FunctionName", "bhavs-api-search", { stat = "p95" }], ["AWS/Bedrock", "InvocationLatency", "ModelId", "amazon.titan-embed-text-v2:0", { stat = "p95" }]] } },

      { type = "metric", x = 0, y = 11, width = 12, height = 6, properties = { title = "API Lambda invocations", region = local.r, stat = "Sum", period = 300, view = "timeSeries", stacked = true, metrics = local.fn_metrics["Invocations"] } },
      { type = "metric", x = 12, y = 11, width = 12, height = 6, properties = { title = "API Lambda errors", region = local.r, stat = "Sum", period = 300, view = "timeSeries", metrics = local.fn_metrics["Errors"] } },

      { type = "metric", x = 0, y = 17, width = 8, height = 6, properties = { title = "Video pipeline (Step Functions)", region = local.r, stat = "Sum", period = 3600, view = "timeSeries",
      metrics = [["AWS/States", "ExecutionsStarted", "StateMachineArn", aws_sfn_state_machine.transcode.arn], [".", "ExecutionsSucceeded", ".", "."], [".", "ExecutionsFailed", ".", "."]] } },
      { type = "metric", x = 8, y = 17, width = 8, height = 6, properties = { title = "Playback events queue", region = local.r, period = 300, view = "timeSeries",
      metrics = [["AWS/SQS", "NumberOfMessagesSent", "QueueName", aws_sqs_queue.events.name, { stat = "Sum" }], [".", "ApproximateAgeOfOldestMessage", ".", ".", { stat = "Maximum", yAxis = "right" }], [".", "ApproximateNumberOfMessagesVisible", ".", aws_sqs_queue.events_dlq.name, { stat = "Maximum", label = "events DLQ" }], [".", ".", ".", aws_sqs_queue.dlq.name, { stat = "Maximum", label = "transcode DLQ" }]] } },
      { type = "metric", x = 16, y = 17, width = 8, height = 6, properties = { title = "DynamoDB consumed capacity", region = local.r, stat = "Sum", period = 300, view = "timeSeries",
      metrics = concat([for t in local.tables : ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", t]], [for t in local.tables : ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", t]]) } },

      { type = "metric", x = 0, y = 23, width = 8, height = 6, properties = { title = "CloudFront requests and bytes out", region = "us-east-1", stat = "Sum", period = 3600, view = "timeSeries",
      metrics = [["AWS/CloudFront", "Requests", "Region", "Global", "DistributionId", local.cdn_id], [".", "BytesDownloaded", ".", ".", ".", ".", { yAxis = "right" }]] } },
      { type = "metric", x = 8, y = 23, width = 8, height = 6, properties = { title = "CloudFront error rate (%) - 403 = rejected stream token", region = "us-east-1", stat = "Average", period = 3600, view = "timeSeries",
      metrics = [["AWS/CloudFront", "4xxErrorRate", "Region", "Global", "DistributionId", local.cdn_id], [".", "5xxErrorRate", ".", ".", ".", "."]] } },
      { type = "metric", x = 16, y = 23, width = 8, height = 6, properties = { title = "Token check (CloudFront Function)", region = "us-east-1", stat = "Sum", period = 3600, view = "timeSeries",
      metrics = [["AWS/CloudFront", "FunctionInvocations", "FunctionName", "bhavs-verify-token", "Region", "Global"], [".", "FunctionComputeUtilization", ".", ".", ".", ".", { stat = "Maximum", yAxis = "right" }]] } },
    ]
  }
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "bhavs"
  dashboard_body = jsonencode(local.dashboard)
}

output "dashboard_url" {
  value = "https://us-east-2.console.aws.amazon.com/cloudwatch/home?region=us-east-2#dashboards/dashboard/bhavs"
}

output "alerts_topic" { value = aws_sns_topic.alerts.arn }
