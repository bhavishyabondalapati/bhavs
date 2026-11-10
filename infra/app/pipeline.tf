# Video pipeline:  S3 upload -> EventBridge -> Lambda(start) -> Step Functions -> Fargate (ARM64, Spot first,
# on-demand retry once) -> Lambda(complete: READY)  |  on failure -> Lambda(fail: FAILED + SQS DLQ).

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

locals {
  pipeline_fns = {
    transcode_complete = {
      handler = "pipeline.transcode_complete.handler"
      env     = { OUT_BUCKET = local.p.output_bucket }
      access = [
        { actions = ["dynamodb:UpdateItem"], resources = [local.p.titles_table_arn] },
        { actions = ["s3:GetObject"], resources = ["${local.p.output_bucket_arn}/titles/*/manifest.json"] },
      ]
    }
    transcode_fail = {
      handler = "pipeline.transcode_fail.handler"
      env     = { DLQ_URL = aws_sqs_queue.dlq.url }
      access = [
        { actions = ["dynamodb:UpdateItem"], resources = [local.p.titles_table_arn] },
        { actions = ["sqs:SendMessage"], resources = [aws_sqs_queue.dlq.arn] },
      ]
    }
  }
}

# ---------- Dead-letter queue ----------
resource "aws_sqs_queue" "dlq" {
  name                      = "bhavs-transcode-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

# ---------- Lambdas (same zip + role pattern as the API) ----------
resource "aws_cloudwatch_log_group" "pipeline" {
  for_each          = local.pipeline_fns
  name              = "/aws/lambda/bhavs-${each.key}"
  retention_in_days = 14
}

# The start Lambda depends on the state machine (which depends on the two above), so it lives apart.
resource "aws_cloudwatch_log_group" "start" {
  name              = "/aws/lambda/bhavs-start_transcode"
  retention_in_days = 14
}

resource "aws_iam_role" "start" {
  name               = "bhavs-pipeline-start_transcode"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}

data "aws_iam_policy_document" "start" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.start.arn}:*"]
  }
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [local.p.titles_table_arn]
  }
  statement {
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.transcode.arn]
  }
}

resource "aws_iam_role_policy" "start" {
  name   = "least-privilege"
  role   = aws_iam_role.start.id
  policy = data.aws_iam_policy_document.start.json
}

resource "aws_lambda_function" "start" {
  function_name    = "bhavs-start_transcode"
  role             = aws_iam_role.start.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "pipeline.start_transcode.handler"
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  memory_size      = 256
  timeout          = 30

  environment {
    variables = {
      TITLES_TABLE      = local.p.titles_table
      STATE_MACHINE_ARN = aws_sfn_state_machine.transcode.arn
    }
  }
  tracing_config {
    mode = "Active"
  }

  depends_on = [aws_cloudwatch_log_group.start, aws_iam_role_policy.start, aws_iam_role_policy_attachment.xray]
}

resource "aws_iam_role" "pipeline" {
  for_each           = local.pipeline_fns
  name               = "bhavs-pipeline-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}

data "aws_iam_policy_document" "pipeline" {
  for_each = local.pipeline_fns
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.pipeline[each.key].arn}:*"]
  }
  dynamic "statement" {
    for_each = each.value.access
    content {
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }
}

resource "aws_iam_role_policy" "pipeline" {
  for_each = local.pipeline_fns
  name     = "least-privilege"
  role     = aws_iam_role.pipeline[each.key].id
  policy   = data.aws_iam_policy_document.pipeline[each.key].json
}

resource "aws_lambda_function" "pipeline" {
  for_each         = local.pipeline_fns
  function_name    = "bhavs-${each.key}"
  role             = aws_iam_role.pipeline[each.key].arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = each.value.handler
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  memory_size      = 256
  timeout          = 30

  environment {
    variables = merge({ TITLES_TABLE = local.p.titles_table }, each.value.env)
  }
  tracing_config {
    mode = "Active"
  }

  depends_on = [aws_cloudwatch_log_group.pipeline, aws_iam_role_policy.pipeline, aws_iam_role_policy_attachment.xray]
}

# ---------- Fargate transcoder ----------
resource "aws_ecs_cluster" "transcode" {
  name = "bhavs-transcode"
}

resource "aws_ecs_cluster_capacity_providers" "transcode" {
  cluster_name       = aws_ecs_cluster.transcode.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

resource "aws_cloudwatch_log_group" "transcode" {
  name              = "/ecs/bhavs-transcode"
  retention_in_days = 14
}

data "aws_iam_policy_document" "assume_ecs" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Execution role: lets ECS pull the image and write logs. Nothing else.
resource "aws_iam_role" "task_exec" {
  name               = "bhavs-transcode-exec"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs.json
}

data "aws_iam_policy_document" "task_exec" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [local.p.ecr_repository_arn]
  }
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.transcode.arn}:*"]
  }
}

resource "aws_iam_role_policy" "task_exec" {
  name   = "pull-and-log"
  role   = aws_iam_role.task_exec.id
  policy = data.aws_iam_policy_document.task_exec.json
}

# Task role: what the container itself may do - read uploads, write titles/*.
resource "aws_iam_role" "task" {
  name               = "bhavs-transcode-task"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs.json
}

