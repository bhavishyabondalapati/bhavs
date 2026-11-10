# Recommender training job. SageMaker training is unavailable (ml.m5.large quota = 0, request still pending),
# so the SAME container runs as a Fargate task. Triggered weekly by EventBridge Scheduler and by `make train-cloud`.
# The schedule is created DISABLED: enable it (var.train_schedule_enabled) after the first manual run is approved.

variable "train_schedule_enabled" {
  type    = bool
  default = false
}

resource "aws_cloudwatch_log_group" "train" {
  name              = "/ecs/bhavs-train"
  retention_in_days = 14
}

resource "aws_iam_role" "train_exec" {
  name               = "bhavs-train-exec"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs.json
}

data "aws_iam_policy_document" "train_exec" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [local.p.train_ecr_repository_arn]
  }
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.train.arn}:*"]
  }
}

resource "aws_iam_role_policy" "train_exec" {
  name   = "pull-and-log"
  role   = aws_iam_role.train_exec.id
  policy = data.aws_iam_policy_document.train_exec.json
}

# What the training code itself may do: read titles + watch history, replace recommendation rows, write a run summary.
resource "aws_iam_role" "train_task" {
  name               = "bhavs-train-task"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs.json
}

data "aws_iam_policy_document" "train_task" {
  statement {
    actions   = ["dynamodb:Scan"]
    resources = [local.p.titles_table_arn, local.p.watch_history_table_arn, local.p.recommendations_table_arn]
  }
  statement {
    actions   = ["dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem"]
    resources = [local.p.recommendations_table_arn]
  }
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${local.p.analytics_bucket_arn}/ml/*"]
  }
}

resource "aws_iam_role_policy" "train_task" {
  name   = "ddb-and-run-summary"
  role   = aws_iam_role.train_task.id
  policy = data.aws_iam_policy_document.train_task.json
}

resource "aws_ecs_task_definition" "train" {
  family                   = "bhavs-train"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "2048"
  memory                   = "4096"
  execution_role_arn       = aws_iam_role.train_exec.arn
  task_role_arn            = aws_iam_role.train_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name        = "train"
    image       = "${local.p.train_ecr_repository_url}:latest"
    essential   = true
    command     = ["python", "train.py", "--model", "auto"]
    environment = [{ name = "RESULTS_BUCKET", value = local.p.analytics_bucket }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.train.name
        "awslogs-region"        = "us-east-2"
        "awslogs-stream-prefix" = "train"
      }
    }
  }])
}

# ---- weekly schedule (EventBridge Scheduler -> ECS RunTask on Fargate Spot) ----
data "aws_iam_policy_document" "scheduler_train" {
  statement {
    actions   = ["ecs:RunTask"]
    resources = ["${replace(aws_ecs_task_definition.train.arn, "/:\\d+$/", "")}:*", replace(aws_ecs_task_definition.train.arn, "/:\\d+$/", "")]
  }
  statement {
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.train_exec.arn, aws_iam_role.train_task.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_train" {
  name   = "run-train-task"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_train.json
}

resource "aws_scheduler_schedule" "train_weekly" {
  name                = "bhavs-train-weekly"
  schedule_expression = "cron(0 6 ? * SUN *)" # Sundays 06:00 UTC
  state               = var.train_schedule_enabled ? "ENABLED" : "DISABLED"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_ecs_cluster.transcode.arn
    role_arn = aws_iam_role.scheduler.arn
    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.train.arn
      platform_version    = "LATEST"
      capacity_provider_strategy {
        capacity_provider = "FARGATE_SPOT"
        weight            = 1
      }
      network_configuration {
        assign_public_ip = true
        subnets          = data.aws_subnets.default.ids
        security_groups  = [aws_security_group.task.id]
      }
    }
  }
}

output "train_task_definition" { value = aws_ecs_task_definition.train.arn }
output "ecs_cluster" { value = aws_ecs_cluster.transcode.name }
output "task_subnets" { value = data.aws_subnets.default.ids }
output "task_security_group" { value = aws_security_group.task.id }
