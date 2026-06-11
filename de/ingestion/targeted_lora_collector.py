"""Targeted backfill of LoRA repos via the GitHub Search API.

LoRA repos are a tiny slice of GitHub, so this script seeds the corpus by
querying the GitHub Repository Search API. Code Search was dropped: its separate
~10 req/min limit made a full pass take ~40 min of waiting for coverage
Repository Search already provides.

Discovered repos land in `lora_search_discovery`, then are enriched into
`github_repos_enriched`. Idempotent: a re-run skips already-enriched repos and
dedups by repo_id.

Run:  python -m de.ingestion.targeted_lora_collector
   or python targeted_lora_collector.py   (from de/ingestion/)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

# The import path differs by context: repo checkout (de.ingestion.*), Airflow
# container where de/ingestion is mounted as /opt/airflow/ingestion
# (ingestion.*), or a direct run from within de/ingestion/ (bare module name).
_ENRICHER_SYMBOLS = (
    "GITHUB_TOKEN",
    "GITHUB_API_BASE",
    "GitHubClient",
    "enrich_repo",
    "get_connection",
    "init_schema",
    "upsert_enriched",
)
_enricher = None
for _module in ("de.ingestion.gh_repo_enricher", "ingestion.gh_repo_enricher",
                "gh_repo_enricher"):
    try:
        _enricher = __import__(_module, fromlist=_ENRICHER_SYMBOLS)
        break
    except ImportError:
        continue
if _enricher is None:
    raise ImportError("Cannot locate gh_repo_enricher on the import path")

GITHUB_TOKEN = _enricher.GITHUB_TOKEN
GITHUB_API_BASE = _enricher.GITHUB_API_BASE
GitHubClient = _enricher.GitHubClient
enrich_repo = _enricher.enrich_repo
get_connection = _enricher.get_connection
init_schema = _enricher.init_schema
upsert_enriched = _enricher.upsert_enriched

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

REPO_SEARCH_QUERIES = [
    "topic:lora",
    "topic:qlora",
    "topic:peft",
    "topic:lora-finetuning",
    "topic:dora",
    "lora in:name,description language:python",
    "qlora in:name,description language:python",
]

# Break GitHub Search's 1000-result-per-query cap by partitioning on creation
# date: LoRA took off in 2023, so a single newest-first query never sees the
# older long tail. Each base query is run once per window; each window returns
# its own <=1000 slice. A wider GitHub corpus means more repos can be linked to
# HF models (github_hf_links) -- i.e. tracing which repo a practice came from --
# plus richer repo_lora_params. (The HF-side practice quadrants are Variant D.)
DATE_WINDOWS = [
    "created:<2023-01-01",
    "created:2023-01-01..2023-06-30",
    "created:2023-07-01..2023-12-31",
    "created:2024-01-01..2024-06-30",
    "created:2024-07-01..2024-12-31",
    "created:>=2025-01-01",
]

# "LoRa" the radio protocol (LoRaWAN / IoT long-range RF) collides with "LoRA"
# the ML technique (Low-Rank Adaptation). Repository Search for topic:lora /
# "lora in:name" pulls in large amounts of firmware/IoT projects. A repo whose
# text matches any of these and shows NO ML signal is rejected at discovery.
RADIO_LORA_BLOCKLIST = [
    "lorawan", "meshtastic", "chirpstack", "the things network", "thethingsnetwork",
    "lpwan", "sx1276", "sx1278", "sx1262", "sx1280", "rfm95", "rfm96", "rfm9x",
    "ttgo", "heltec", "expresslrs", "elrs", "radio control", "rc link",
    "esp32", "esp8266", "arduino", "firmware", "transceiver", "gateway",
    "ham radio", "hamradio", "aprs", "soft radio", "rnode", "reticulum",
    "iot", "embedded",
]

# These override the blocklist: clear ML-LoRA signal keeps a repo even if it
# also mentions, say, "gateway" or "firmware".
ML_LORA_SIGNALS = [
    "fine-tun", "finetun", "peft", "qlora", "diffusion", "stable-diffusion",
    "llm", "large language model", "transformer", "huggingface", "hugging face",
    "pytorch", "adapter", "low-rank", "low rank", "checkpoint", "safetensors",
    "embedding",
]

# GitHub Search API: 100 results/page, 10 pages max => 1000-result hard cap.
SEARCH_PER_PAGE = 100
SEARCH_MAX_PAGES = 10

# Search endpoints are rate-limited separately (30 req/min authenticated).
SEARCH_REQUEST_DELAY = 2.1

# Cap on repos enriched per run. Discovery surfaces several thousand
# candidates; enriching all of them would burn ~6h of GitHub API budget. The
# backfill target is 500+, so we enrich a bounded slice per run -- a re-run is
# idempotent and picks up where the previous one stopped (fetch_pending skips
# already-enriched repos). Override via LORA_ENRICH_LIMIT.
ENRICH_LIMIT = int(os.getenv("LORA_ENRICH_LIMIT", "700"))


def init_discovery_schema(conn) -> None:
    """Create lora_search_discovery if it does not exist (mirrors migration 001)."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS lora_search_discovery (
            id              BIGINT AUTO_INCREMENT PRIMARY KEY,
            repo_id         BIGINT       NOT NULL UNIQUE,
            repo_name       VARCHAR(255) NOT NULL,
            search_source   VARCHAR(32)  NOT NULL,
            search_query    VARCHAR(512),
            discovered_at   DATETIME     NOT NULL,
            enriched        BOOLEAN      DEFAULT FALSE,
            INDEX idx_repo_id   (repo_id),
            INDEX idx_source    (search_source),
            INDEX idx_enriched  (enriched)
        )
        """
    )
    conn.commit()
    cursor.close()
    logger.info("lora_search_discovery schema ready")


def record_discovery(conn, repo_id: int, repo_name: str, source: str, query: str) -> None:
    """Insert a discovered repo, ignoring repos already seen (dedup by repo_id)."""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT IGNORE INTO lora_search_discovery
            (repo_id, repo_name, search_source, search_query, discovered_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (repo_id, repo_name, source, query[:512], datetime.now(timezone.utc)),
    )
    conn.commit()
    cursor.close()


def mark_enriched(conn, repo_id: int) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE lora_search_discovery SET enriched = TRUE WHERE repo_id = %s",
        (repo_id,),
    )
    conn.commit()
    cursor.close()


def fetch_pending(conn, limit: int) -> list[dict]:
    """Discovered repos not yet enriched and not already in github_repos_enriched."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT d.repo_id, d.repo_name
        FROM lora_search_discovery d
        LEFT JOIN github_repos_enriched e ON d.repo_id = e.repo_id
        WHERE d.enriched = FALSE AND e.repo_id IS NULL
        ORDER BY (d.search_source = 'repo_search') DESC, d.discovered_at ASC
        LIMIT %s
        """,
        (limit,),
    )
    rows = cursor.fetchall()
    cursor.close()
    return rows


def _search(client: GitHubClient, query: str) -> list[dict]:
    """Page through a Repository Search query, dropping radio-LoRa repos."""
    results: dict[int, str] = {}
    rejected = 0
    for page in range(1, SEARCH_MAX_PAGES + 1):
        path = (
            f"/search/repositories?q={requests_quote(query)}"
            f"&per_page={SEARCH_PER_PAGE}&page={page}"
        )
        response = client._request(path)
        time.sleep(SEARCH_REQUEST_DELAY)
        if response is None or response.status_code != 200:
            code = getattr(response, "status_code", "n/a")
            logger.warning("Search '%s' page %d -> HTTP %s", query, page, code)
            break

        body = response.json()
        items = body.get("items", [])
        for item in items:
            repo_id = item.get("id")
            repo_name = item.get("full_name")
            if not (repo_id and repo_name):
                continue
            if is_radio_lora(item):
                rejected += 1
                continue
            results[repo_id] = repo_name

        if len(items) < SEARCH_PER_PAGE:
            break  # last page

    if rejected:
        logger.info("  '%s': dropped %d radio-LoRa repos", query, rejected)
    return [{"repo_id": rid, "repo_name": name} for rid, name in results.items()]


def is_radio_lora(item: dict) -> bool:
    """True when the repo hits the radio blocklist AND shows no ML-LoRA signal."""
    text = " ".join(filter(None, [
        item.get("full_name", ""),
        item.get("description") or "",
        " ".join(item.get("topics", []) or []),
    ])).lower()

    if any(signal in text for signal in ML_LORA_SIGNALS):
        return False
    return any(term in text for term in RADIO_LORA_BLOCKLIST)


def requests_quote(value: str) -> str:
    from urllib.parse import quote
    return quote(value)


def collect_candidates(client: GitHubClient, conn) -> int:
    """Run all search queries, recording every discovered repo; returns new count."""
    discovered_before = _count_discovered(conn)

    for base in REPO_SEARCH_QUERIES:
        for window in DATE_WINDOWS:
            query = f"{base} {window}"
            repos = _search(client, query)
            for repo in repos:
                record_discovery(conn, repo["repo_id"], repo["repo_name"], "repo_search", query)
            logger.info("repo_search '%s' -> %d repos", query, len(repos))

    discovered_after = _count_discovered(conn)
    return discovered_after - discovered_before


def _count_discovered(conn) -> int:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM lora_search_discovery")
    (count,) = cursor.fetchone()
    cursor.close()
    return count


def enrich_pending(client: GitHubClient, conn) -> tuple[int, int]:
    """Enrich up to ENRICH_LIMIT discovered-but-unenriched repos. Returns (ok, failed)."""
    pending = fetch_pending(conn, ENRICH_LIMIT)
    logger.info("Enriching %d pending LoRA repos (cap=%d)", len(pending), ENRICH_LIMIT)

    ok = failed = 0
    for i, repo in enumerate(pending, start=1):
        repo_id = repo["repo_id"]
        repo_name = repo["repo_name"]
        try:
            data = enrich_repo(client, repo_id, repo_name)
            upsert_enriched(conn, data)
            mark_enriched(conn, repo_id)
            if data.get("enrichment_status") == "ok":
                ok += 1
            else:
                failed += 1
            logger.info(
                "[%d/%d] %s | status=%s | lang=%s",
                i, len(pending), repo_name,
                data.get("enrichment_status"), data.get("primary_language"),
            )
        except Exception as e:
            failed += 1
            logger.error("Failed to enrich %s: %s", repo_name, e)
            upsert_enriched(conn, {
                "repo_id": repo_id,
                "repo_name": repo_name,
                "enrichment_status": "error",
            })
            mark_enriched(conn, repo_id)
    return ok, failed


def report(conn) -> None:
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM lora_search_discovery")
    (discovered,) = cursor.fetchone()

    cursor.execute(
        "SELECT search_source, COUNT(*) FROM lora_search_discovery GROUP BY search_source"
    )
    by_source = cursor.fetchall()

    cursor.execute(
        """
        SELECT COUNT(*) FROM github_repos_enriched e
        JOIN lora_search_discovery d ON e.repo_id = d.repo_id
        WHERE e.enrichment_status = 'ok'
        """
    )
    (enriched_ok,) = cursor.fetchone()

    cursor.close()

    logger.info("=" * 60)
    logger.info("TARGETED LORA COLLECTOR -- RESULTS")
    logger.info("  discovered (unique repo_id): %d", discovered)
    for source, count in by_source:
        logger.info("    via %-12s: %d", source, count)
    logger.info("  enriched OK into github_repos_enriched: %d", enriched_ok)
    logger.info("=" * 60)


def main() -> None:
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set. Add it to your .env file.")
    if not GITHUB_API_BASE:
        raise RuntimeError("GITHUB_API_BASE missing from gh_repo_enricher.")

    client = GitHubClient(GITHUB_TOKEN)
    conn = get_connection()
    init_schema(conn)            # github_repos_enriched
    init_discovery_schema(conn)

    new_discovered = collect_candidates(client, conn)
    logger.info("Discovery pass: %d newly recorded repos", new_discovered)

    ok, failed = enrich_pending(client, conn)
    logger.info("Enrichment pass: %d ok, %d failed", ok, failed)

    report(conn)
    conn.close()


if __name__ == "__main__":
    main()
