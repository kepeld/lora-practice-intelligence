"""/api/v1 endpoints per docs/api-contract.md, over the DuckDB marts.

Sort columns are whitelisted; filters are parameterized. /search and /ask
degrade to 503 with a clear detail when the vector stack or ANTHROPIC_API_KEY
is unavailable, so the rest of the app keeps working.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query

from . import db

router = APIRouter(prefix="/api/v1")

QUADRANTS = {"common+works", "common+fails", "rare+works", "rare+fails"}
INSIGHT_SORTS = {"avg_success_score", "prevalence", "score_lift"}
MODEL_SORTS = {"composite_success_score", "downloads", "likes", "fine_tune_fan_out"}
REPO_SORTS = {"star_count", "extraction_confidence"}

# LoraParams fields nested under repos/models (matches the contract).
PARAM_FIELDS = (
    "rank_value", "lora_alpha", "target_modules", "learning_rate", "optimizer",
    "lora_dropout", "lora_bias", "scheduler", "batch_size",
    "gradient_accumulation_steps", "num_train_epochs", "warmup_steps",
    "bf16", "fp16", "gradient_checkpointing", "merge_and_unload",
    "param_sources", "total_params_extracted", "extraction_confidence",
    "extracted_at",
)
# Parameters filterable / drillable by name (the 14 the stats mart unions,
# plus the rest of the extracted set — all real columns).
FILTERABLE_PARAMS = set(PARAM_FIELDS) - {"param_sources", "total_params_extracted",
                                         "extraction_confidence", "extracted_at"}


def _order(order: str) -> str:
    if order not in ("asc", "desc"):
        raise HTTPException(422, "order must be 'asc' or 'desc'")
    return order.upper()


def _check_warehouse():
    if not db.warehouse_available():
        raise HTTPException(
            503,
            f"warehouse file not found at {db.warehouse_path()} — run the "
            "pipeline (load_to_duckdb + dbt) or `python -m app.demo_seed`",
        )


def _pick_params(row: dict) -> dict:
    return {k: row.get(k) for k in PARAM_FIELDS}


@router.get("/stats/summary")
def stats_summary():
    _check_warehouse()
    repos_total = db.scalar("SELECT count(*) FROM SILVER.REPOS") or 0
    repos_enriched = db.scalar(
        "SELECT count(*) FROM SILVER.REPOS WHERE is_enriched") or 0
    hf_models_total = db.scalar("SELECT count(*) FROM SILVER.HF_MODELS") or 0
    links_total = db.scalar("SELECT count(*) FROM SILVER.GITHUB_HF_LINKS") or 0
    repos_with_params = db.scalar("SELECT count(*) FROM GOLD.REPO_LORA_PARAMS") or 0
    repos_with_files = db.scalar(
        "SELECT count(DISTINCT repo_full_name) FROM BRONZE.GITHUB_FILES") or 0
    coverage = round(repos_with_params / repos_with_files, 3) if repos_with_files else 0.0
    return {
        "repos_total": repos_total,
        "repos_enriched": repos_enriched,
        "hf_models_total": hf_models_total,
        "links_total": links_total,
        "repos_with_params": repos_with_params,
        "extraction_coverage": coverage,
    }


@router.get("/insights")
def insights(quadrant: str | None = None, param_name: str | None = None,
             min_prevalence: int | None = None, sample_ok: bool | None = None,
             sort: str = "avg_success_score", order: str = "desc",
             limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    _check_warehouse()
    if sort not in INSIGHT_SORTS:
        raise HTTPException(422, f"sort must be one of {sorted(INSIGHT_SORTS)}")
    where, params = ["1=1"], []
    if quadrant:
        wanted = quadrant.replace(" ", "+")   # '+' often decodes as a space
        if wanted not in QUADRANTS:
            raise HTTPException(422, f"quadrant must be one of {sorted(QUADRANTS)}")
        where.append("quadrant = ?")
        params.append(wanted)
    if param_name:
        where.append("param_name = ?")
        params.append(param_name)
    if min_prevalence is not None:
        where.append("prevalence >= ?")
        params.append(min_prevalence)
    if sample_ok is not None:
        where.append("sample_ok = ?")
        params.append(sample_ok)
    cond = " AND ".join(where)
    total = db.scalar(f"SELECT count(*) FROM GOLD.LORA_PRACTICE_STATS WHERE {cond}", params)
    rows = db.query(
        f"SELECT * FROM GOLD.LORA_PRACTICE_STATS WHERE {cond} "
        f"ORDER BY {sort} {_order(order)} NULLS LAST LIMIT ? OFFSET ?",
        params + [limit, offset])
    return db.envelope(rows, total, limit, offset)


@router.get("/insights/{param_name}/{param_value}/models")
def insight_models(param_name: str, param_value: str,
                   limit: int = Query(10, ge=1, le=50)):
    """Evidence drill-down: real HF models that use this parameter value."""
    _check_warehouse()
    if param_name not in FILTERABLE_PARAMS:
        raise HTTPException(422, f"unknown parameter {param_name!r}")
    rows = db.query(
        f"""SELECT p.model_id, o.base_model, o.pipeline_tag, o.library_name,
                   o.downloads, o.likes, o.fine_tune_fan_out,
                   o.composite_success_score
            FROM SILVER.HF_MODELS_LORA_PARAMS p
            JOIN GOLD.REPO_LORA_OUTCOMES o USING (model_id)
            WHERE CAST(p.{param_name} AS VARCHAR) = ?
            ORDER BY o.composite_success_score DESC NULLS LAST LIMIT ?""",
        [param_value, limit])
    return {"items": rows}


def _attach_model_params(rows: list[dict]) -> list[dict]:
    ids = [r["model_id"] for r in rows]
    if not ids:
        return rows
    marks = ", ".join(["?"] * len(ids))
    by_id = {p["model_id"]: _pick_params(p) for p in db.query(
        f"SELECT * FROM SILVER.HF_MODELS_LORA_PARAMS WHERE model_id IN ({marks})", ids)}
    for r in rows:
        r["lora_params"] = by_id.get(r["model_id"])
    return rows


_MODELS_SELECT = """
    SELECT o.*, m.tags, m.tag_count, m.created_at, m.last_modified
    FROM GOLD.REPO_LORA_OUTCOMES o
    LEFT JOIN SILVER.HF_MODELS m USING (model_id)
