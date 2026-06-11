# ML Underground API — contract v1 (proposed)

> **Status: not implemented yet.** This is a *proposed* contract derived from
> the live warehouse schema (DuckDB `GOLD`/`SILVER`) and the project spec.
> The frontend builds stubs against it; the future FastAPI app is implemented
> to match these exact names. Adjust here first, code second.

## Conventions

- Base path: `/api/v1`.
- Field names below are **exactly** the warehouse column names — match them 1:1
  on the frontend.
- List endpoints return a pagination envelope:
  `{ "items": [...], "total": int, "limit": int, "offset": int }`.
  Query params `limit` (default 50, max 200) and `offset` (default 0).
- Timestamps are ISO-8601 strings (`"2026-06-05T13:38:00Z"`).
- Errors use the FastAPI default body `{ "detail": "..." }` (404, 422, ...).
- Path params containing `/` (`repo_name` = `owner/name`, `model_id` =
  `user/model`) use a FastAPI `:path` converter, so they are passed raw.

## Shared objects

### `LoraParams`

Same shape on both the repo side and the model side. Every extracted field is
nullable (extraction may miss it).

| field | type | notes |
| --- | --- | --- |
| `rank_value` | int \| null | the LoRA `rank` (renamed — `rank` is a SQL keyword) |
| `lora_alpha` | int \| null | |
| `target_modules` | string[] \| null | e.g. `["q_proj","v_proj"]` (stored as a JSON array) |
| `learning_rate` | float \| null | may be in scientific notation, e.g. `2e-4` |
| `optimizer` | string \| null | e.g. `"adamw_torch"` |
| `lora_dropout` | float \| null | |
| `lora_bias` | string \| null | e.g. `"none"` |
| `scheduler` | string \| null | e.g. `"cosine"` |
| `batch_size` | int \| null | |
| `gradient_accumulation_steps` | int \| null | |
| `num_train_epochs` | int \| null | |
| `warmup_steps` | int \| null | |
| `bf16` | bool \| null | |
| `fp16` | bool \| null | |
| `gradient_checkpointing` | bool \| null | |
| `merge_and_unload` | bool \| null | |
| `param_sources` | object \| null | source per field, e.g. `{"rank_value":"ast","optimizer":"yaml"}` (priority `ast` > `json` > `yaml` > `regex` > `llm`) |
| `total_params_extracted` | int | how many fields were found |
| `extraction_confidence` | float | `0.00`–`1.00` |
| `extracted_at` | timestamp | |

### `Repo`

`repo_id` (int), `repo_name` (str `"owner/name"`), `description` (str | null),
`primary_language` (str | null), `topics` (string[]), `license` (str | null),
`homepage` (str | null), `star_count` (int), `forks_count` (int),
`open_issues_count` (int), `contributors_count` (int), `commit_count_30d` (int),
`has_tests` (bool), `has_ci` (bool), `is_fork` (bool), `is_archived` (bool),
`readme_length` (int), `repo_created_at` (timestamp), `pushed_at` (timestamp),
`enriched_at` (timestamp | null), `is_enriched` (bool).

### `HFModel`

`model_id` (str `"user/model"`), `author` (str), `base_model` (str | null),
`pipeline_tag` (str | null), `library_name` (str | null), `downloads` (int),
`likes` (int), `tags` (string[]), `tag_count` (int), `is_fine_tune` (bool),
`created_at` (timestamp), `last_modified` (timestamp).

### `Outcome`

`HFModel` plus `fine_tune_fan_out` (int — how many models declare this one as
their `base_model`), the per-signal percentiles `downloads_pct` / `likes_pct` /
`fan_out_pct` (float, 0–1), and `composite_success_score` (float, **0–1**).

> `composite_success_score` is a percentile blend
> (`0.55·downloads_pct + 0.35·likes_pct + 0.10·fan_out_pct`; weights live in
> `gold/repo_lora_outcomes.sql`). It is a 0–1 value — render it as `0.xx` or a
> percentage, **not** as `x/10`. It measures relative popularity (correlation,
> not causation).

### `PracticeStat` (an "insight")

`param_name` (str), `param_value` (str), `prevalence` (int — how many models use
this value), `avg_success_score` (float, 0–1), `avg_score_vs_base` (float — mean
of each model's score minus its `base_model` peer mean; this is the works/fails
axis), `score_lift` (float — bucket mean minus the parameter's pooled mean, an
effect size), `sample_ok` (bool — `prevalence >= 3`; treat `false` buckets as
noise, not insights), `quadrant` (enum — exact strings: `"common+works"`,
`"common+fails"`, `"rare+works"`, `"rare+fails"`).

## Endpoints

### `GET /api/v1/insights`

The four-quadrant practice table — the core product value.

Query: `quadrant` (filter, e.g. `rare+works`), `param_name` (filter),
`min_prevalence` (int), `sample_ok` (bool — hide noisy small buckets), `sort`
(`avg_success_score` | `prevalence` | `score_lift`, default
`avg_success_score`), `order` (`asc` | `desc`, default `desc`).

