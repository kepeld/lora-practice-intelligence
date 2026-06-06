# Architecture

End-to-end, ML Underground collects LoRA training code from GitHub and LoRA
models from HuggingFace, lands them in a MySQL bronze layer, promotes them
through a Snowflake medallion (Bronze → Staging → Silver → Gold) with dbt, and
exposes the resulting marts for analysis and a (planned) web dashboard.

## Components

| Layer | Tech | Role |
| --- | --- | --- |
| Sources | GitHub Search API, GitHub REST API, HuggingFace Hub | Discover + enrich LoRA repos and models |
| Orchestration | Apache Airflow (LocalExecutor) | The three DAGs below |
| Bronze | MySQL 8 | Raw collected entities + Airflow metadata |
| Warehouse | Snowflake + dbt | Staging → Silver → Gold marts |
| Vector DB | Qdrant | README / model-card embeddings for semantic search |
| Quality | Great Expectations | Bronze validation gate |
| Monitoring | Prometheus + Grafana + custom exporter | Pipeline health |
| Serving (planned) | FastAPI + dashboard | See [api-contract.md](api-contract.md) |

## Data flow

```
GitHub  (collector → enricher → files) ─┐
                                        ├─► MySQL bronze ─► Snowflake (dbt) ─► Gold marts
HuggingFace (collector → cards) ────────┘             └─► Qdrant (embeddings)
```

## Airflow DAGs

### `ml_underground_pipeline` — hourly

The warehouse path runs in order; the two embedding tasks hang off
`hf_ingestion` as a non-blocking side branch, so a transient embedding failure
does not cascade into Snowflake / dbt.

```
repo_enricher → hf_ingestion → data_quality_check → load_to_snowflake → dbt_run
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

## Medallion layers (Snowflake)

| Schema | Built by | Contents |
| --- | --- | --- |
| BRONZE | `load_to_snowflake.py` | Replica of MySQL bronze |
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