"""


@router.get("/models")
def models(base_model: str | None = None, pipeline_tag: str | None = None,
           library_name: str | None = None, min_downloads: int | None = None,
           sort: str = "composite_success_score", order: str = "desc",
           limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    _check_warehouse()
    if sort not in MODEL_SORTS:
        raise HTTPException(422, f"sort must be one of {sorted(MODEL_SORTS)}")
    where, params = ["1=1"], []
    if base_model:
        where.append("o.base_model = ?")
        params.append(base_model)
    if pipeline_tag:
        where.append("o.pipeline_tag = ?")
        params.append(pipeline_tag)
    if library_name:
        where.append("o.library_name = ?")
        params.append(library_name)
    if min_downloads is not None:
        where.append("o.downloads >= ?")
        params.append(min_downloads)
    cond = " AND ".join(where)
    total = db.scalar(
        f"SELECT count(*) FROM GOLD.REPO_LORA_OUTCOMES o WHERE {cond}", params)
    rows = db.query(
        f"{_MODELS_SELECT} WHERE {cond} "
        f"ORDER BY o.{sort} {_order(order)} NULLS LAST LIMIT ? OFFSET ?",
        params + [limit, offset])
    return db.envelope(_attach_model_params(rows), total, limit, offset)


@router.get("/models/{model_id:path}")
def model_detail(model_id: str):
    _check_warehouse()
    rows = db.query(f"{_MODELS_SELECT} WHERE o.model_id = ?", [model_id])
    if not rows:
        raise HTTPException(404, f"model {model_id!r} not found")
    row = _attach_model_params(rows)[0]
    children = db.query(
        "SELECT fine_tune_models FROM GOLD.HF_MODEL_TREE WHERE base_model = ?",
        [model_id])
    row["fine_tune_models"] = children[0]["fine_tune_models"] if children else []
    return row


_REPO_FIELDS = """
    r.repo_id, r.repo_name, r.description, r.primary_language, r.topics,
    r.license, r.homepage, r.star_count, r.forks_count, r.open_issues_count,
    r.contributors_count, r.commit_count_30d, r.has_tests, r.has_ci,
    r.is_fork, r.is_archived, r.readme_length, r.repo_created_at,
    r.pushed_at, r.enriched_at, r.is_enriched
