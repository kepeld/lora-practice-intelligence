# LoRA Practice Intelligence

A data platform that mines rare LoRA training practices from GitHub and
validates them against HuggingFace model outcome metrics (downloads, likes,
fine-tune fan-out). The goal: surface "rare-but-works" LoRA techniques —
hyperparameter recipes, training tricks, dataset patterns — before they
spread.

## How it works

```
                 GitHub                                HuggingFace
                    │                                       │
   ┌────────────────┴───────────────┐       ┌───────────────┴────────────────┐
   │ Targeted GitHub Search         │       │ Hourly hf_ingestion            │
   │ (targeted_lora_collector)      │       │ + targeted LoRA backfill       │
   │ → enrich via GitHub API        │       │                                │
   └────────────────┬───────────────┘       └───────────────┬────────────────┘
                    ▼                                       ▼
              MySQL bronze ◄─── github_hf_linker ───► MySQL bronze
              (repos, files,         ┌─────────────┐ (HF models)
               readmes)              │ silver +    │
                    │                │ gold marts  │
                    └──► Snowflake ──┤ on Snowflake│──► success score,
                                     │ via dbt     │     rare-but-works,
                                     └─────────────┘     practice index
```

## Repository layout

```
ua-palantir/
├── de/                                  # Data engineering
│   ├── airflow/
│   │   ├── Dockerfile                   # Airflow image (extra deps)
│   │   └── dags/
│   │       ├── ml_underground_dag.py        # Hourly pipeline (7 tasks)
│   │       ├── corpus_backfill_dag.py       # Weekly LoRA corpus backfill
│   │       └── lora_extraction_dag.py       # Manual LoRA hyperparameter extract
│   ├── ingestion/                       # Collectors / enricher / linker / extractor
│   ├── dbt/ml_underground/              # Staging → Silver → Gold (Snowflake)
│   ├── quality/                         # Great Expectations bronze suites
│   ├── migrations/                      # MySQL schema migrations (001..007)
│   ├── mysql/init.sql                   # Bootstrap schema
│   └── tests/                           # pytest (filters)
├── ml/                                  # ML / RAG — prompts, scoring, RAG
├── infra/
│   ├── exporter/                        # Custom Prometheus exporter
│   ├── grafana/                         # Auto-provisioned dashboards
│   └── prometheus.yml
├── docker-compose.yml                   # Local stack (profiles: de, monitor, all)
└── README.md
```

## Getting started

### Prerequisites
- Docker Desktop
- Python 3.11+ via `pyenv`
- `uv` for package management
- A GitHub token (`public_repo` scope), a Snowflake account, and the
  HuggingFace Hub anonymous client (no token needed).

### Configure secrets

Copy `.env.example` to `.env` and fill in:
- `GITHUB_TOKEN` — GitHub personal access token
- `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_DATABASE`,
  `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_ROLE`


### Start the stack

```bash
# Full data-engineering stack (MySQL, Airflow, Qdrant)
docker compose --profile de up -d

# + monitoring (Prometheus, Grafana, pipeline-exporter)
docker compose --profile de --profile monitor up -d
```

### Service URLs (local)

| Service     | URL                       | Credentials             |
| ----------- | ------------------------- | ----------------------- |
| Airflow     | http://localhost:8081     | admin / admin           |
| Qdrant      | http://localhost:6333     | —                       |
| Grafana     | http://localhost:3000     | admin / admin           |
| Prometheus  | http://localhost:9090     | —                       |

## Pipelines

### Hourly DAG — `ml_underground_pipeline`

Runs every hour, 7 tasks. The warehouse path runs in order, with the two
embedding tasks hanging off `hf_ingestion` as a **non-blocking side branch** —
a transient embedding failure no longer cascades into Snowflake / dbt:

```
repo_enricher → hf_ingestion → data_quality_check → load_to_snowflake → dbt_run
                     └─► embed_repos → embed_hf_models   (side branch)
```

1. `repo_enricher` — enrich LoRA repos from the `lora_search_discovery`
   backlog via the GitHub API
