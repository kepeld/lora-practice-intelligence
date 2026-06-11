# Data model

## Bronze — MySQL (DE owns)

| Table | Holds |
| --- | --- |
| `github_repos_enriched` | Active corpus root — GitHub API enrichment + LoRA classification |
| `github_repos_bronze` | Frozen legacy table — not populated by the current pipeline |
| `huggingface_models_bronze` | HF models (organic + `targeted_lora` flag) + model cards |
| `lora_search_discovery` | GitHub LoRA-collector discovery log |
| `hf_lora_search_discovery` | HF LoRA-collector discovery log |
| `github_hf_links` | GitHub repo ↔ HF model links + confidence |
| `github_files` | Training scripts + config files per repo |
| `lora_configs_raw` | Per-source raw param extractions (many rows per repo) |
| `repo_lora_params` | Per-repo LoRA params after the priority merge |
| `hf_models_lora_params` | Per-HF-model LoRA params (Variant D) |
| `github_repos_embedded`, `hf_models_embedded` | Qdrant embedding bookkeeping |

Replicated as-is into the DuckDB warehouse's `BRONZE` schema by
`load_to_duckdb.py`. The warehouse is a single DuckDB file (catalog
`ML_UNDERGROUND`) at `/opt/airflow/dbt/ML_UNDERGROUND.duckdb` in the container
(locally `de/dbt/ml_underground/ML_UNDERGROUND.duckdb`), resolved via the
`DUCKDB_PATH` env var. (Migrated from Snowflake to DuckDB.)

## Silver — DuckDB (dbt tables)

| Model | Grain | Notes |
| --- | --- | --- |
| `repos` | one row per GitHub repo | conformed entity, `is_enriched` flag |
| `hf_models` | one row per HF model | `tag_count`, `is_fine_tune` |
| `github_hf_links` | one row per (repo, model) | `best_confidence` |
| `lora_configs_raw` | many rows per repo | `source` ∈ ast / json / yaml / regex / llm |
| `hf_models_lora_params` | one row per HF model | Variant D params |
| `repos_needing_llm_extraction` | one row per repo | target list for #7 |

## Gold — DuckDB (dbt tables)

| Model | Grain | Notes |
| --- | --- | --- |
| `repo_lora_params` | one row per repo | merged params + repo context |
| `repo_lora_outcomes` | one row per HF model | success score (#6) |
| `hf_model_tree` | one row per `base_model` | fine-tune fan-out |
| `lora_practice_stats` | one row per (param, value) | four quadrants (#10) |

## Qdrant collections

| Collection | Content | Point ID |
| --- | --- | --- |
| `github_repos` | enriched repo README embeddings | `repo_id` |
| `huggingface_models` | HF model card embeddings | `uuid5(model_id)` |

`all-MiniLM-L6-v2`, 384-dim, cosine.

## Analytics logic

### Success score (`repo_lora_outcomes.composite_success_score`)

Each signal is mapped to its population percentile (0–1 via `percent_rank()`),
then blended:

    0.3·downloads_pct + 0.2·likes_pct + 0.5·fan_out_pct

`fan_out_pct` carries the most weight because fine-tune fan-out — how many other
models declare this one as their `base_model` (from `hf_model_tree`) — is the
hardest signal to game. Percentile-normalising keeps every signal on the same
[0,1] scale, so the weights mean what they say (#6).

### Four-quadrant practice stats (`lora_practice_stats`)

For each (parameter, value) bucket we compute `prevalence` (how many models use
it) and `avg_score_vs_base` — the mean of each model's score minus the mean of
its `base_model` peers, so a value is credited for beating peers on the *same*
base model rather than for riding a popular one. Buckets are classified against
the per-parameter medians of those two quantities:

| | works (`avg_score_vs_base` ≥ median) | fails (< median) |
| --- | --- | --- |
| **common** (prevalence ≥ median) | table stakes | cargo cult |
| **rare** (prevalence < median) | **hidden insight** | dead end |

`sample_ok` flags buckets backed by at least 3 models, so a `rare + works` cell
with a single model reads as noise rather than a hidden gem.

The `rare + works` quadrant is the core product output. It is built via
Variant D (HF-side params joined to outcomes on `model_id`), so no GitHub↔HF
linkage is required.

### LoRA params

The extracted hyperparameters (`rank_value`, `lora_alpha`, `target_modules`,
`learning_rate`, `optimizer`, ...) with exact types are documented in
[api-contract.md](api-contract.md) (`LoraParams`) and defined in
`de/migrations/006_repo_lora_params.sql` and `007_hf_models_lora_params.sql`.