Returns an envelope of `PracticeStat`.

> URL-encode the `+` in quadrant values (`rare%2Bworks`) — a raw `+` decodes as
> a space.

### `GET /api/v1/repos`

LoRA repos with their extracted params.

Query: `param` + `value` (e.g. `optimizer=adamw_8bit`), `language`, `has_tests`
(bool), `q` (text in name/description), `sort` (`star_count` |
`extraction_confidence`), `order`.

Returns an envelope of `Repo & { lora_params: LoraParams }`.

### `GET /api/v1/repos/{repo_name:path}`

Single repo detail.

Returns `Repo & { lora_params: LoraParams, linked_models: {model_id,
best_confidence}[] }`.

### `GET /api/v1/models`

HF models with outcomes.

Query: `base_model`, `pipeline_tag`, `library_name`, `min_downloads`, `sort`
(`composite_success_score` | `downloads` | `likes` | `fine_tune_fan_out`,
default `composite_success_score`), `order`.

Returns an envelope of `Outcome`.

### `GET /api/v1/models/{model_id:path}`

Single model detail.

Returns `Outcome & { lora_params: LoraParams, fine_tune_models: string[] }`
(`fine_tune_models` = the children that derive from it).

### `GET /api/v1/search`

Semantic search over READMEs / model cards (Qdrant).

Query: `q` (required), `type` (`repos` | `models` | `all`, default `all`),
`limit`.

Returns `{ "items": [ { "score": float, "type": "repo" | "model", "object":
Repo | HFModel } ] }`.

> Only repos and models live in the search index. Practice insights
> (`PracticeStat`) are **not** searchable — filter them via `/insights` instead.

### `GET /api/v1/ask`

RAG answer over the corpus (backed by `ml.rag.answer`): semantic retrieval,
then a grounded LLM answer that cites the repo_name / model_id it drew from.

Query: `q` (required), `top_k` (int, default 5).

Returns `{ "answer": str, "sources": [ ...same items as /search ] }`. Needs
`ANTHROPIC_API_KEY` server-side; expect noticeably higher latency than
`/search`.

### `GET /api/v1/stats/summary`

Dashboard KPIs (hero numbers).

Returns `{ "repos_total": int, "repos_enriched": int, "hf_models_total": int,
"links_total": int, "repos_with_params": int, "extraction_coverage": float }`.

## Examples

`GET /api/v1/insights?quadrant=rare%2Bworks&sort=avg_success_score`

```json
{
  "items": [
    { "param_name": "optimizer", "param_value": "adamw_8bit",
      "prevalence": 12, "avg_success_score": 0.74, "avg_score_vs_base": 0.21,
      "score_lift": 0.18, "sample_ok": true, "quadrant": "rare+works" },
    { "param_name": "rank_value", "param_value": "128",
      "prevalence": 9, "avg_success_score": 0.7, "avg_score_vs_base": 0.16,
      "score_lift": 0.12, "sample_ok": true, "quadrant": "rare+works" }
  ],
  "total": 2, "limit": 50, "offset": 0
}
```

`GET /api/v1/models?sort=composite_success_score` (one item shown)

```json
{
  "items": [
    { "model_id": "alice/llama3-finance-lora", "author": "alice",
      "base_model": "meta-llama/Llama-3.1-8B", "pipeline_tag": "text-generation",
      "library_name": "peft", "downloads": 48213, "likes": 312,
      "tags": ["lora", "finance"], "tag_count": 2, "is_fine_tune": true,
      "created_at": "2026-02-10T08:00:00Z", "last_modified": "2026-05-30T12:00:00Z",
      "fine_tune_fan_out": 7, "downloads_pct": 0.98, "likes_pct": 0.95,
      "fan_out_pct": 0.99, "composite_success_score": 0.97,
      "lora_params": {
        "rank_value": 64, "lora_alpha": 16,
        "target_modules": ["q_proj", "v_proj"], "learning_rate": 0.0002,
        "optimizer": "adamw_8bit", "extraction_confidence": 1.0,
        "param_sources": { "rank_value": "json" },
        "extracted_at": "2026-05-31T00:00:00Z"
      }
    }
  ],
  "total": 1, "limit": 50, "offset": 0
}
```

## Source of truth

Field names and types come from the warehouse marts:

- `LoraParams` — `GOLD.REPO_LORA_PARAMS` / `SILVER.HF_MODELS_LORA_PARAMS`
  (DDL in `de/migrations/006_repo_lora_params.sql`, `007_hf_models_lora_params.sql`).
- `Repo` — `SILVER.REPOS` (`de/dbt/ml_underground/models/silver/repos.sql`).
- `HFModel` — `SILVER.HF_MODELS`.
- `Outcome` — `GOLD.REPO_LORA_OUTCOMES`.
- `PracticeStat` — `GOLD.LORA_PRACTICE_STATS`.
