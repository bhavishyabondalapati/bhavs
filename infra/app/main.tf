terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
  backend "s3" {
    key          = "app/terraform.tfstate"
    region       = "us-east-2"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = "us-east-2"
  default_tags {
    tags = {
      Project = "bhavs"
    }
  }
}

variable "state_bucket" {
  description = "Terraform state bucket (set by the Makefile via TF_VAR_state_bucket)."
  type        = string
}

variable "cors_origins" {
  type    = list(string)
  default = ["http://localhost:3000"]
}

# Everything the persistent stack created (Cognito ids, table names/ARNs).
data "terraform_remote_state" "persistent" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "persistent/terraform.tfstate"
    region = "us-east-2"
  }
}

locals {
  p = data.terraform_remote_state.persistent.outputs
}
