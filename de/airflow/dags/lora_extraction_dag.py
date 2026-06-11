"""LoRA-config extraction DAG — Step 4 (US-3.1, US-3.2).

Stages: extract_raw (github_files -> lora_configs_raw), extract_llm (US-3.3 #7,
LLM fallback for repos no structured layer matched -> lora_configs_raw), and
merge_to_gold (priority merge AST > JSON > YAML > regex > LLM -> repo_lora_params).

In parallel with the GitHub path: extract_hf_cards (huggingface_models_bronze
-> hf_models_lora_params, Variant D).

Manual trigger only. Idempotent: re-runs only refresh rows whose contents
changed (UNIQUE keys + ON DUPLICATE KEY UPDATE).
"""

from __future__ import annotations

from datetime import timedelta

from airflow import DAG
from airflow.models.param import Param
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago

default_args = {
    "owner": "ml-underground",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
}


def run_extract_raw(**context):
    """Walk github_files for LoRA repos, extract per file, upsert into lora_configs_raw."""
    import logging
    import os
    import sys

    import mysql.connector

    os.environ.setdefault("MYSQL_HOST", "mysql")
    sys.path.insert(0, "/opt/airflow")
    from ingestion.lora_config_extractor import extract_from_file

    params = context["params"]
    file_limit = int(params["file_limit"])

    log = logging.getLogger(__name__)

    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "root"),
        database=os.getenv("MYSQL_DATABASE", "ml_underground"),
    )

    # Only files belonging to LoRA repos (enrichment_status='ok' excludes
    # the radio-LoRa false-positives). The JOIN is on repo_full_name because
    # github_files stores the owner/name string, matching github_repos_enriched.
    #
    # Materialise the read result before opening the write cursor — MySQL
    # connector forbids interleaved read/write on a single connection
    # ("Unread result found"). The corpus is small (~5k rows of MEDIUMTEXT,
    # ~50MB peak) so a fetchall is fine.
    read_cur = conn.cursor(dictionary=True)
    read_cur.execute(
        """
        SELECT f.file_id, f.repo_full_name, f.file_path, f.file_category,
               f.content
        FROM github_files f
        JOIN github_repos_enriched e
          ON e.repo_name = f.repo_full_name
         AND e.enrichment_status = 'ok'
        WHERE f.content IS NOT NULL
        ORDER BY f.file_id
        LIMIT %s
        """,
        (file_limit,),
    )
    files = read_cur.fetchall()
    read_cur.close()
    log.info("extract_raw: read %d files", len(files))

    write_cur = conn.cursor()
    files_seen = 0
    rows_inserted = 0
    rows_by_source: dict = {}
    BATCH = 500
    buffer: list = []

    def _flush():
        nonlocal rows_inserted, buffer
        if not buffer:
            return
        write_cur.executemany(
            """
            INSERT INTO lora_configs_raw
                (repo_full_name, file_id, source, param_name,
                 param_value, confidence)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                param_value = VALUES(param_value),
                confidence  = VALUES(confidence),
                extracted_at = CURRENT_TIMESTAMP
            """,
            buffer,
        )
        rows_inserted += len(buffer)
        buffer = []

    for row in files:
        files_seen += 1
        extracted = extract_from_file(
            row["file_path"], row["file_category"], row["content"],
        )
        for r in extracted:
            buffer.append((
                row["repo_full_name"], row["file_id"],
                r["source"], r["param_name"],
                r["param_value"], float(r["confidence"]),
            ))
            rows_by_source[r["source"]] = rows_by_source.get(r["source"], 0) + 1
        if len(buffer) >= BATCH:
            _flush()
            conn.commit()
        if files_seen % 500 == 0:
            log.info("processed %d files, %d raw rows so far",
                     files_seen, rows_inserted + len(buffer))

    _flush()
    conn.commit()
    write_cur.close()
    conn.close()

    log.info("extract_raw done: files=%d, raw_rows=%d, by_source=%s",
             files_seen, rows_inserted, rows_by_source)
    return {"files": files_seen, "rows": rows_inserted,
            "by_source": rows_by_source}


