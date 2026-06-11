"""
Targeted HuggingFace LoRA Collector

The hourly `hf_ingestion` task collects the newest HF models indiscriminately,
so the LoRA share of `huggingface_models_bronze` is thin. This script
deliberately seeds the LoRA corpus by querying the HuggingFace Hub API for
PEFT/LoRA/QLoRA/DoRA models and adapters.

It mirrors the GitHub side (targeted_lora_collector): every model surfaced by a
search is recorded in `hf_lora_search_discovery`, then its full metadata is
upserted into `huggingface_models_bronze` with `collection_source='targeted_lora'`
and `is_lora_relevant=TRUE`.

Idempotent: discovery dedups by model_id; the upsert refreshes metrics on
existing rows but never downgrades an `organic` row's collection_source.

Run:  python -m de.ingestion.hf_targeted_collector
   or python hf_targeted_collector.py   (from de/ingestion/)
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

import mysql.connector
from huggingface_hub import HfApi, ModelCard
from huggingface_hub.utils import HfHubHTTPError

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ml_underground")

# How many NEW LoRA models to ingest per run. 0 = unbounded: drain the whole
# discovery backlog (use for a full backfill). Discovery may surface more than
# this; ingestion stops once this many new models are written. Override via
# HF_LORA_TARGET_COUNT.
TARGET_COUNT = int(os.getenv("HF_LORA_TARGET_COUNT", "1500"))

# Skip models below this download count -- drops abandoned/empty adapters while
# keeping the real-adapter long tail. Safe to go low now: the peft-only query is
# high-precision, so a low floor admits real adapters, not merged/full noise.
# A small floor still keeps 0-download test uploads from re-diluting the score.
MIN_DOWNLOADS = int(os.getenv("HF_LORA_MIN_DOWNLOADS", "10"))

# Per-search cap on models pulled from the Hub. 0 (default) = FULL SWEEP:
# paginate the entire filter space instead of only the top-N by downloads, so
# discovery reaches the long tail where rare practices live -- the main lever for
# corpus size. Set a positive value to cap a single query.
SEARCH_LIMIT = int(os.getenv("HF_LORA_SEARCH_LIMIT", "0"))

# Small delay between model-card fetches to stay polite to the Hub.
CARD_FETCH_DELAY = 0.05

# Only the peft library/tag: these models were saved via peft.save_pretrained, so
# they carry adapter_config.json (confidence-1.0 params). The broader lora/qlora/
# adapter tags and free-text search pulled in merged/full models with no adapter
# config (~10% param yield), so they are intentionally dropped.
SEARCH_QUERIES = [
    ("library:peft", {"filter": "peft"}),
]


def get_connection():
    return mysql.connector.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
        password=MYSQL_PASSWORD, database=MYSQL_DATABASE,
    )


def init_discovery_schema(conn) -> None:
    """Create hf_lora_search_discovery if absent (mirrors migration 002)."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS hf_lora_search_discovery (
            id              BIGINT AUTO_INCREMENT PRIMARY KEY,
            model_id        VARCHAR(255) NOT NULL UNIQUE,
            search_query    VARCHAR(255),
            discovered_at   DATETIME     NOT NULL,
            ingested        BOOLEAN      DEFAULT FALSE,
            INDEX idx_model_id  (model_id),
            INDEX idx_ingested  (ingested)
        )
        """
    )
    conn.commit()
    cursor.close()
    logger.info("hf_lora_search_discovery schema ready")


def record_discovery(conn, model_id: str, query: str) -> None:
    """Insert a discovered model, ignoring models already seen (dedup by model_id)."""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT IGNORE INTO hf_lora_search_discovery
            (model_id, search_query, discovered_at)
        VALUES (%s, %s, %s)
        """,
        (model_id, query[:255], datetime.now(timezone.utc)),
    )
    conn.commit()
    cursor.close()


def mark_ingested(conn, model_id: str) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE hf_lora_search_discovery SET ingested = TRUE WHERE model_id = %s",
        (model_id,),
    )
    conn.commit()
    cursor.close()


