# Architecture

End-to-end, ML Underground collects LoRA training code from GitHub and LoRA
models from HuggingFace, lands them in a MySQL bronze layer, promotes them
through a DuckDB medallion (Bronze → Staging → Silver → Gold) with dbt, and
exposes the resulting marts through a FastAPI service and dashboard (deployed at
ml-underground.xyz).

## Components

| Layer | Tech | Role |
| --- | --- | --- |
| Sources | GitHub Search API, GitHub REST API, HuggingFace Hub | Discover + enrich LoRA repos and models |
| Orchestration | Apache Airflow (LocalExecutor) | The three DAGs below |
| Bronze | MySQL 8 | Raw collected entities + Airflow metadata |
| Warehouse | DuckDB + dbt | Staging → Silver → Gold marts (single `ML_UNDERGROUND.duckdb` file, path via `DUCKDB_PATH`) |
| Vector DB | Qdrant | README / model-card embeddings (payload carries text excerpts for RAG) |
| ML access | `ml/` (`data.py`, `scoring.py`, `practice_stats.py`, `rag/`) | DuckDB readers, pandas mirrors of the gold marts, RAG search + grounded answers |
| Quality | Great Expectations | Bronze validation gate |
| Monitoring | Prometheus + Grafana + custom exporter | Pipeline health |
| Serving | FastAPI + dashboard (`app/`) | The v1 API + dashboard; see [api-contract.md](api-contract.md) |

## Data flow

```
GitHub  (collector → enricher → files) ─┐
                                        ├─► MySQL bronze ─► DuckDB (dbt) ─► Gold marts
HuggingFace (collector → cards) ────────┘             └─► Qdrant (embeddings)
```

## Airflow DAGs

### `ml_underground_pipeline` — hourly

The warehouse path runs in order; the two embedding tasks hang off
`hf_ingestion` as a non-blocking side branch, so a transient embedding failure
does not cascade into DuckDB / dbt.

```
repo_enricher → hf_ingestion → data_quality_check → load_to_duckdb → dbt_run
                     └─► embed_repos → embed_hf_models        (side branch)
```

### `corpus_backfill_dag` — weekly (Sun 06:00 UTC, also manual)

Ordered and idempotent; `skip_*` params let a manual run re-trigger a single
stage.

```
lora_collector → hf_collector → files_fetcher → linker
```

### `lora_extraction_dag` — manual

```
extract_raw → extract_llm → merge_to_gold   (chained; extract_llm is the #7 LLM fallback)
extract_hf_cards                            (independent branch: HF adapter_config.json, confidence 1.0)
```

## Medallion layers (DuckDB)

The medallion lives in a single DuckDB file (catalog `ML_UNDERGROUND`,
default `/opt/airflow/dbt/ML_UNDERGROUND.duckdb` in the container, locally
`de/dbt/ml_underground/ML_UNDERGROUND.duckdb`, path via `DUCKDB_PATH`). dbt
uses the `dbt-duckdb` adapter. The schemas below are unchanged from the prior
Snowflake setup — only the warehouse engine changed.

| Schema | Built by | Contents |
| --- | --- | --- |
| BRONZE | `load_to_duckdb.py` | Replica of MySQL bronze |
| STAGING | dbt (views) | `stg_github_repos`, `stg_hf_models` |
| SILVER | dbt (tables) | Conformed entities + per-source extractions |
| GOLD | dbt (tables) | Params, outcomes, model tree, practice stats |

See [data-model.md](data-model.md) for the table-level detail.

## Key design decisions

- **Targeted collection over a firehose.** The original GH Archive → Kafka
  hourly firehose was retired (#35); the corpus now grows from GitHub Search and
  the HF Hub. The active corpus root is `github_repos_enriched`
  (`github_repos_bronze` is frozen).
- **Variant D — linkage-free practice stats.** `lora_practice_stats` is built
  from LoRA params extracted directly from HF model cards, joined to outcomes on
  `model_id`. It needs no GitHub↔HF record linkage, which de-risks the case where
  linkage yields too few high-confidence pairs.
- **Non-blocking embeddings.** The embedding tasks are a side branch off
  `hf_ingestion`, so vector-store hiccups never block the warehouse path.
- **Layered extraction.** Params are extracted with a source priority of
  AST > JSON > YAML > regex > LLM; the LLM fallback (#7) runs as the
  `extract_llm` task and no-ops when `ANTHROPIC_API_KEY` is absent.
- **Untrusted retrieved context.** RAG answers ground on the README/card text
  stored in the Qdrant payload — public-internet data, so it is length-capped,
  scrubbed of instruction-like patterns, and pinned inside
  `<retrieved_context>` delimiters as data-not-instructions (#52).

## Deployment

The full pipeline runs on AWS via Terraform (`infra/terraform`): EC2 for
Airflow, Qdrant, the app and monitoring; RDS MySQL for bronze; S3; Secrets
Manager. A lightweight serve-only public demo (dashboard + marts API,
`app/Dockerfile.web`) is deployed on Render (`render.yaml`) at
https://ml-underground.xyz; `infra/terraform-demo` is the AWS equivalent. The
DuckDB warehouse ships as a file — a baked demo, or the real corpus fetched via
`DUCKDB_URL`.