"""


def _attach_repo_params(rows: list[dict]) -> list[dict]:
    names = [r["repo_name"] for r in rows]
    if not names:
        return rows
    marks = ", ".join(["?"] * len(names))
    by_name = {p["repo_full_name"]: _pick_params(p) for p in db.query(
        f"SELECT * FROM GOLD.REPO_LORA_PARAMS WHERE repo_full_name IN ({marks})",
        names)}
    for r in rows:
        r["lora_params"] = by_name.get(r["repo_name"])
    return rows


@router.get("/repos")
def repos(param: str | None = None, value: str | None = None,
          language: str | None = None, has_tests: bool | None = None,
          q: str | None = None, sort: str = "star_count", order: str = "desc",
          limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    _check_warehouse()
    if sort not in REPO_SORTS:
        raise HTTPException(422, f"sort must be one of {sorted(REPO_SORTS)}")
    joins = ""
    where, params = ["1=1"], []
    if param or value:
        if not (param and value):
            raise HTTPException(422, "param and value must be passed together")
        if param not in FILTERABLE_PARAMS:
            raise HTTPException(422, f"unknown parameter {param!r}")
        joins = "JOIN GOLD.REPO_LORA_PARAMS g ON g.repo_full_name = r.repo_name"
        where.append(f"CAST(g.{param} AS VARCHAR) = ?")
        params.append(value)
    if language:
        where.append("r.primary_language = ?")
        params.append(language)
    if has_tests is not None:
        where.append("r.has_tests = ?")
        params.append(has_tests)
    if q:
        where.append("(r.repo_name ILIKE ? OR coalesce(r.description, '') ILIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    cond = " AND ".join(where)
    sort_expr = "r.star_count" if sort == "star_count" else (
        "(SELECT extraction_confidence FROM GOLD.REPO_LORA_PARAMS p "
        "WHERE p.repo_full_name = r.repo_name)")
    total = db.scalar(
        f"SELECT count(*) FROM SILVER.REPOS r {joins} WHERE {cond}", params)
    rows = db.query(
        f"SELECT {_REPO_FIELDS} FROM SILVER.REPOS r {joins} WHERE {cond} "
        f"ORDER BY {sort_expr} {_order(order)} NULLS LAST LIMIT ? OFFSET ?",
        params + [limit, offset])
    return db.envelope(_attach_repo_params(rows), total, limit, offset)


@router.get("/repos/{repo_name:path}")
def repo_detail(repo_name: str):
    _check_warehouse()
    rows = db.query(
        f"SELECT {_REPO_FIELDS} FROM SILVER.REPOS r WHERE r.repo_name = ?",
        [repo_name])
    if not rows:
        raise HTTPException(404, f"repo {repo_name!r} not found")
    row = _attach_repo_params(rows)[0]
    row["linked_models"] = db.query(
        "SELECT model_id, best_confidence FROM SILVER.GITHUB_HF_LINKS "
        "WHERE repo_full_name = ? ORDER BY best_confidence DESC", [repo_name])
    return row


def _map_hits(hits: list[dict]) -> list[dict]:
    return [{"score": h["score"], "type": h["kind"], "object": h["object"]}
            for h in hits]


@router.get("/search")
def search(q: str, type: str = "all", limit: int = Query(10, ge=1, le=50)):
    if type not in ("repos", "models", "all"):
        raise HTTPException(422, "type must be repos | models | all")
    try:
        from ml.rag.retriever import search as rag_search
        from ml.rag.retriever import search_all
        hits = (search_all(q, top_k=limit) if type == "all"
                else rag_search(q, kind=type, top_k=limit))
    except Exception as exc:
        raise HTTPException(
            503, f"semantic search unavailable (Qdrant/embedder): {exc}")
    return {"items": _map_hits(hits[:limit])}


@router.get("/ask")
def ask(q: str, top_k: int = Query(5, ge=1, le=10)):
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "ANTHROPIC_API_KEY is not configured on the server")
    try:
        from ml.rag import answer
        result = answer(q, top_k=top_k)
    except Exception as exc:
        raise HTTPException(503, f"RAG answer unavailable: {exc}")
    return {"answer": result["answer"], "sources": _map_hits(result["sources"])}
