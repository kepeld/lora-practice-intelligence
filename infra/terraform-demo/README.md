# Demo deploy — public dashboard + search + RAG (serve-only)

A single, persistent EC2 that serves the **whole app** — dashboard, `/search`
(semantic) and `/ask` (RAG) — over the real corpus, for the teacher demo. It is
the *serving* subset of the stack only: two containers (`app` + `qdrant`), no
Airflow / MySQL / pipeline. Tear it down with `terraform destroy` after the demo.

For the full pipeline IaC (collection + monitoring, US-6.1/6.2) see `../terraform`.

## What it runs

- `app` — FastAPI + the static dashboard, on `:8000` (public). Reads the marts
  from a 9.5 MB slim DuckDB; embeds queries with sentence-transformers (torch).
- `qdrant` — the vector DB, internal only. The two collections (`github_repos`,
  `huggingface_models`) are restored from snapshots at boot.

`t3.medium` (4 GB) keeps torch + Qdrant comfortable. ~$0.045/hr ≈ $30/mo if left
on; this is meant to run for the demo and be destroyed.

## The payload (built locally, no pipeline on the box)

Three files, produced from the local stack:

- `ML_UNDERGROUND.duckdb` — slim marts-only warehouse (`SILVER`/`GOLD` + a
  content-stripped `github_files`); real corpus, ~9.5 MB.
- `github_repos.snapshot`, `huggingface_models.snapshot` — Qdrant collection
  snapshots (`POST /collections/<c>/snapshots` then download).

## Deploy

```bash
cd infra/terraform-demo
terraform init

# 1. Create the bucket + secrets + IAM + SG first (everything but the instance)
terraform apply -target=aws_s3_bucket.data \
  -target=aws_secretsmanager_secret.github_token \
  -target=aws_secretsmanager_secret.anthropic_api_key \
  -target=aws_iam_instance_profile.ec2 \
  -target=aws_security_group.ec2

# 2. Populate the secrets (values never touch Terraform state)
aws secretsmanager put-secret-value --secret-id mlu-demo/github-token \
  --secret-string "$(gh auth token)"
aws secretsmanager put-secret-value --secret-id mlu-demo/anthropic-api-key \
  --secret-string "sk-ant-..."

# 3. Upload the payload (bucket name is in `terraform output data_bucket`)
BUCKET=$(terraform output -raw data_bucket)
aws s3 cp ML_UNDERGROUND.duckdb        "s3://$BUCKET/ML_UNDERGROUND.duckdb"
aws s3 cp github_repos.snapshot        "s3://$BUCKET/github_repos.snapshot"
aws s3 cp huggingface_models.snapshot  "s3://$BUCKET/huggingface_models.snapshot"

# 4. Launch the instance
terraform apply
```

Boot takes ~10–15 min (the torch image builds once). Poll readiness:

```bash
aws ssm start-session --target "$(terraform output -raw instance_id)"
# on the box:
tail -f /var/log/user-data.log      # watch progress
ls /home/ubuntu/SETUP_DONE          # exists when finished
```

Then open `terraform output app_url` and click around: insights (the four
quadrants), models, repos, the search box, and the ask/RAG panel.

## Notes

- `/ask` is public, so it defaults to a cheap model (`rag_model`,
  `claude-haiku-4-5`). Set `claude-opus-4-8` for richer answers if the cost is
  acceptable for the demo window.
- The app is `http://<ip>:8000` (no TLS) — fine for a short demo; browsers will
  flag it "not secure". A Caddy/Let's-Encrypt front is the production follow-up.

## Teardown

```bash
terraform destroy
```

Removes the instance, bucket (force_destroy), secrets, IAM and SG → $0.
