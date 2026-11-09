# Events pipeline (Firehose is blocked by an SCP, so this is the equivalent):
#   POST /events -> SQS -> batch Lambda -> S3 raw/ (gzip JSONL, partitioned dt/hour)
#   hourly Scheduler -> compact Lambda -> Athena CTAS -> S3 parquet/ (partitioned dt/hour) -> cached admin report

locals {
  lake = local.p.analytics_bucket
}

# ---------- queues ----------
resource "aws_sqs_queue" "events_dlq" {
  name                      = "bhavs-events-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "events" {
  name                       = "bhavs-events"
  visibility_timeout_seconds = 120
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.events_dlq.arn
    maxReceiveCount     = 5
  })
}

# ---------- batch writer ----------
resource "aws_cloudwatch_log_group" "events_batch" {
  name              = "/aws/lambda/bhavs-events_batch"
  retention_in_days = 14
}

resource "aws_iam_role" "events_batch" {
  name               = "bhavs-analytics-events_batch"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}

data "aws_iam_policy_document" "events_batch" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.events_batch.arn}:*"]
  }
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.events.arn]
  }
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${local.p.analytics_bucket_arn}/raw/*"]
  }
}

resource "aws_iam_role_policy" "events_batch" {
  name   = "least-privilege"
  role   = aws_iam_role.events_batch.id
  policy = data.aws_iam_policy_document.events_batch.json
}

resource "aws_lambda_function" "events_batch" {
  function_name    = "bhavs-events_batch"
  role             = aws_iam_role.events_batch.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "analytics.events_batch.handler"
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  memory_size      = 256
  timeout          = 60
  environment {
    variables = { ANALYTICS_BUCKET = local.lake }
  }
  depends_on = [aws_cloudwatch_log_group.events_batch, aws_iam_role_policy.events_batch]
}

resource "aws_lambda_event_source_mapping" "events" {
  event_source_arn                   = aws_sqs_queue.events.arn
  function_name                      = aws_lambda_function.events_batch.arn
  batch_size                         = 100
  maximum_batching_window_in_seconds = 30 # fewer, bigger files
}

# ---------- Glue catalog + Athena ----------
resource "aws_glue_catalog_database" "analytics" {
  name = "bhavs_analytics"
}

locals {
  event_columns = {
    ts           = "bigint"
    received_at  = "bigint"
    type         = "string"
    user_id      = "string"
    title_id     = "string"
    session_id   = "string"
    position     = "double"
    duration     = "double"
    bitrate_kbps = "int"
    rendition    = "string"
    synthetic    = "boolean"
  }
  projection = {
    "projection.enabled"          = "true"
    "projection.dt.type"          = "date"
    "projection.dt.format"        = "yyyy-MM-dd"
    "projection.dt.range"         = "2026-01-01,NOW"
    "projection.dt.interval"      = "1"
    "projection.dt.interval.unit" = "DAYS"
    "projection.hour.type"        = "integer"
    "projection.hour.range"       = "0,23"
    "projection.hour.digits"      = "2"
  }
}

resource "aws_glue_catalog_table" "events_raw" {
  name          = "events_raw"
  database_name = aws_glue_catalog_database.analytics.name
  table_type    = "EXTERNAL_TABLE"
  parameters = merge(local.projection, {
    classification              = "json"
    "storage.location.template" = "s3://${local.lake}/raw/dt=$${dt}/hour=$${hour}/"
  })
  partition_keys {
    name = "dt"
    type = "string"
  }
  partition_keys {
    name = "hour"
    type = "string"
  }
  storage_descriptor {
    location      = "s3://${local.lake}/raw/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"
    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
      parameters            = { "ignore.malformed.json" = "true" }
    }
    dynamic "columns" {
      for_each = local.event_columns
      content {
        name = columns.key
        type = columns.value
      }
    }
  }
}

resource "aws_glue_catalog_table" "events" {
  name          = "events"
  database_name = aws_glue_catalog_database.analytics.name
  table_type    = "EXTERNAL_TABLE"
  parameters = merge(local.projection, {
    classification              = "parquet"
    "storage.location.template" = "s3://${local.lake}/parquet/dt=$${dt}/hour=$${hour}/"
  })
  partition_keys {
    name = "dt"
    type = "string"
  }
  partition_keys {
    name = "hour"
    type = "string"
  }
  storage_descriptor {
    location      = "s3://${local.lake}/parquet/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }
    dynamic "columns" {
      for_each = local.event_columns
      content {
        name = columns.key
        type = columns.value
      }
    }
  }
}

resource "aws_athena_workgroup" "bhavs" {
  name          = "bhavs"
  force_destroy = true
  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 1073741824 # 1 GB hard stop = at most $0.005 per query
    result_configuration {
      output_location = "s3://${local.lake}/athena-results/"
    }
  }
}

# Saved queries (also what the admin page shows). The SQL lives in services/src/analytics/sql/.
resource "aws_athena_named_query" "saved" {
  for_each    = toset(["views_per_title", "avg_watch_pct", "drop_off", "bitrate_distribution", "totals"])
  name        = "bhavs-${each.key}"
  workgroup   = aws_athena_workgroup.bhavs.id
  database    = aws_glue_catalog_database.analytics.name
  description = "bhavs analytics: ${each.key}"
  query       = file("${path.module}/../../services/src/analytics/sql/${each.key}.sql")
}

# ---------- hourly compaction + report ----------
resource "aws_cloudwatch_log_group" "compact" {
  name              = "/aws/lambda/bhavs-analytics_compact"
  retention_in_days = 14
}

resource "aws_iam_role" "compact" {
  name               = "bhavs-analytics-compact"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}

data "aws_iam_policy_document" "compact" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.compact.arn}:*"]
  }
  # Athena reads/writes S3 with the CALLER's permissions, so the Lambda role needs these.
  statement {
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [local.p.analytics_bucket_arn]
  }
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${local.p.analytics_bucket_arn}/raw/*", "${local.p.analytics_bucket_arn}/parquet/*", "${local.p.analytics_bucket_arn}/athena-results/*"]
  }
  statement {
    actions   = ["s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["${local.p.analytics_bucket_arn}/parquet/*", "${local.p.analytics_bucket_arn}/athena-results/*", "${local.p.analytics_bucket_arn}/reports/*"]
  }
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${local.p.analytics_bucket_arn}/reports/*"]
  }
  statement {
    actions   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:StopQueryExecution"]
    resources = [aws_athena_workgroup.bhavs.arn]
  }
  statement {
    actions = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:GetPartition", "glue:GetPartitions", "glue:CreateTable", "glue:DeleteTable"]
    resources = [
      "arn:aws:glue:us-east-2:${data.aws_caller_identity.me.account_id}:catalog",
      "arn:aws:glue:us-east-2:${data.aws_caller_identity.me.account_id}:database/${aws_glue_catalog_database.analytics.name}",
      "arn:aws:glue:us-east-2:${data.aws_caller_identity.me.account_id}:table/${aws_glue_catalog_database.analytics.name}/*",
    ]
  }
}

resource "aws_iam_role_policy" "compact" {
  name   = "least-privilege"
  role   = aws_iam_role.compact.id
  policy = data.aws_iam_policy_document.compact.json
}

resource "aws_lambda_function" "compact" {
  function_name    = "bhavs-analytics_compact"
  role             = aws_iam_role.compact.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "analytics.compact.handler"
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  memory_size      = 256
  timeout          = 900
  environment {
    variables = { ANALYTICS_BUCKET = local.lake, WORKGROUP = aws_athena_workgroup.bhavs.name }
  }
  depends_on = [aws_cloudwatch_log_group.compact, aws_iam_role_policy.compact]
}

data "aws_iam_policy_document" "assume_scheduler" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "bhavs-scheduler"
  assume_role_policy = data.aws_iam_policy_document.assume_scheduler.json
}

resource "aws_iam_role_policy" "scheduler" {
  name = "invoke-compact"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.compact.arn }]
  })
}

resource "aws_scheduler_schedule" "compact" {
  name                = "bhavs-analytics-hourly"
  schedule_expression = "cron(7 * * * ? *)" # 7 minutes past every hour: the previous hour is complete
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.compact.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = "{}"
  }
}

output "events_queue_url" { value = aws_sqs_queue.events.url }
output "analytics_compact_function" { value = aws_lambda_function.compact.function_name }