# param_sources / extraction_confidence are computed separately; these map 1:1.
_GOLD_COLUMNS = (
    "rank_value", "lora_alpha", "target_modules", "learning_rate", "optimizer",
    "lora_dropout", "lora_bias", "scheduler", "batch_size",
    "gradient_accumulation_steps", "num_train_epochs", "warmup_steps",
    "bf16", "fp16", "gradient_checkpointing", "merge_and_unload",
)


# Sanity bounds — reject values clearly out of LoRA's plausible range
# (regex layer can pick up e.g. `dim=38077` and mislabel it as lora_alpha).
# rank_value=-1 is a valid PEFT "auto" sentinel.
_INT_BOUNDS = {
    "rank_value":                  (-1,   512),
    "lora_alpha":                  (1,    1024),
    "batch_size":                  (1,    1024),
    "gradient_accumulation_steps": (1,    1024),
    # num_train_epochs tightened: regex picks up "978B tokens"-style numbers
    # from prose. No real LoRA run trains for >100 epochs.
    "num_train_epochs":            (1,    100),
    "warmup_steps":                (0,    10000),
}
_FLOAT_BOUNDS = {
    "learning_rate": (1e-9, 10.0),   # 1e-7..1e-3 typical, never above ~1
    "lora_dropout":  (0.0,  1.0),
}


def _coerce(name: str, raw: str | None):
    """Cast TEXT param_value back to the strongly-typed column, dropping junk."""
    import json
    if raw is None or raw == "":
        return None
    if name in _INT_BOUNDS:
        try:
            v = int(float(raw))
        except (ValueError, TypeError):
            return None
        lo, hi = _INT_BOUNDS[name]
        if not (lo <= v <= hi):
            return None
        # rank_value=-1 is a valid PEFT auto-rank sentinel, but rank=0 is junk.
        if name == "rank_value" and v == 0:
            return None
        return v
    if name in _FLOAT_BOUNDS:
        try:
            v = float(raw)
        except (ValueError, TypeError):
            return None
        lo, hi = _FLOAT_BOUNDS[name]
        return v if lo <= v <= hi else None
    if name in ("bf16", "fp16", "gradient_checkpointing", "merge_and_unload"):
        s = str(raw).strip()
        # DeepSpeed ZeRO configs store these as {"enabled": true/false/"auto"}.
        if s[:1] == "{":
            import ast
            d = None
            for loader in (json.loads, ast.literal_eval):
                try:
                    d = loader(s)
                    break
                except (ValueError, SyntaxError, TypeError):
                    d = None
            if not isinstance(d, dict):
                return None
            v = d.get("enabled")
            if v is None or (isinstance(v, str) and v.strip().lower() == "auto"):
                return None
            return v is True or str(v).strip().lower() in ("1", "true", "yes")
        return s.lower() in ("1", "true", "yes")
    if name == "target_modules":
        # Already JSON-serialized by the extractor when it was a list.
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            parsed = [s.strip() for s in str(raw).split(",") if s.strip()]
        return json.dumps(parsed if isinstance(parsed, list) else [parsed])
    if name in ("optimizer", "lora_bias", "scheduler"):
        return str(raw)[:50]
    return raw


