# AWS deploy (Terraform) — pipeline + monitoring on one EC2, data to S3

Single ephemeral EC2 running the whole stack (`docker compose --profile de --profile monitor`),
publishing the DuckDB warehouse to S3 so Dmytro can download it and work locally. Satisfies #40
(US-6.1 pipeline on AWS via Terraform, NFR-3 one-command apply, NFR-5 secrets out of code; US-6.2
monitoring) without the expensive managed services. Run it, demo it, `terraform destroy`.

## What it creates
- 1 EC2 (Ubuntu 22.04, `t3.xlarge`, 40 GB gp3) running the 8-service stack; **no public ports** —
  Airflow/Grafana/Prometheus are reachable only from `operator_cidr`, shell is via SSM.
- IAM instance role + profile (read 3 secrets, write the data bucket, SSM).
- 3 **empty** Secrets Manager secrets (you populate the values).
- 1 S3 data bucket (the pipeline publishes `ML_UNDERGROUND.duckdb` here; persists across teardown).

## Prerequisites
- `aws configure` done (account on a paid plan), `terraform` installed.
- Set `operator_cidr` in `terraform.tfvars` to your `<public-ip>/32`.

## Deploy
```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # set operator_cidr

# 0. tear down the earlier EC2 still in state, then re-init for the new providers
terraform destroy            # removes the idle EC2/EIP/SG/key from the previous run
terraform init -upgrade

# 1. create the secret containers + IAM + SG + S3 first (so secrets exist before the instance boots)
terraform plan  -out=tfplan -target=aws_secretsmanager_secret.github_token \
  -target=aws_secretsmanager_secret.anthropic_api_key \
  -target=aws_secretsmanager_secret.airflow_secret_key \
  -target=aws_iam_instance_profile.ec2 -target=aws_security_group.ec2 -target=aws_s3_bucket.data
terraform apply tfplan

# 2. populate the secrets (values never touch tfstate/code)
aws secretsmanager put-secret-value --secret-id ml-underground/github-token     --secret-string "ghp_..."
aws secretsmanager put-secret-value --secret-id ml-underground/anthropic-api-key --secret-string "sk-ant-..."   # or "" to skip /ask
aws secretsmanager put-secret-value --secret-id ml-underground/airflow-secret-key --secret-string "$(openssl rand -hex 32)"

# 3. create the instance — user_data reads the populated secrets and brings the stack up
terraform plan  -out=tfplan
terraform apply tfplan
```
`terraform output` prints the URLs, the SSM command, and the `presign_duckdb` command. The build on
the instance (one torch image) takes ~10–15 min; poll readiness:
```bash
aws ssm start-session --target <instance-id>     # then: tail -f /var/log/user-data.log ; ls /home/ubuntu/SETUP_DONE
```

## Run the DAGs (acceptance) + publish the data
In Airflow (`http://<ip>:8081`, admin/admin, your IP only): unpause + trigger `ml_underground_pipeline`,
`corpus_backfill_dag` (small config `{"lora_target_count":150,"hf_target_count":300,"files_repo_limit":200}`),
and `lora_extraction_dag` → all green. The cron then publishes `ML_UNDERGROUND.duckdb` to S3.

## How Dmytro downloads (no AWS account needed)
```bash
aws s3 presign s3://<data-bucket>/data/ML_UNDERGROUND.duckdb --expires-in 604800   # `terraform output presign_duckdb`
```
Send Dmytro the URL → he runs:
```bash
curl -o de/dbt/ml_underground/ML_UNDERGROUND.duckdb "<presigned-url>"
```
…and `ml/data.py` reads it locally. **Snapshot model:** to refresh, re-run the pipeline (it
republishes) and re-download. The S3 bucket persists so the last snapshot is always downloadable.

## Cost + teardown
~$0.17/hr EC2 + pennies (gp3/secrets); a demo run is **< $1** (inside the $5 budget alert). S3 of a
~330 MB file ≈ $0.01/mo. `terraform destroy` the EC2 after the demo (secrets delete immediately,
bucket `force_destroy`) → ~$0. Keep the bucket if you still want Dmytro downloading.

## Production follow-up (full #40, not built here)
RDS (managed MySQL), NAT Gateway, ECS/Fargate + ECR, GitHub Actions CI/CD (OIDC) for plan/apply,
ALB + ACM/TLS, remote tfstate (S3 + DynamoDB lock), Airflow remote logging to S3, secret rotation.
Each is cost/effort-heavy and unnecessary for an ephemeral demo; this single-EC2 deploy is the
demo-grade slice that can be promoted to those later.
