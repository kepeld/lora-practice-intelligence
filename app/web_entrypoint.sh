#!/bin/sh
set -e
# Optionally swap the baked demo warehouse for a hosted real one (a public
# R2 / S3 / GitHub-release URL). stdlib urllib only — keeps the image torch-
# and curl-free; a failed fetch falls back to the demo so the site still boots.
if [ -n "$DUCKDB_URL" ]; then
  echo "fetching warehouse from \$DUCKDB_URL"
  python -c "import os,urllib.request; urllib.request.urlretrieve(os.environ['DUCKDB_URL'], os.environ['DUCKDB_PATH'])" \
    || echo "fetch failed; serving the baked demo warehouse"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