def run_merge_to_gold(**context):
    """Collapse lora_configs_raw → repo_lora_params (one row per repo)."""
    import json
    import logging
    import os
    import sys

    import mysql.connector

    os.environ.setdefault("MYSQL_HOST", "mysql")
    sys.path.insert(0, "/opt/airflow")
    from ingestion.lora_config_extractor import merge_params

    log = logging.getLogger(__name__)

    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "root"),
        database=os.getenv("MYSQL_DATABASE", "ml_underground"),
    )

    # One pass: pull every raw row at once and bucket by repo locally.
    # Avoids "Unread result found" from holding two cursors open on one
    # connection.
    read_cur = conn.cursor(dictionary=True)
    read_cur.execute(
        "SELECT repo_full_name, source, param_name, param_value, confidence "
        "FROM lora_configs_raw"
    )
    raw_rows = read_cur.fetchall()
    read_cur.close()

    by_repo: dict = {}
    for r in raw_rows:
        by_repo.setdefault(r["repo_full_name"], []).append({
            "source": r["source"],
            "param_name": r["param_name"],
            "param_value": r["param_value"],
            "confidence": float(r["confidence"]),
        })
    log.info("merge_to_gold: %d repos with extracted rows (from %d raw rows)",
             len(by_repo), len(raw_rows))

    columns = (
        ["repo_full_name"] + list(_GOLD_COLUMNS)
        + ["param_sources", "total_params_extracted", "extraction_confidence"]
    )
    placeholders = ", ".join(["%s"] * len(columns))
    update_clause = ", ".join(
        f"{c}=VALUES({c})" for c in columns if c != "repo_full_name"
    ) + ", extracted_at=CURRENT_TIMESTAMP"
    sql = (
        f"INSERT INTO repo_lora_params ({', '.join(columns)}) "
        f"VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_clause}"
    )

    insert_cur = conn.cursor()
    inserted = 0
    skipped = 0

    for repo, rows in by_repo.items():
        merged = merge_params(rows)
        if not merged:
            skipped += 1
            continue
        values = [repo]
        for col in _GOLD_COLUMNS:
            values.append(_coerce(col, merged.get(col)))
        values.append(json.dumps(merged["param_sources"]))
        values.append(int(merged["total_params_extracted"]))
        values.append(float(merged["extraction_confidence"]))
        insert_cur.execute(sql, values)
        inserted += 1

    conn.commit()
    insert_cur.close()
    conn.close()

    log.info("merge_to_gold done: inserted=%d, skipped=%d", inserted, skipped)
    return {"inserted": inserted, "skipped": skipped}


def run_extract_llm(**context):
    """LLM fallback (US-3.3, #7): for LoRA repos that have files but produced no
    structured rows in lora_configs_raw, ask Claude to recover params and upsert
    them as source='llm'. The downstream merge keeps llm at lowest priority, so
    these rows only fill gaps no structured layer could.

    No-ops (does not fail the DAG) when ANTHROPIC_API_KEY is unset or the
    anthropic package is missing — the rest of the pipeline runs regardless.
    """
    import logging
    import os
    import sys

    import mysql.connector

    os.environ.setdefault("MYSQL_HOST", "mysql")
    sys.path.insert(0, "/opt/airflow")

    log = logging.getLogger(__name__)

    if not os.getenv("ANTHROPIC_API_KEY"):
        log.warning("extract_llm: ANTHROPIC_API_KEY not set — skipping LLM fallback")
        return {"skipped": "no ANTHROPIC_API_KEY"}
    try:
        import anthropic
    except ImportError:
        log.warning("extract_llm: anthropic package not installed — skipping")
        return {"skipped": "anthropic not installed"}

    from ingestion.llm_extractor import extract_from_llm

    params = context["params"]
    repo_limit = int(params["llm_repo_limit"])
    files_per_repo = int(params["llm_max_files_per_repo"])
    if repo_limit <= 0:
        log.info("extract_llm: llm_repo_limit=0 — nothing to do")
        return {"repos": 0, "rows": 0}

    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "root"),
        database=os.getenv("MYSQL_DATABASE", "ml_underground"),
    )

    # Target set: LoRA repos with files but zero rows in lora_configs_raw
    # (AST/JSON/YAML/regex all missed). Inserting llm rows removes a repo from
    # this set, so re-runs won't re-bill it.
    read_cur = conn.cursor(dictionary=True)
    read_cur.execute(
        """
        SELECT f.repo_full_name
        FROM github_files f
        JOIN github_repos_enriched e
          ON e.repo_name = f.repo_full_name
         AND e.enrichment_status = 'ok'
        WHERE f.content IS NOT NULL
          AND f.repo_full_name NOT IN (SELECT repo_full_name FROM lora_configs_raw)
        GROUP BY f.repo_full_name
        ORDER BY f.repo_full_name
        LIMIT %s
        """,
        (repo_limit,),
    )
    repos = [r["repo_full_name"] for r in read_cur.fetchall()]
    read_cur.close()
    log.info("extract_llm: %d repos need LLM fallback", len(repos))

    # Bucket every target repo's files in one read (no interleaved cursors).
    files_by_repo: dict = {}
    if repos:
        placeholders = ", ".join(["%s"] * len(repos))
        fcur = conn.cursor(dictionary=True)
        fcur.execute(
            f"""
            SELECT repo_full_name, file_id, file_path, file_category, content
            FROM github_files
            WHERE repo_full_name IN ({placeholders}) AND content IS NOT NULL
            ORDER BY repo_full_name,
                FIELD(file_category,
                      'training_script', 'config', 'adapter_config', 'dependencies'),
                file_id
            """,
            tuple(repos),
        )
        for row in fcur.fetchall():
            files_by_repo.setdefault(row["repo_full_name"], []).append(row)
        fcur.close()

    client = anthropic.Anthropic()
    insert_sql = (
        "INSERT INTO lora_configs_raw "
        "(repo_full_name, file_id, source, param_name, param_value, confidence) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE param_value=VALUES(param_value), "
        "confidence=VALUES(confidence), extracted_at=CURRENT_TIMESTAMP"
    )

    write_cur = conn.cursor()
    repos_with_rows = 0
    rows_inserted = 0
    failures = 0

    for repo in repos:
        files = files_by_repo.get(repo, [])[:files_per_repo]
        if not files:
            continue
        try:
            rows = extract_from_llm(files, client=client)
        except Exception as exc:  # one repo failing must not stop the batch
            failures += 1
            log.warning("extract_llm: repo %s failed: %s", repo, exc)
            continue
        if not rows:
            continue
        # LLM rows are repo-level; key them to a representative file_id (the
        # first after the training_script-first ordering) to satisfy the schema.
        file_id = files[0]["file_id"]
        write_cur.executemany(insert_sql, [
            (repo, file_id, r["source"], r["param_name"],
             r["param_value"], float(r["confidence"]))
            for r in rows
        ])
        conn.commit()
        repos_with_rows += 1
        rows_inserted += len(rows)

    write_cur.close()
    conn.close()
    log.info("extract_llm done: repos=%d, repos_with_rows=%d, rows=%d, failures=%d",
             len(repos), repos_with_rows, rows_inserted, failures)
    return {"repos": len(repos), "repos_with_rows": repos_with_rows,
            "rows": rows_inserted, "failures": failures}