data "aws_iam_policy_document" "task" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${local.p.source_bucket_arn}/uploads/*"]
  }
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${local.p.output_bucket_arn}/titles/*"]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "s3-in-out"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# 4 vCPU / 8 GB ARM64 (Graviton). Cheapest arch; Fargate Spot supports ARM64 on platform 1.4.0+.
resource "aws_ecs_task_definition" "transcode" {
  family                   = "bhavs-transcode"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "4096"
  memory                   = "8192"
  execution_role_arn       = aws_iam_role.task_exec.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }
  ephemeral_storage {
    size_in_gib = 30
  }

  container_definitions = jsonencode([{
    name      = "transcode"
    image     = "${local.p.ecr_repository_url}:latest"
    essential = true
    # Spot gives a 2-minute warning; ffmpeg has nothing to save, so a short stop is fine.
    stopTimeout = 30
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.transcode.name
        "awslogs-region"        = "us-east-2"
        "awslogs-stream-prefix" = "transcode"
      }
    }
  }])
}

# No inbound rules at all; outbound only (S3, ECR). Public IP is needed because there is no NAT gateway.
resource "aws_security_group" "task" {
  name        = "bhavs-transcode-task"
  description = "Transcode task: egress only"
  vpc_id      = data.aws_vpc.default.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ---------- Step Functions ----------
data "aws_iam_policy_document" "assume_sfn" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "bhavs-transcode-sfn"
  assume_role_policy = data.aws_iam_policy_document.assume_sfn.json
}

data "aws_iam_policy_document" "sfn" {
  statement {
    actions   = ["ecs:RunTask"]
    resources = ["${replace(aws_ecs_task_definition.transcode.arn, "/:\\d+$/", "")}:*", replace(aws_ecs_task_definition.transcode.arn, "/:\\d+$/", "")]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.transcode.arn]
    }
  }
  statement {
    actions   = ["ecs:StopTask", "ecs:DescribeTasks"]
    resources = ["*"]
  }
  statement {
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.task.arn, aws_iam_role.task_exec.arn]
  }
  # Required by the ".sync" integration: Step Functions manages an EventBridge rule to wait for the task.
  statement {
    actions   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
    resources = ["arn:aws:events:us-east-2:${data.aws_caller_identity.me.account_id}:rule/StepFunctionsGetEventsForECSTaskRule"]
  }
  statement {
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.pipeline["transcode_complete"].arn,
      aws_lambda_function.pipeline["transcode_fail"].arn,
    ]
  }
}

resource "aws_iam_role_policy" "sfn" {
  name   = "run-task-and-lambdas"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn.json
}

locals {
  run_task = { for kind, provider in { spot = "FARGATE_SPOT", ondemand = "FARGATE" } : kind => {
    Type     = "Task"
    Resource = "arn:aws:states:::ecs:runTask.sync"
    Parameters = {
      Cluster                  = aws_ecs_cluster.transcode.arn
      TaskDefinition           = aws_ecs_task_definition.transcode.arn
      CapacityProviderStrategy = [{ CapacityProvider = provider, Weight = 1 }]
      PlatformVersion          = "LATEST"
      NetworkConfiguration = {
        AwsvpcConfiguration = {
          Subnets        = data.aws_subnets.default.ids
          SecurityGroups = [aws_security_group.task.id]
          AssignPublicIp = "ENABLED"
        }
      }
      Overrides = {
        ContainerOverrides = [{
          Name = "transcode"
          Environment = [
            { Name = "TITLE_ID", "Value.$" = "$.title_id" },
            { Name = "SRC_BUCKET", "Value.$" = "$.src_bucket" },
            { Name = "SRC_KEY", "Value.$" = "$.src_key" },
            { Name = "OUT_PREFIX", "Value.$" = "$.out_prefix" },
            { Name = "OUT_BUCKET", Value = local.p.output_bucket },
          ]
        }]
      }
    }
    TimeoutSeconds = 3600
    ResultPath     = null
  } }
}

resource "aws_sfn_state_machine" "transcode" {
  name     = "bhavs-transcode"
  role_arn = aws_iam_role.sfn.arn

  definition = jsonencode({
    Comment = "Transcode one title. Spot first; on any failure retry ONCE on on-demand; then DLQ + FAILED."
    StartAt = "TranscodeSpot"
    States = {
      TranscodeSpot = merge(local.run_task.spot, {
        Next  = "MarkReady"
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.spot_error", Next = "TranscodeOnDemand" }]
      })
      TranscodeOnDemand = merge(local.run_task.ondemand, {
        Next  = "MarkReady"
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "MarkFailed" }]
      })
      MarkReady = {
        Type       = "Task"
        Resource   = aws_lambda_function.pipeline["transcode_complete"].arn
        Retry      = [{ ErrorEquals = ["Lambda.ServiceException", "Lambda.TooManyRequestsException"], MaxAttempts = 3, IntervalSeconds = 2, BackoffRate = 2 }]
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "MarkFailed" }]
        ResultPath = null
        End        = true
      }
      MarkFailed = {
        Type       = "Task"
        Resource   = aws_lambda_function.pipeline["transcode_fail"].arn
        ResultPath = null
        Next       = "Failed"
      }
      Failed = {
        Type  = "Fail"
        Error = "TranscodeFailed"
        Cause = "Both the Spot and on-demand attempts failed; title marked FAILED and sent to the DLQ."
      }
    }
  })

  tracing_configuration {
    enabled = true
  }

  depends_on = [aws_iam_role_policy_attachment.xray]
}

# ---------- EventBridge: S3 upload -> start ----------
resource "aws_cloudwatch_event_rule" "upload" {
  name        = "bhavs-source-upload"
  description = "New object under uploads/ in the bhavs source bucket"
  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created"]
    detail = {
      bucket = { name = [local.p.source_bucket] }
      object = { key = [{ prefix = "uploads/" }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "upload" {
  rule = aws_cloudwatch_event_rule.upload.name
  arn  = aws_lambda_function.start.arn
}

resource "aws_lambda_permission" "upload" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.start.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.upload.arn
}

output "cdn_domain" { value = local.p.cdn_domain }
output "state_machine_arn" { value = aws_sfn_state_machine.transcode.arn }
output "dlq_url" { value = aws_sqs_queue.dlq.url }
