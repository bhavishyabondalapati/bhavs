data "aws_caller_identity" "me" {}

locals {
  acct = data.aws_caller_identity.me.account_id
}

# ---- uploads (source videos). An upload here starts the transcode pipeline (via EventBridge). ----
resource "aws_s3_bucket" "source" {
  bucket        = "bhavs-source-${local.acct}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "source" {
  bucket                  = aws_s3_bucket.source.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "source" {
  bucket = aws_s3_bucket.source.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "source" {
  bucket = aws_s3_bucket.source.id
  rule {
    id     = "expire-sources"
    status = "Enabled"
    filter {
      prefix = "uploads/"
    }
    expiration {
      days = 30 # originals live on your Mac; this only bounds storage cost
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 3
    }
  }
}

# Send "object created" events to EventBridge; rules live in the (destroyable) app stack.
resource "aws_s3_bucket_notification" "source" {
  bucket      = aws_s3_bucket.source.id
  eventbridge = true
}

# ---- output (HLS renditions, posters). Private: only CloudFront (OAC) can read it. ----
resource "aws_s3_bucket" "output" {
  bucket        = "bhavs-output-${local.acct}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "output" {
  bucket                  = aws_s3_bucket.output.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "output" {
  bucket = aws_s3_bucket.output.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "output" {
  bucket = aws_s3_bucket.output.id
  rule {
    id     = "abort-multipart"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 3
    }
  }
}

data "aws_iam_policy_document" "output_cf" {
  statement {
    sid       = "AllowCloudFrontOACRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.output.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.cdn.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "output" {
  bucket     = aws_s3_bucket.output.id
  policy     = data.aws_iam_policy_document.output_cf.json
  depends_on = [aws_s3_bucket_public_access_block.output]
}

# ---- container registry for the Fargate ffmpeg image ----
resource "aws_ecr_repository" "transcode" {
  name                 = "bhavs-transcode"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "transcode" {
  repository = aws_ecr_repository.transcode.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the 3 newest images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 3 }
      action       = { type = "expire" }
    }]
  })
}

# ---- analytics lake: raw JSONL from the events pipeline, compacted Parquet, Athena results, cached reports ----
resource "aws_s3_bucket" "analytics" {
  bucket        = "bhavs-analytics-${local.acct}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "analytics" {
  bucket                  = aws_s3_bucket.analytics.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "analytics" {
  bucket = aws_s3_bucket.analytics.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "analytics" {
  bucket = aws_s3_bucket.analytics.id
  rule {
    id     = "athena-results-expire"
    status = "Enabled"
    filter {
      prefix = "athena-results/"
    }
    expiration {
      days = 7
    }
  }
  rule {
    id     = "abort-multipart"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 3
    }
  }
}
