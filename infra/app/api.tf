# One zip holds all API code; each function gets its own IAM role so permissions stay minimal.
data "archive_file" "api" {
  type        = "zip"
  source_dir  = "${path.module}/../../services/src"
  output_path = "${path.module}/build/api.zip"
  excludes    = tolist(fileset("${path.module}/../../services/src", "**/__pycache__/**"))
}

locals {
  functions = {
    titles_list = {
      route   = "GET /titles"
      handler = "api.titles_list.handler"
      env     = {}
      access = [
        { actions = ["dynamodb:Scan"], resources = [local.p.titles_table_arn] },
      ]
    }
    titles_get = {
      route   = "GET /titles/{id}"
      handler = "api.titles_get.handler"
      env     = {}
      access = [
        { actions = ["dynamodb:GetItem"], resources = [local.p.titles_table_arn] },
      ]
    }
    me = {
      route   = "GET /me"
      handler = "api.me.handler"
      env     = {}
      access = [
        { actions = ["dynamodb:UpdateItem"], resources = [local.p.users_table_arn] },
      ]
    }
    continue_watching = {
      route   = "GET /me/continue-watching"
      handler = "api.continue_watching.handler"
      env     = {}
      access = [
        { actions = ["dynamodb:Query"], resources = [local.p.watch_history_table_arn] },
        { actions = ["dynamodb:BatchGetItem"], resources = [local.p.titles_table_arn] },
      ]
    }
    recommendations = {
      route   = "GET /me/recommendations"
      handler = "api.recommendations.handler"
      env     = {}
      access = [
        { actions = ["dynamodb:Query"], resources = [local.p.recommendations_table_arn] },
        { actions = ["dynamodb:BatchGetItem", "dynamodb:Scan"], resources = [local.p.titles_table_arn] },
      ]
    }
    stream_token = {
      route   = "GET /titles/{id}/stream"
      handler = "api.stream_token.handler"
      env = {
        CDN_DOMAIN       = local.p.cdn_domain
        STREAM_KEY_PARAM = local.stream_key_param
      }
      access = [
        { actions = ["dynamodb:GetItem"], resources = [local.p.titles_table_arn] },
        { actions = ["ssm:GetParameter"], resources = ["arn:aws:ssm:us-east-2:${data.aws_caller_identity.me.account_id}:parameter${local.stream_key_param}"] },
      ]
    }
    admin_analytics = {
      route   = "GET /admin/analytics"
      handler = "api.admin_analytics.handler"
      env     = { ANALYTICS_BUCKET = local.p.analytics_bucket }
      access = [
        { actions = ["s3:GetObject"], resources = ["${local.p.analytics_bucket_arn}/reports/*"] },
      ]
    }
    search = {
      route   = "GET /search"
      handler = "api.search.handler"
      env = {
        ANALYTICS_BUCKET = local.p.analytics_bucket
        EMBEDDINGS_KEY   = "search/embeddings.json"
      }
      access = [
        { actions = ["s3:GetObject"], resources = ["${local.p.analytics_bucket_arn}/search/*"] },
        { actions = ["dynamodb:BatchGetItem"], resources = [local.p.titles_table_arn] },
        { actions = ["bedrock:InvokeModel"], resources = ["arn:aws:bedrock:us-east-2::foundation-model/amazon.titan-embed-text-v2:0"] },
      ]
    }
    events = {
      route   = "POST /events"
      handler = "api.events.handler"
      env     = { EVENTS_QUEUE_URL = aws_sqs_queue.events.url }
      access = [
        { actions = ["sqs:SendMessage"], resources = [aws_sqs_queue.events.arn] },
        { actions = ["dynamodb:UpdateItem"], resources = [local.p.watch_history_table_arn] },
        { actions = ["dynamodb:GetItem"], resources = [local.p.titles_table_arn] },
      ]
    }
  }
}

data "aws_iam_policy_document" "assume_lambda" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fn" {
  for_each           = local.functions
  name               = "bhavs-api-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}

data "aws_iam_policy_document" "fn" {
  for_each = local.functions

  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.fn[each.key].arn}:*"]
  }

  dynamic "statement" {
    for_each = each.value.access
    content {
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }
}

resource "aws_iam_role_policy" "fn" {
  for_each = local.functions
  name     = "least-privilege"
  role     = aws_iam_role.fn[each.key].id
  policy   = data.aws_iam_policy_document.fn[each.key].json
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.functions
  name              = "/aws/lambda/bhavs-api-${each.key}"
  retention_in_days = 14
}

resource "aws_lambda_function" "fn" {
  for_each         = local.functions
  function_name    = "bhavs-api-${each.key}"
  role             = aws_iam_role.fn[each.key].arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = each.value.handler
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  memory_size      = 256
  timeout          = 10

  environment {
    variables = merge({
      TITLES_TABLE  = local.p.titles_table
      USERS_TABLE   = local.p.users_table
      HISTORY_TABLE = local.p.watch_history_table
      RECS_TABLE    = local.p.recommendations_table
    }, each.value.env)
  }

  depends_on = [aws_cloudwatch_log_group.fn, aws_iam_role_policy.fn]
}

resource "aws_apigatewayv2_api" "http" {
  name          = "bhavs-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = var.cors_origins
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.http.id
  name             = "cognito-jwt"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    audience = [local.p.user_pool_client_id]
    issuer   = local.p.user_pool_issuer
  }
}

resource "aws_apigatewayv2_integration" "fn" {
  for_each               = local.functions
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.fn[each.key].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "fn" {
  for_each           = local.functions
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = each.value.route
  target             = "integrations/${aws_apigatewayv2_integration.fn[each.key].id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_lambda_permission" "apigw" {
  for_each      = local.functions
  statement_id  = "AllowHttpApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn[each.key].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true

  # Cost guard: a runaway client cannot generate a surprise bill.
  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 25
  }
}

output "api_url" { value = aws_apigatewayv2_api.http.api_endpoint }
output "region" { value = "us-east-2" }
output "user_pool_client_id" { value = local.p.user_pool_client_id }
output "user_pool_id" { value = local.p.user_pool_id }
