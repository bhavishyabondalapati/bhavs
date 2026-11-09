# All on-demand (pay per request): $0 when idle.
resource "aws_dynamodb_table" "titles" {
  name         = "bhavs-titles"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"
  attribute {
    name = "id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "users" {
  name         = "bhavs-users"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"
  attribute {
    name = "user_id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "watch_history" {
  name         = "bhavs-watch-history"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"
  range_key    = "title_id"
  attribute {
    name = "user_id"
    type = "S"
  }
  attribute {
    name = "title_id"
    type = "S"
  }
}

# Rows per user: user_id + row_key ("top_picks", "because#<title_id>"). user_id "GLOBAL" holds
# popularity rows used for cold start.
resource "aws_dynamodb_table" "recommendations" {
  name         = "bhavs-recommendations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"
  range_key    = "row_key"
  attribute {
    name = "user_id"
    type = "S"
  }
  attribute {
    name = "row_key"
    type = "S"
  }
}
