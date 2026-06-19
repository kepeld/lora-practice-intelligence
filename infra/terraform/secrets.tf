# Empty secret containers — Terraform never holds the values (no secret_version here).
# The USER populates them with `aws secretsmanager put-secret-value` before the instance
# boots; the instance role reads them. recovery_window_in_days = 0 so destroy is immediate
# and a re-apply within 7 days doesn't hit a reserved/scheduled-for-deletion name.
resource "aws_secretsmanager_secret" "github_token" {
  name                    = "${var.project}/github-token"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name                    = "${var.project}/anthropic-api-key"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "airflow_secret_key" {
  name                    = "${var.project}/airflow-secret-key"
  recovery_window_in_days = 0
}