# HF cards are small enough that we skip the raw-table audit trail the GitHub
# side keeps — extract and merge per model in one pass.
def run_extract_hf_cards(**context):
    """Walk huggingface_models_bronze, extract+merge per card, upsert into hf_models_lora_params."""
    import json
    import logging
    import os
    import sys

    import mysql.connector

    os.environ.setdefault("MYSQL_HOST", "mysql")
    sys.path.insert(0, "/opt/airflow")
    from ingestion.lora_config_extractor import (
        extract_from_adapter_config, extract_from_hf_model_card, merge_params,
    )
    from ingestion.hf_utils import fetch_adapter_config

    log = logging.getLogger(__name__)
    params = context["params"]
    card_limit = int(params["hf_card_limit"])

    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "root"),
        database=os.getenv("MYSQL_DATABASE", "ml_underground"),
    )

    read_cur = conn.cursor(dictionary=True)
    # incremental: skip models already in hf_models_lora_params so a re-run
    # finishes the backlog fast instead of re-fetching everything (truncate the
    # table to force a full refresh).
    read_cur.execute(
        "SELECT model_id, tags, card_content, is_lora_relevant "
        "FROM huggingface_models_bronze b "
        "WHERE ((card_content IS NOT NULL AND CHAR_LENGTH(card_content) > 200) "
        "       OR is_lora_relevant = TRUE) "
        "  AND NOT EXISTS (SELECT 1 FROM hf_models_lora_params p "
        "                  WHERE p.model_id = b.model_id) "
        "ORDER BY model_id "
        "LIMIT %s",
        (card_limit,),
    )
    models = read_cur.fetchall()
    read_cur.close()
    log.info("extract_hf_cards: read %d models", len(models))

    columns = (
        ["model_id"] + list(_GOLD_COLUMNS)
        + ["param_sources", "total_params_extracted", "extraction_confidence"]
    )
    placeholders = ", ".join(["%s"] * len(columns))
    update_clause = ", ".join(
        f"{c}=VALUES({c})" for c in columns if c != "model_id"
    ) + ", extracted_at=CURRENT_TIMESTAMP"
    sql = (
        f"INSERT INTO hf_models_lora_params ({', '.join(columns)}) "
        f"VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_clause}"
    )

    write_cur = conn.cursor()
    inserted = 0
    skipped = 0
    adapter_hits = 0
    src_count = {"ast": 0, "json": 0, "yaml": 0, "regex": 0, "llm": 0}

    for m in models:
        tags = []
        if m["tags"]:
            try:
                tags = json.loads(m["tags"]) if isinstance(m["tags"], str) else m["tags"]
            except (json.JSONDecodeError, TypeError):
                tags = []
        raw = extract_from_hf_model_card(m["card_content"], tags=tags)
        # Variant D depth: PEFT adapters publish adapter_config.json (canonical
        # r / lora_alpha / target_modules, confidence 1.0). Cards rarely state
        # target_modules, so pull the real config for LoRA models and let it win
        # the merge (json priority > yaml > regex).
        if m.get("is_lora_relevant"):
            cfg = fetch_adapter_config(m["model_id"])
            if cfg:
                adapter_rows = extract_from_adapter_config(cfg)
                if adapter_rows:
                    raw = adapter_rows + raw
                    adapter_hits += 1
        if not raw:
            skipped += 1
            continue
        merged = merge_params(raw)
        if not merged:
            skipped += 1
            continue
        for s in merged["param_sources"].values():
            src_count[s] = src_count.get(s, 0) + 1
        values = [m["model_id"]]
        for col in _GOLD_COLUMNS:
            values.append(_coerce(col, merged.get(col)))
        values.append(json.dumps(merged["param_sources"]))
        values.append(int(merged["total_params_extracted"]))
        values.append(float(merged["extraction_confidence"]))
        write_cur.execute(sql, values)
        inserted += 1
        if inserted % 200 == 0:
            conn.commit()
            log.info("  ... %d models written", inserted)

    conn.commit()
    write_cur.close()
    conn.close()

    log.info("extract_hf_cards done: inserted=%d, skipped=%d, adapter_config_hits=%d, by_source=%s",
             inserted, skipped, adapter_hits, src_count)
    return {"inserted": inserted, "skipped": skipped,
            "adapter_config_hits": adapter_hits, "by_source": src_count}


