# Account-level usage budget. Credits are EXCLUDED so alerts track real usage, not what credits hide.
# Budgets only alert; they cannot stop spending. ANNUALLY = one cumulative cap across the project.
resource "aws_budgets_budget" "usage" {
  name         = "bhavs-usage"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "ANNUALLY"

  cost_types {
    include_credit = false
    include_refund = false
  }

  dynamic "notification" {
    for_each = toset(var.budget_thresholds_usd)
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "ABSOLUTE_VALUE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_email]
    }
  }
}