def fetch_pending(conn, limit: int) -> list[str]:
    """Discovered model_ids not yet ingested by this collector."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT model_id FROM hf_lora_search_discovery
        WHERE ingested = FALSE
        ORDER BY discovered_at ASC
        LIMIT %s
        """,
        (limit,),
    )
    rows = [r[0] for r in cursor.fetchall()]
    cursor.close()
    return rows


def upsert_model(conn, model, card_content: str | None) -> None:
    """
    Write one HF model to huggingface_models_bronze, flagged as a targeted
    LoRA hit. An existing `organic` row keeps its collection_source (we only
    raise the LoRA flag and refresh metrics); a brand-new row is targeted_lora.
    """
    tags = list(model.tags or [])
    author = model.id.split("/")[0] if "/" in model.id else None

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO huggingface_models_bronze
            (model_id, author, base_model, pipeline_tag, library_name,
             downloads, likes, tags, card_content,
             created_at, last_modified, ingested_at,
             collection_source, is_lora_relevant)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            base_model        = VALUES(base_model),
            pipeline_tag      = VALUES(pipeline_tag),
            library_name      = VALUES(library_name),
            downloads         = VALUES(downloads),
            likes             = VALUES(likes),
            tags              = VALUES(tags),
            card_content      = VALUES(card_content),
            last_modified     = VALUES(last_modified),
            ingested_at       = VALUES(ingested_at),
            is_lora_relevant  = TRUE,
            -- never downgrade an organic row; only fill in if unset
            collection_source = IF(collection_source = 'organic',
                                   'organic', VALUES(collection_source))
        """,
        (
            model.id, author, extract_base_model(tags),
            model.pipeline_tag, model.library_name,
            model.downloads or 0, model.likes or 0, json.dumps(tags),
            card_content,
            naive(model.created_at), naive(model.last_modified),
            datetime.now(timezone.utc),
            "targeted_lora", True,
        ),
    )
    conn.commit()
    cursor.close()


def extract_base_model(tags) -> str | None:
    """Parse the base model from HF's `base_model:<id>` tags."""
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
    """HF returns tz-aware UTC datetimes; MySQL DATETIME needs naive."""
    return dt.replace(tzinfo=None) if dt else None


def load_card(model_id: str) -> str | None:
    """Model-card README; many models have none -> NULL."""
    try:
        return ModelCard.load(model_id).content
    except Exception:
        return None


def collect_candidates(api: HfApi, conn) -> int:
    """Run all HF searches, recording every discovered model. Returns new count."""
    before = _count_discovered(conn)

    for label, kwargs in SEARCH_QUERIES:
        try:
            models = api.list_models(
                sort="downloads", direction=-1,
                limit=(SEARCH_LIMIT or None),  # 0 -> None -> full pagination
                **kwargs,
            )
            count = 0
            for model in models:
                # listing is sorted by downloads desc: once below the floor the
                # rest are too, so stop paginating this query -- bounds a full
                # sweep to the models actually worth ingesting.
                dl = getattr(model, "downloads", None)
                if dl is not None and dl < MIN_DOWNLOADS:
                    break
                record_discovery(conn, model.id, label)
                count += 1
            logger.info("hf_search '%s' -> %d models", label, count)
        except HfHubHTTPError as e:
            logger.warning("hf_search '%s' failed: %s", label, e)

    return _count_discovered(conn) - before


def _count_discovered(conn) -> int:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM hf_lora_search_discovery")
    (count,) = cursor.fetchone()
    cursor.close()
    return count


