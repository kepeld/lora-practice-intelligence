# Test scenarios

Basic test scenarios for ML Underground (LoRA Practice Intelligence). Each
scenario lists steps, the expected result, and — where the check is automated —
the pytest that pins it. Task tracking lives on the
[kanban board](https://github.com/users/AvdieienkoDmytro/projects/1).

## Environments

| Environment | How to get it |
| --- | --- |
| Demo warehouse | `python -m app.demo_seed` (small, deterministic — used by the automated suite) |
| Real warehouse | the pipeline's `ML_UNDERGROUND.duckdb` (DuckDB file, `DUCKDB_PATH`) |
| Full RAG stack | Qdrant on `:6333` with the two collections + `ANTHROPIC_API_KEY` in `.env` |

Run the app: `uvicorn app.main:app --port 8000` (or `docker compose --profile app up -d`).

## Automated suite

```bash
python -m pytest de/tests/    # 129 tests
```

| File | Covers |
| --- | --- |
| `test_app_api.py` | API contract: envelopes, filters, sorts, evidence, 404/422/503 paths |
| `test_rag.py` | retrieval formatting, RAG grounding, injection scrub, warehouse enrichment |
| `test_practice_stats.py`, `test_scoring.py` | quadrant + success-score logic (pandas mirrors of dbt) |
| `test_lora_extractor.py`, `test_llm_extractor.py`, `test_filters.py`, `test_hf_utils.py` | extraction layers and ingestion helpers |

## Dashboard (E2E, browser)

### TS-01 — Dashboard loads with corpus KPIs
1. Open `/`.
2. **Expected:** header, six KPI tiles with non-zero counts (repos, models,
   links, coverage %), insight cards below. No console errors.
   *(Automated root check: `test_app_api.py::test_dashboard_served_at_root`.)*

### TS-02 — Quadrant filtering
1. On *Practice insights*, click the `Hidden gems` chip.
2. **Expected:** only `rare+works` cards remain, chip is highlighted gold;
   clicking `All` restores the full list. No page reload.
   *(API side: `test_insights_quadrant_filter_tolerates_space`.)*

### TS-03 — Low-sample gate
1. Toggle `hide low-sample` off and on.
2. **Expected:** off shows extra cards with a dashed `low sample` badge;
   on hides every card with `prevalence < 3`.
   *(API side: `test_insights_sample_ok_filter`.)*

### TS-04 — Evidence drawer
1. Click any insight card (e.g. `optimizer = adamw`).
2. **Expected:** a right-side drawer lists real HF models using that exact
   value, sorted by success score; each links to `huggingface.co/<user>/<model>`
   (slash intact, no `%2F`).
3. Esc or the scrim closes the drawer.
   *(API side: `test_insight_evidence_models`, boolean/legacy variants.)*

### TS-05 — Models explorer
1. In *Models*, sort by downloads, then filter by a base model.
2. Click a row.
3. **Expected:** table re-renders without reload; the row expands into the
   extracted recipe chips (`rank_value = 64`, `bf16 = true`, …) and a working
   HuggingFace link.
   *(API side: `test_models_envelope_with_nested_params`, `test_models_filter_by_base`.)*

### TS-06 — Repos explorer
1. In *Repositories*, type a name fragment, toggle `has tests`.
2. Click a row.
3. **Expected:** live filtering; the expanded row shows the recipe, linked HF
   models with confidences, and a GitHub link.
   *(API side: `test_repos_filters_and_nested_params`, `test_repo_detail_linked_models`.)*

### TS-07 — Semantic search *(needs Qdrant)*
1. Search `8-bit adamw optimizer for qlora`.
2. **Expected:** mixed repo/model results with similarity scores, each linking
   to its GitHub/HF page. Insights are *not* in the search index by design.

### TS-08 — RAG ask *(needs Qdrant + API key)*
1. Ask `which optimizer do successful qlora fine-tunes use?`.
2. **Expected:** a grounded answer that cites warehouse facts (validated
   rare-but-works practices with scores, per-source extracted recipes) and
   lists the retrieved sources below. The model must *not* invent values
   absent from the context; when the context is insufficient it must say so.
   *(Prompt side: `test_rag.py::test_answer_enriches_hits_with_warehouse_context`.)*

## Degraded modes (honest failure states)

### TS-09 — No warehouse file
1. Point `DUCKDB_PATH` at a missing file, open `/`.
2. **Expected:** a banner explains the warehouse is unreachable and shows the
   demo-seed command; no blank screens or stack traces.

### TS-10 — Vector stack down
1. Stop Qdrant (or remove `qdrant-client`), run a search.
2. **Expected:** HTTP 503 with a human-readable `detail`; the rest of the
   dashboard keeps working.
   *(Automated: `test_search_degrades_to_503` — simulated outage.)*

### TS-11 — No Anthropic key
1. Unset `ANTHROPIC_API_KEY`, use *Ask*.
2. **Expected:** HTTP 503 `ANTHROPIC_API_KEY is not configured on the server`;
   search still works.
   *(Automated: `test_ask_without_key_is_503`.)*

## API contract spot-checks

### TS-12 — Pagination envelope and limits
`GET /api/v1/insights?limit=5&offset=5` → `{items, total, limit, offset}`,
at most 5 items; `limit=500` → 422.
*(Automated: `test_insights_envelope_and_sort`.)*

### TS-13 — Quadrant URL encoding
`?quadrant=rare%2Bworks` and `?quadrant=rare+works` return identical results
(a raw `+` decodes as a space and is tolerated).
*(Automated: `test_insights_quadrant_filter_tolerates_space`.)*

### TS-14 — Validation and 404s
Unknown sort → 422; unknown parameter in the evidence path → 422 (no SQL
injection through `{param}`); missing model/repo detail → 404.
*(Automated: `test_insights_bad_sort_is_422`,
`test_insight_evidence_unknown_param_is_422`, `test_model_detail_and_404`.)*

## Pipeline smoke (Airflow)

### TS-15 — Hourly pipeline degrades gracefully
Trigger `ml_underground_pipeline` with Qdrant stopped.
**Expected:** the embedding side branch fails without blocking
`data_quality_check → load_to_duckdb → dbt_run` (non-blocking branch design).

### TS-16 — LLM extraction is optional and idempotent
Trigger `lora_extraction_dag` without `ANTHROPIC_API_KEY`.
**Expected:** `extract_llm` no-ops with a warning, the DAG still succeeds;
re-running the DAG does not duplicate rows (upsert keys).
*(Extractor logic: `test_llm_extractor.py`.)*

## Verification log

- 2026-06-12 — full suite **129 passed**; TS-01…TS-08 executed manually against
  the real warehouse (328 MB DuckDB), restored Qdrant snapshots (5 596 repo +
  8 933 model vectors) and the live Anthropic key; TS-09…TS-11 exercised via
  the automated suite and live degradation checks during development.
