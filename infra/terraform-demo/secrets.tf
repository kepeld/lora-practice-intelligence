# Empty secret containers — Terraform never holds the values. The USER populates
# them with `aws secretsmanager put-secret-value` before the instance boots; the
# instance role reads them. recovery_window_in_days = 0 so destroy is immediate.
resource "aws_secretsmanager_secret" "github_token" {
  name                    = "${var.project}/github-token"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name                    = "${var.project}/anthropic-api-key"
  recovery_window_in_days = 0
}
