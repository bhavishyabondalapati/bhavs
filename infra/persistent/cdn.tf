# Streaming CDN. Option B (no custom domain): the player gets a short-lived signed token in the URL path;
# a CloudFront Function verifies it. Switching to signed cookies later only changes this file + the token Lambda.

resource "aws_cloudfront_key_value_store" "keys" {
  name    = "bhavs-stream-keys"
  comment = "HMAC key for stream tokens. The value is set by scripts/rotate_stream_key.sh, never by Terraform."
}

resource "aws_cloudfront_function" "viewer_request" {
  name    = "bhavs-verify-token"
  runtime = "cloudfront-js-2.0"
  comment = "Verifies stream tokens"
  publish = true
  code    = file("${path.module}/cdn/viewer_request.js")

  key_value_store_associations = [aws_cloudfront_key_value_store.keys.arn]
}

resource "aws_cloudfront_origin_access_control" "output" {
  name                              = "bhavs-output-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_response_headers_policy" "cors" {
  name = "bhavs-stream-cors"
  cors_config {
    access_control_allow_credentials = false
    origin_override                  = true
    access_control_max_age_sec       = 3600
    access_control_allow_origins {
      items = var.web_origins
    }
    access_control_allow_methods {
      items = ["GET", "HEAD", "OPTIONS"]
    }
    access_control_allow_headers {
      items = ["*"]
    }
    access_control_expose_headers {
      items = ["Content-Length", "Content-Range"]
    }
  }
  security_headers_config {
    content_type_options {
      override = true
    }
  }
}

resource "aws_cloudfront_distribution" "cdn" {
  enabled         = true
  comment         = "bhavs streaming"
  price_class     = "PriceClass_100" # US/Canada/Europe edges: cheapest
  http_version    = "http2and3"
  is_ipv6_enabled = true

  origin {
    origin_id                = "output"
    domain_name              = aws_s3_bucket.output.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.output.id
  }

  default_cache_behavior {
    target_origin_id           = "output"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.cors.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.viewer_request.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