2. `hf_ingestion` — newest HuggingFace LoRA models + cards (retry-hardened)
3. `data_quality_check` — Great Expectations validation of bronze
4. `load_to_snowflake` — replicate MySQL bronze → Snowflake BRONZE
5. `dbt_run` — build Silver / Gold marts
6. `embed_repos` — repo READMEs → Qdrant `github_repos` *(US-5.3, side branch)*
7. `embed_hf_models` — HF model cards → Qdrant `huggingface_models` *(US-5.3, side branch)*

### Weekly backfill DAG — `corpus_backfill_dag`

Runs Sundays 06:00 UTC (also manual-triggerable). One ordered, idempotent DAG
that keeps the LoRA corpus growing as GitHub Search / HF Hub surface new
candidates:

| Step             | Purpose                                                |
| ---------------- | ------------------------------------------------------ |
| `lora_collector` | Seed corpus with LoRA GitHub repos via Search API      |
| `hf_collector`   | Seed corpus with LoRA models via HF Hub                |
| `files_fetcher`  | Pull training scripts + configs from LoRA repos        |
| `linker`         | Derive GitHub ↔ HF links (regex + fuzzy, no API calls) |

`skip_*` params let a manual run re-trigger just one stage.

### Manual DAG — `lora_extraction_dag`

Extracts LoRA hyperparameters. `extract_raw` runs the layered extractor over
`github_files` into `lora_configs_raw`, then `merge_to_gold` priority-merges
into `repo_lora_params` — these two are chained (`extract_raw → merge_to_gold`).
In parallel, the `extract_hf_cards` task fetches each LoRA model's
`adapter_config.json` (PEFT canonical params, confidence 1.0) into
`hf_models_lora_params`; it is an independent branch (independent input HF
cards, independent output) and is not sequenced between `extract_raw` and
`merge_to_gold`.

## Data model

### MySQL bronze (DE owns)

| Table                       | What it holds                                |
| --------------------------- | -------------------------------------------- |
| `github_repos_bronze`       | Retired/frozen legacy table — not populated by the current pipeline (corpus root is now `github_repos_enriched`) |
| `github_repos_enriched`     | Active corpus root — GitHub API enrichment + LoRA classification |
| `huggingface_models_bronze` | HF models (organic + targeted_lora flag)     |
| `lora_search_discovery`     | LoRA-collector discovery log                 |
| `hf_lora_search_discovery`  | HF LoRA-collector discovery log              |
| `github_hf_links`           | GitHub repo ↔ HF model links + confidence    |
| `github_files`              | Training scripts + config files per repo     |

### Snowflake medallion

| Schema    | Built by                | Highlights                                                          |
| --------- | ----------------------- | ------------------------------------------------------------------- |
| `BRONZE`  | `load_to_snowflake.py`  | Replica of MySQL bronze                                             |
| `STAGING` | dbt (views)             | `stg_github_repos`, `stg_hf_models`                                 |
| `SILVER`  | dbt (tables)            | `repos`, `hf_models`, `hf_models_lora_params`, `github_hf_links`, `lora_configs_raw`, `repos_needing_llm_extraction` |
| `GOLD`    | dbt (tables)            | `repo_lora_params`, `repo_lora_outcomes`, `hf_model_tree`, `lora_practice_stats` |

### Qdrant collections *(US-5.3)*

| Collection            | Content                              | Point ID            |
| --------------------- | ------------------------------------ | ------------------- |
| `github_repos`        | enriched repo README embeddings      | `repo_id`           |
| `huggingface_models`  | HF model card embeddings             | `uuid5(model_id)`   |

`all-MiniLM-L6-v2`, 384-dim, cosine.

## Monitoring

`docker compose --profile de --profile monitor up -d` brings up Prometheus,
Grafana, and a custom `pipeline-exporter` that queries MySQL (bronze row
counts), Qdrant (embedding counts) and the Airflow metadata DB (last
successful DAG run). Grafana auto-provisions the **ML Underground Pipeline**
dashboard.

## Testing

```bash
uv pip install -r requirements-dev.txt
uv run pytest de/tests/
```