def ingest_pending(api: HfApi, conn) -> tuple[int, int]:
    """
    Fetch full metadata for discovered models and upsert them. Stops once
    TARGET_COUNT new models have been written. Returns (written, skipped).
    """
    unbounded = TARGET_COUNT <= 0
    pending = fetch_pending(conn, 10_000_000 if unbounded else TARGET_COUNT * 3)
    logger.info("Ingesting %s LoRA models from %d pending candidates",
                "all pending" if unbounded else f"up to {TARGET_COUNT}", len(pending))

    written = skipped = 0
    for model_id in pending:
        if not unbounded and written >= TARGET_COUNT:
            break
        try:
            model = api.model_info(model_id)
        except Exception as e:
            logger.warning("model_info failed for %s: %s", model_id, e)
            mark_ingested(conn, model_id)  # don't retry a broken id forever
            skipped += 1
            continue

        if (model.downloads or 0) < MIN_DOWNLOADS:
            mark_ingested(conn, model_id)
            skipped += 1
            continue

        card = load_card(model_id)
        time.sleep(CARD_FETCH_DELAY)
        upsert_model(conn, model, card)
        mark_ingested(conn, model_id)
        written += 1
        if written % 100 == 0:
            logger.info("  ... %d models written", written)

    return written, skipped


def report(conn) -> None:
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM hf_lora_search_discovery")
    (discovered,) = cursor.fetchone()

    cursor.execute(
        "SELECT collection_source, COUNT(*) FROM huggingface_models_bronze "
        "GROUP BY collection_source"
    )
    by_source = cursor.fetchall()

    cursor.execute(
        "SELECT COUNT(*) FROM huggingface_models_bronze WHERE is_lora_relevant = TRUE"
    )
    (lora_total,) = cursor.fetchone()

    cursor.execute(
        "SELECT COALESCE(library_name,'(none)'), COUNT(*) FROM huggingface_models_bronze "
        "WHERE is_lora_relevant = TRUE GROUP BY library_name ORDER BY 2 DESC LIMIT 10"
    )
    by_library = cursor.fetchall()

    cursor.execute(
        "SELECT COALESCE(pipeline_tag,'(none)'), COUNT(*) FROM huggingface_models_bronze "
        "WHERE is_lora_relevant = TRUE GROUP BY pipeline_tag ORDER BY 2 DESC LIMIT 10"
    )
    by_pipeline = cursor.fetchall()

    cursor.execute(
        "SELECT COALESCE(base_model,'(none)'), COUNT(*) FROM huggingface_models_bronze "
        "WHERE is_lora_relevant = TRUE GROUP BY base_model ORDER BY 2 DESC LIMIT 10"
    )
    by_base = cursor.fetchall()

    cursor.execute(
        "SELECT model_id, library_name, pipeline_tag, base_model, downloads, likes "
        "FROM huggingface_models_bronze WHERE collection_source = 'targeted_lora' "
        "ORDER BY downloads DESC LIMIT 20"
    )
    sample = cursor.fetchall()
    cursor.close()

    logger.info("=" * 64)
    logger.info("TARGETED HF LORA COLLECTOR -- RESULTS")
    logger.info("  discovered (unique model_id): %d", discovered)
    logger.info("  models flagged is_lora_relevant: %d", lora_total)
    logger.info("  by collection_source:")
    for source, count in by_source:
        logger.info("    %-16s: %d", source, count)
    logger.info("  by library_name (LoRA-relevant):")
    for lib, count in by_library:
        logger.info("    %-24s: %d", lib, count)
    logger.info("  by pipeline_tag (LoRA-relevant):")
    for tag, count in by_pipeline:
        logger.info("    %-24s: %d", tag, count)
    logger.info("  top base_model (LoRA-relevant):")
    for base, count in by_base:
        logger.info("    %-40s: %d", base, count)
    logger.info("  sample of 20 targeted_lora models (by downloads):")
    for mid, lib, pipe, base, dl, lk in sample:
        logger.info("    %-50s lib=%s pipe=%s base=%s dl=%d likes=%d",
                    mid, lib, pipe, base, dl, lk)
    logger.info("=" * 64)


def main() -> None:
    api = HfApi()
    conn = get_connection()
    init_discovery_schema(conn)

    new_discovered = collect_candidates(api, conn)
    logger.info("Discovery pass: %d newly recorded models", new_discovered)

    written, skipped = ingest_pending(api, conn)
    logger.info("Ingestion pass: %d written, %d skipped (below min_downloads / errors)",
                written, skipped)

    report(conn)
    conn.close()


if __name__ == "__main__":
    main()