with DAG(
    dag_id="lora_extraction_dag",
    default_args=default_args,
    description="Step 4: extract LoRA hyperparameters from github_files and HuggingFace model cards",
    schedule_interval="@daily",    # daily — extract_hf_cards is incremental, so it
                                   # only processes newly-ingested models
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=3),
    params={
        # Cap how many github_files rows we walk per run. The default
        # comfortably covers the current corpus (~4900 files).
        "file_limit": Param(20000, type="integer", minimum=1),
        # Cap how many HF model cards we walk per run. The default covers
        # the current pool (~3400 cards with content); set lower for a fast
        # iteration during development.
        "hf_card_limit": Param(10000, type="integer", minimum=1),
        # LLM fallback (#7): cap repos per run and files sent per repo.
        "llm_repo_limit": Param(200, type="integer", minimum=0),
        "llm_max_files_per_repo": Param(6, type="integer", minimum=1),
    },
    tags=["extraction", "manual", "lora_intelligence"],
) as dag:

    extract_raw = PythonOperator(
        task_id="extract_raw",
        python_callable=run_extract_raw,
        execution_timeout=timedelta(minutes=60),
    )

    merge_to_gold = PythonOperator(
        task_id="merge_to_gold",
        python_callable=run_merge_to_gold,
        execution_timeout=timedelta(minutes=30),
    )

    # US-3.3 / #7 — LLM fallback runs between raw extraction and the gold merge
    # so its source='llm' rows are included in the priority merge.
    extract_llm = PythonOperator(
        task_id="extract_llm",
        python_callable=run_extract_llm,
        execution_timeout=timedelta(minutes=60),
    )

    # Variant D — runs in parallel with the GitHub extraction. Independent
    # input (HF cards), independent output table (hf_models_lora_params), so
    # no ordering needed.
    extract_hf_cards = PythonOperator(
        task_id="extract_hf_cards",
        python_callable=run_extract_hf_cards,
        # ~150 adapter_config fetches/min over HTTP; the grown peft corpus (~9k
        # adapters) needs well over the old 30 min, which timed out mid-sweep.
        execution_timeout=timedelta(minutes=120),
    )

    extract_raw >> extract_llm >> merge_to_gold
