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

Replicated as-is to Snowflake `BRONZE` by `load_to_snowflake.py`.

## Silver — Snowflake (dbt tables)

| Model | Grain | Notes |
| --- | --- | --- |
| `repos` | one row per GitHub repo | conformed entity, `is_enriched` flag |
| `hf_models` | one row per HF model | `tag_count`, `is_fine_tune` |
| `github_hf_links` | one row per (repo, model) | `best_confidence` |
| `lora_configs_raw` | many rows per repo | `source` ∈ ast / json / yaml / regex / llm |
| `hf_models_lora_params` | one row per HF model | Variant D params |
| `repos_needing_llm_extraction` | one row per repo | target list for #7 |

## Gold — Snowflake (dbt tables)

| Model | Grain | Notes |
| --- | --- | --- |
| `repo_lora_params` | one row per repo | merged params + repo context |
| `repo_lora_outcomes` | one row per HF model | success score (#6 placeholder) |
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

A heavy-tail-dampened blend of model outcome signals:

    0.4·ln(downloads+1) + 0.3·ln(likes+1) + 0.3·ln(fine_tune_fan_out+1)

`fine_tune_fan_out` is how many other models declare this one as their
`base_model` (from `hf_model_tree`). The weights are a placeholder; the final
formula is #6.

### Four-quadrant practice stats (`lora_practice_stats`)

For each (parameter, value) bucket we compute `prevalence` (how many models use
it) and `avg_success_score`, then classify against the per-parameter medians:

| | works (score ≥ median) | fails (score < median) |
| --- | --- | --- |
| **common** (prevalence ≥ median) | table stakes | cargo cult |
| **rare** (prevalence < median) | **hidden insight** | dead end |

The `rare + works` quadrant is the core product output. It is built via
Variant D (HF-side params joined to outcomes on `model_id`), so no GitHub↔HF
linkage is required.

### LoRA params

The extracted hyperparameters (`rank_value`, `lora_alpha`, `target_modules`,
`learning_rate`, `optimizer`, ...) with exact types are documented in
[api-contract.md](api-contract.md) (`LoraParams`) and defined in
`de/migrations/006_repo_lora_params.sql` and `007_hf_models_lora_params.sql`.
