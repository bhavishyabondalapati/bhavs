#!/usr/bin/env bash
# Put an existing user in the Cognito "admin" group (they can then open /admin). Usage: scripts/make_admin.sh you@example.com
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-sky}"
[ $# -eq 1 ] || { echo "usage: $0 <email>"; exit 1; }
POOL=$(terraform -chdir=infra/persistent output -raw user_pool_id)
aws cognito-idp admin-add-user-to-group --region us-east-2 --user-pool-id "$POOL" --username "$1" --group-name admin
echo "$1 is now an admin. They must sign out and back in for the new group to appear in their token."
