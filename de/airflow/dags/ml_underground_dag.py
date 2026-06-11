"""
ML Underground — Main Pipeline DAG

Orchestrates the hourly LoRA-corpus refresh:
  1. repo_enricher     — enrich discovered LoRA repos (lora_search_discovery) via GitHub API
  2. hf_ingestion      — fetch new HuggingFace LoRA models + model cards
  3. data_quality      — Great Expectations validation of the bronze tables
  4. load_to_duckdb    — replicate MySQL bronze tables into the DuckDB warehouse
  5. dbt_run           — build dbt Silver/Gold models in DuckDB
  + embed_repos / embed_hf_models — embed READMEs / model cards into Qdrant (RAG);
    a non-blocking side branch off hf_ingestion.

GitHub LoRA discovery, file extraction and GH↔HF linkage run in the weekly
corpus_backfill_dag — the GH Archive firehose was retired (LoRA repos come from
targeted Search, not the global event stream).

Schedule: hourly
"""

import os
from datetime import timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago

default_args = {
    "owner": "ml-underground",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="ml_underground_pipeline",
    default_args=default_args,
    description="Hourly LoRA-corpus refresh: enrich → HF ingest → quality → DuckDB → dbt",
    schedule_interval="0 * * * *",  # every hour at :00
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
    tags=["ml-underground", "de", "github"],
) as dag:

    def run_enricher(**context):
        """Enrich unenriched LoRA repos with GitHub API metadata (BATCH_SIZE per run)."""
        import base64
        import json
        import re
        import time
        from datetime import datetime, timedelta, timezone

        import mysql.connector
        import requests

        GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
        MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql")
        MYSQL_USER = os.getenv("MYSQL_USER", "root")
        MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
        MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ml_underground")
        BATCH_SIZE = 50
        REQUEST_DELAY = 0.05
        DEP_FILES = ["requirements.txt", "pyproject.toml", "setup.py", "package.json"]

        session = requests.Session()
        session.headers.update({
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        })

        conn = mysql.connector.connect(
            host=MYSQL_HOST, user=MYSQL_USER,
            password=MYSQL_PASSWORD, database=MYSQL_DATABASE,
        )
        # Enrich LoRA repos surfaced by the targeted collector (lora_search_discovery)
        # that are not yet in github_repos_enriched, newest discoveries first. The GH
        # Archive firehose was retired, so this drains the targeted-Search backlog and
        # keeps up with new weekly discoveries between corpus_backfill_dag runs.
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT d.repo_id, d.repo_name
            FROM lora_search_discovery d
            LEFT JOIN github_repos_enriched e ON d.repo_id = e.repo_id
            WHERE e.repo_id IS NULL
            ORDER BY d.discovered_at DESC
            LIMIT %s
        """, (BATCH_SIZE,))
        repos = cursor.fetchall()
        cursor.close()

        def api_get(path):
            try:
                r = session.get(f"https://api.github.com{path}", timeout=10)
                return r.json() if r.status_code == 200 else None
            except Exception:
                return None

        def count_via_pagination(path):
            # item count via the Link rel="last" page number (per_page=1)
            try:
                r = session.get(f"https://api.github.com{path}", timeout=10)
                if r.status_code != 200:
                    return 0
                match = re.search(
                    r'[?&]page=(\d+)>;\s*rel="last"', r.headers.get("Link", "")
                )
                if match:
                    return int(match.group(1))
                body = r.json()
                return len(body) if isinstance(body, list) else 0
            except Exception:
                return 0

        def parse_dt(value):
            if not value:
                return None
            try:
                return datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except Exception:
                return None

        def decode_content(blob):
            if blob and blob.get("encoding") == "base64":
                try:
                    return base64.b64decode(blob["content"]).decode(
                        "utf-8", errors="replace"
                    )
                except Exception:
                    return None
            return None

        since_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        enriched = 0
        for repo in repos:
            repo_name = repo["repo_name"]
            repo_id = repo["repo_id"]

            data = api_get(f"/repos/{repo_name}")
            status = "ok" if data else "not_found"
            data = data or {}
            license_info = data.get("license") or {}

            description = data.get("description")
            language = data.get("language")
            topics = data.get("topics", [])
            license_name = license_info.get("spdx_id")
            open_issues = data.get("open_issues_count", 0)
            repo_created_at = parse_dt(data.get("created_at"))
            pushed_at = parse_dt(data.get("pushed_at"))
            repo_size_kb = data.get("size", 0)
            forks_count = data.get("forks_count", 0)
            subscribers_count = data.get("subscribers_count", 0)
            is_fork = bool(data.get("fork", False))
            is_archived = bool(data.get("archived", False))
            homepage = data.get("homepage") or None
            default_branch = data.get("default_branch")

            has_tests = has_ci = False
            dep_path = None
            if default_branch:
                tree = api_get(
                    f"/repos/{repo_name}/git/trees/{default_branch}?recursive=1"
                )
                if tree and tree.get("truncated"):
                    print(f"repo_enricher: {repo_name} git tree truncated -- "
                          "has_tests/has_ci/dep may be incomplete")
                root_files = set()
                for entry in (tree or {}).get("tree", []):
                    path = entry.get("path", "")
                    lower = path.lower()
                    parts = lower.split("/")
                    base = parts[-1]
                    if not has_tests and (
                        "test" in parts or "tests" in parts
                        or base.startswith("test_") or base.endswith("_test.py")
                        or base.endswith(".test.js") or base.endswith(".spec.js")
                    ):
                        has_tests = True
                    if not has_ci and (
                        lower.startswith(".github/workflows/")
                        or lower.startswith(".circleci/")
                        or base in (".travis.yml", ".gitlab-ci.yml", "jenkinsfile")
                    ):
                        has_ci = True
                    if "/" not in path:
                        root_files.add(base)
                dep_path = next((d for d in DEP_FILES if d in root_files), None)
                time.sleep(REQUEST_DELAY)

            readme = decode_content(api_get(f"/repos/{repo_name}/readme"))
            readme_length = len(readme) if readme else 0
            time.sleep(REQUEST_DELAY)

            # only the dep file the tree located
            deps = {}
            if dep_path:
                content = decode_content(
                    api_get(f"/repos/{repo_name}/contents/{dep_path}")
                )
                if content:
                    deps = {"file": dep_path, "content": content[:5000]}
                time.sleep(REQUEST_DELAY)

            contributors_count = commit_count_30d = 0
            if status == "ok":
                contributors_count = count_via_pagination(
                    f"/repos/{repo_name}/contributors?per_page=1&anon=true"
                )
                time.sleep(REQUEST_DELAY)
                commit_count_30d = count_via_pagination(
                    f"/repos/{repo_name}/commits?since={since_30d}&per_page=1"
                )
                time.sleep(REQUEST_DELAY)

            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO github_repos_enriched
                    (repo_id, repo_name, description, primary_language, topics,
                     license, open_issues_count, readme_content, readme_length,
                     dependencies, repo_created_at, repo_size_kb, has_tests,
                     has_ci, contributors_count, commit_count_30d, is_fork,
                     is_archived, pushed_at, forks_count, subscribers_count,
                     homepage, enriched_at, enrichment_status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    description=VALUES(description),
                    primary_language=VALUES(primary_language),
                    topics=VALUES(topics),
                    license=VALUES(license),
                    open_issues_count=VALUES(open_issues_count),
                    readme_content=VALUES(readme_content),
                    readme_length=VALUES(readme_length),
                    dependencies=VALUES(dependencies),
                    repo_created_at=VALUES(repo_created_at),
                    repo_size_kb=VALUES(repo_size_kb),
                    has_tests=VALUES(has_tests),
                    has_ci=VALUES(has_ci),
                    contributors_count=VALUES(contributors_count),
                    commit_count_30d=VALUES(commit_count_30d),
                    is_fork=VALUES(is_fork),
                    is_archived=VALUES(is_archived),
                    pushed_at=VALUES(pushed_at),
                    forks_count=VALUES(forks_count),
                    subscribers_count=VALUES(subscribers_count),
                    homepage=VALUES(homepage),
                    enriched_at=VALUES(enriched_at),
                    enrichment_status=VALUES(enrichment_status)
            """, (
                repo_id, repo_name, description, language, json.dumps(topics),
                license_name, open_issues, readme, readme_length,
                json.dumps(deps), repo_created_at, repo_size_kb, has_tests,
                has_ci, contributors_count, commit_count_30d, is_fork,
                is_archived, pushed_at, forks_count, subscribers_count,
                homepage, datetime.now(timezone.utc), status,
            ))
            conn.commit()
            cursor.close()
            enriched += 1
            print(f"Enriched [{enriched}] {repo_name} | status={status} | lang={language}")

        conn.close()
        print(f"Enrichment complete: {enriched} repos processed")
        return {"enriched": enriched}

    task_enricher = PythonOperator(
        task_id="repo_enricher",
        python_callable=run_enricher,
        provide_context=True,
    )

    def run_hf_ingestion(**context):
        """Fetch newest HuggingFace Hub models into MySQL; parse base_model for hf_model_tree."""
        import json
        import sys
        from datetime import datetime, timezone

        import mysql.connector
        from huggingface_hub import HfApi, ModelCard

        # de/ingestion is mounted at /opt/airflow/ingestion — shared, unit-tested
        # helpers live there (the LoRA filter, this HF retry wrapper, ...).
        sys.path.insert(0, "/opt/airflow")
        from ingestion.hf_utils import list_models_with_retry

        MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql")
        MYSQL_USER = os.getenv("MYSQL_USER", "root")
        MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
        MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ml_underground")
        HF_BATCH_SIZE = int(os.getenv("HF_BATCH_SIZE", "100"))

        def extract_base_model(tags):
            # HF tags the base model as "base_model:<id>" and may also add a
            # relation-qualified form like "base_model:adapter:<id>".
            for tag in tags:
                if tag.startswith("base_model:"):
                    value = tag.split("base_model:", 1)[1]
                    for relation in ("finetune:", "adapter:", "quantized:", "merge:"):
                        if value.startswith(relation):
                            value = value[len(relation):]
                            break
                    return value
            return None

        def naive(dt):
            # HF returns tz-aware UTC datetimes; MySQL DATETIME needs naive.
            return dt.replace(tzinfo=None) if dt else None

        def load_card(model_id):
            # Model card README; many fresh models have none — store NULL.
            try:
                return ModelCard.load(model_id).content
            except Exception:
                return None

        # LoRA-targeted ingestion: take the newest models that match the LoRA
        # ecosystem (library:peft OR tag:lora). Dedup by model.id across the
        # two passes — many LoRA models carry tag:lora but library:transformers.
        api = HfApi()
        seen = {}
        for kwargs in [{"filter": "peft"}, {"filter": "lora"}]:
            # Retry transient HF DNS/connection blips (the "Name or service not
            # known" failure) so one flaky lookup no longer fails the task and
            # cascades upstream_failed down the rest of the pipeline.
            for m in list_models_with_retry(
                api, sort="created_at", direction=-1, limit=HF_BATCH_SIZE,
                full=True, **kwargs,
            ):
                seen[m.id] = m
        models = list(seen.values())

        conn = mysql.connector.connect(
            host=MYSQL_HOST, user=MYSQL_USER,
            password=MYSQL_PASSWORD, database=MYSQL_DATABASE,
        )
        cursor = conn.cursor()

        ingested = 0
        for model in models:
            tags = list(model.tags or [])
            author = model.id.split("/")[0] if "/" in model.id else None
            cursor.execute("""
                INSERT INTO huggingface_models_bronze
                    (model_id, author, base_model, pipeline_tag, library_name,
                     downloads, likes, tags, card_content,
                     created_at, last_modified, ingested_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    base_model=VALUES(base_model),
                    pipeline_tag=VALUES(pipeline_tag),
                    library_name=VALUES(library_name),
                    downloads=VALUES(downloads),
                    likes=VALUES(likes),
                    tags=VALUES(tags),
                    card_content=VALUES(card_content),
                    last_modified=VALUES(last_modified),
                    ingested_at=VALUES(ingested_at)
            """, (
                model.id, author, extract_base_model(tags),
                model.pipeline_tag, model.library_name,
                model.downloads or 0, model.likes or 0, json.dumps(tags),
                load_card(model.id),
                naive(model.created_at), naive(model.last_modified),
                datetime.now(timezone.utc),
            ))
            ingested += 1

        conn.commit()
        cursor.close()
        conn.close()
        print(f"HuggingFace ingestion: {ingested} models stored")
        return {"ingested": ingested}

    task_hf_ingestion = PythonOperator(
        task_id="hf_ingestion",
        python_callable=run_hf_ingestion,
        provide_context=True,
    )

    def run_embed_repos(**context):
        """Embed newly-enriched repo READMEs into Qdrant `github_repos`; track in github_repos_embedded."""
        import json
        from datetime import datetime, timezone

        import mysql.connector
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams
        from sentence_transformers import SentenceTransformer

        MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql")
        MYSQL_USER = os.getenv("MYSQL_USER", "root")
        MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
        MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ml_underground")
        QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
        QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
        COLLECTION = "github_repos"
        MODEL_NAME = "all-MiniLM-L6-v2"
        BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "100"))

        conn = mysql.connector.connect(
            host=MYSQL_HOST, user=MYSQL_USER,
            password=MYSQL_PASSWORD, database=MYSQL_DATABASE,
        )
        cursor = conn.cursor(dictionary=True)
        # status='ok' excludes radio_lora (LoRaWAN/IoT) false positives so the
        # Qdrant LoRA-practice collection stays clean (US-5.3).
        cursor.execute("""
            SELECT e.repo_id, e.repo_name, e.primary_language, e.topics,
                   e.enriched_at, e.readme_content
            FROM github_repos_enriched e
            LEFT JOIN github_repos_embedded emb ON e.repo_id = emb.repo_id
            WHERE e.readme_content IS NOT NULL
              AND e.enrichment_status = 'ok'
              -- re-embed when the README changed since the last embed, not only
              -- first-time rows, so Qdrant vectors don't go permanently stale.
              AND (emb.repo_id IS NULL OR e.enriched_at > emb.embedded_at)
            ORDER BY e.enriched_at DESC
            LIMIT %s
        """, (BATCH_SIZE,))
        repos = cursor.fetchall()
        cursor.close()

        if not repos:
            conn.close()
            print("embed_repos: nothing new to embed")
            return {"embedded": 0}

        model = SentenceTransformer(MODEL_NAME)
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

        existing = [c.name for c in client.get_collections().collections]
        if COLLECTION not in existing:
            client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(
                    size=model.get_sentence_embedding_dimension(),
                    distance=Distance.COSINE,
                ),
            )

        vectors = model.encode(
            [r["readme_content"] for r in repos],
            batch_size=32, show_progress_bar=False,
        )

        def parse_topics(value):
            if isinstance(value, (bytes, bytearray)):
                value = value.decode("utf-8")
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    return []
            return value if isinstance(value, list) else []

        points = []
        for repo, vector in zip(repos, vectors):
            points.append(PointStruct(
                id=repo["repo_id"],
                vector=vector.tolist(),
                payload={
                    "repo_id": repo["repo_id"],
                    "repo_name": repo["repo_name"],
                    "primary_language": repo["primary_language"],
                    "topics": parse_topics(repo["topics"]),
                    # truncated text so RAG can ground answers on actual practices
                    # (US-5.3), not just rank by metadata.
                    "readme_content": (repo["readme_content"] or "")[:2000],
                    "enriched_at": repo["enriched_at"].isoformat()
                    if repo["enriched_at"] else None,
                },
            ))
        client.upsert(collection_name=COLLECTION, points=points)

        now = datetime.now(timezone.utc)
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO github_repos_embedded (repo_id, repo_name, model, embedded_at)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                model=VALUES(model), embedded_at=VALUES(embedded_at)
        """, [(r["repo_id"], r["repo_name"], MODEL_NAME, now) for r in repos])
        conn.commit()
        cursor.close()
        conn.close()

        print(f"embed_repos: {len(points)} repos embedded into Qdrant '{COLLECTION}'")
        return {"embedded": len(points)}

    task_embed_repos = PythonOperator(
        task_id="embed_repos",
        python_callable=run_embed_repos,
        provide_context=True,
    )

    def run_embed_hf_models(**context):
        """Embed HuggingFace model cards into Qdrant `huggingface_models`; track in hf_models_embedded."""
        import uuid
        from datetime import datetime, timezone

        import mysql.connector
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams
        from sentence_transformers import SentenceTransformer

        MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql")
        MYSQL_USER = os.getenv("MYSQL_USER", "root")
        MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
        MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ml_underground")
        QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
        QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
        COLLECTION = "huggingface_models"
        MODEL_NAME = "all-MiniLM-L6-v2"
        BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "100"))

        conn = mysql.connector.connect(
            host=MYSQL_HOST, user=MYSQL_USER,
            password=MYSQL_PASSWORD, database=MYSQL_DATABASE,
        )
        cursor = conn.cursor(dictionary=True)
        # Only LoRA-relevant models go into the Qdrant collection that powers
        # semantic search over LoRA practices (US-5.3). Organic HF models that
        # were not flagged are kept in MySQL but not embedded.
        cursor.execute("""
            SELECT m.model_id, m.base_model, m.pipeline_tag, m.library_name,
                   m.downloads, m.likes, m.card_content
            FROM huggingface_models_bronze m
            LEFT JOIN hf_models_embedded emb ON m.model_id = emb.model_id
            WHERE m.card_content IS NOT NULL
              AND m.is_lora_relevant = TRUE
              -- re-embed updated cards; newest-first so fresh models (matching
              -- newest-first ingestion) are never starved by the batch cap.
              AND (emb.model_id IS NULL OR m.last_modified > emb.embedded_at)
            ORDER BY m.created_at DESC
            LIMIT %s
        """, (BATCH_SIZE,))
        models = cursor.fetchall()
        cursor.close()

        if not models:
            conn.close()
            print("embed_hf_models: nothing new to embed")
            return {"embedded": 0}

        encoder = SentenceTransformer(MODEL_NAME)
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

        existing = [c.name for c in client.get_collections().collections]
        if COLLECTION not in existing:
            client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(
                    size=encoder.get_sentence_embedding_dimension(),
                    distance=Distance.COSINE,
                ),
            )

        vectors = encoder.encode(
            [m["card_content"] for m in models],
            batch_size=32, show_progress_bar=False,
        )

        points = []
        for row, vector in zip(models, vectors):
            points.append(PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, row["model_id"])),
                vector=vector.tolist(),
                payload={
                    "model_id": row["model_id"],
                    "base_model": row["base_model"],
                    "pipeline_tag": row["pipeline_tag"],
                    "library_name": row["library_name"],
                    "downloads": row["downloads"],
                    "likes": row["likes"],
                    # truncated card text so RAG can ground answers on it (US-5.3).
                    "card_content": (row["card_content"] or "")[:2000],
                },
            ))
        client.upsert(collection_name=COLLECTION, points=points)

        now = datetime.now(timezone.utc)
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO hf_models_embedded (model_id, model, embedded_at)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                model=VALUES(model), embedded_at=VALUES(embedded_at)
        """, [(m["model_id"], MODEL_NAME, now) for m in models])
        conn.commit()
        cursor.close()
        conn.close()

        print(f"embed_hf_models: {len(points)} models embedded into Qdrant '{COLLECTION}'")
        return {"embedded": len(points)}

    task_embed_hf_models = PythonOperator(
        task_id="embed_hf_models",
        python_callable=run_embed_hf_models,
        provide_context=True,
    )

    task_data_quality = BashOperator(
        task_id="data_quality_check",
        bash_command="/home/airflow/ge-venv/bin/python /opt/airflow/quality/ge_validate.py",
    )

    task_load_duckdb = BashOperator(
        task_id="load_to_duckdb",
        bash_command="/home/airflow/dbt-venv/bin/python /opt/airflow/dbt/load_to_duckdb.py",
    )

    task_dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=(
            "/home/airflow/dbt-venv/bin/dbt build "
            "--project-dir /opt/airflow/dbt --profiles-dir /opt/airflow/dbt"
        ),
    )

    # Embeddings (Qdrant/RAG) hang off hf_ingestion as a NON-BLOCKING side branch, so a
    # transient embedding failure no longer cascades into the DuckDB/dbt rebuild.
    task_enricher >> task_hf_ingestion
    task_hf_ingestion >> task_data_quality >> task_load_duckdb >> task_dbt_run
    task_hf_ingestion >> task_embed_repos >> task_embed_hf_models
