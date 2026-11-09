variable "budget_email" {
  description = "Email that receives AWS Budget alerts. Set in terraform.tfvars or TF_VAR_budget_email (never committed)."
  type        = string
}

variable "budget_limit_usd" {
  type    = number
  default = 100
}

variable "budget_thresholds_usd" {
  description = "Actual-spend alert thresholds in USD."
  type        = list(number)
  default     = [50, 80, 100]
}
