terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
  # Bucket name is passed with -backend-config (see Makefile) so the account id stays out of git.
  backend "s3" {
    key          = "persistent/terraform.tfstate"
    region       = "us-east-2"
    encrypt      = true
    use_lockfile = true
  }
}

# Profile comes from the AWS_PROFILE env var (Makefile exports AWS_PROFILE=sky).
provider "aws" {
  region = "us-east-2"
  default_tags {
    tags = {
      Project = "bhavs"
    }
  }
}
