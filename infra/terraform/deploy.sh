#!/usr/bin/env bash
# Sync the code + the DuckDB warehouse onto the EC2 instance (no secrets ever
# land there) and start the API stack. Run from infra/terraform/ after apply.
set -euo pipefail
cd "$(dirname "$0")"

REPO_ROOT="$(cd ../.. && pwd)"
KEY="$(pwd)/ml-underground-key.pem"
IP="$(terraform output -raw public_ip)"
DEST="/home/ubuntu/ua-palantir"
SSHOPTS="-i $KEY -o StrictHostKeyChecking=no"

echo ">> waiting for instance bootstrap (Docker install)…"
until ssh $SSHOPTS "ubuntu@$IP" "test -f /home/ubuntu/SETUP_DONE" 2>/dev/null; do printf '.'; sleep 10; done
echo " ready"

echo ">> syncing code + the DuckDB warehouse (~330MB) — no .env / keys / tfstate…"
rsync -az --delete \
  --exclude '.git' --exclude '.venv' --exclude 'node_modules' \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.env' \
  --exclude 'infra/terraform' \
  -e "ssh $SSHOPTS" \
  "$REPO_ROOT/" "ubuntu@$IP:$DEST/"

echo ">> building + starting api + qdrant (first build pulls torch — a few minutes)…"
ssh $SSHOPTS "ubuntu@$IP" "cd $DEST && docker compose --profile app up -d --build"

echo
echo "================================================================"
echo " API:        http://$IP:8000/api/v1"
echo " Swagger:    http://$IP:8000/docs"
echo " For Dmytro: http://$IP:8000/api/v1"
echo "================================================================"
echo "Data endpoints work from the synced DuckDB file. /search and /ask"
echo "need Qdrant populated + an Anthropic key — see README.md."
