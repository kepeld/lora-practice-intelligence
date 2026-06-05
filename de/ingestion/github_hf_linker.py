"""
GitHub <-> HuggingFace Record Linker

Derives links between GitHub LoRA repos and HuggingFace models from text
already stored in MySQL -- no API calls. Four strategies, in priority order:

  1. readme_direct    (1.0)  -- repo README links to huggingface.co/<model_id>
  2. modelcard_direct (1.0)  -- HF model card links to github.com/<owner/repo>
  3. same_username    (0.7)  -- GitHub owner == HF author
  4. fuzzy_name       (calc) -- fuzzy match of repo name vs. model name

A (repo, model) pair only gets a lower-priority link if no higher-priority
strategy already linked it. Results land in the `github_hf_links` bronze table
(see migrations/003_github_hf_links.sql).

Idempotent: UNIQUE KEY (repo_full_name, model_id, link_type) + INSERT IGNORE.

Run:  python -m de.ingestion.github_hf_linker
   or python github_hf_linker.py   (from de/ingestion/)
"""

from __future__ import annotations

import logging
import os
import re

import mysql.connector

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# prefer rapidfuzz if installed, else fall back to stdlib difflib
try:
    from rapidfuzz.fuzz import ratio as _rf_ratio

    def fuzz_ratio(a: str, b: str) -> float:
        return _rf_ratio(a, b) / 100.0
except ImportError:
    from difflib import SequenceMatcher

    def fuzz_ratio(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

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

# Minimum rapidfuzz/difflib ratio for a fuzzy_name link. Override via env.
FUZZY_THRESHOLD = float(os.getenv("LINKER_FUZZY_THRESHOLD", "0.85"))

# Characters of context kept around a direct-link regex hit.
CONTEXT_CHARS = 50

# Generic names that identify nothing -- a fuzzy match between two repos both
# called "lora" is meaningless (ratio 1.0, zero real relationship). Any name
# that reduces to one of these is excluded from fuzzy_name matching.
FUZZY_NAME_STOPLIST = {
    "lora", "loras", "qlora", "dora", "peft", "adapter", "adapters",
    "lora-finetuning", "lora-training", "finetune", "finetuning", "fine-tuning",
    "llm", "llms", "model", "models", "test", "demo", "example", "examples",
    "ai", "ml", "nlp", "training", "diffusion", "transformer", "transformers",
}

# Minimum name length for fuzzy matching -- short names produce noisy hits.
FUZZY_MIN_NAME_LEN = 6

# huggingface.co/<owner>/<model>  and  github.com/<owner>/<repo>
HF_URL_RE = re.compile(
    r"huggingface\.co/([A-Za-z0-9_-]+/[A-Za-z0-9._-]+)", re.IGNORECASE
)
GH_URL_RE = re.compile(
    r"github\.com/([A-Za-z0-9_-]+/[A-Za-z0-9._-]+)", re.IGNORECASE
)


def get_connection():
    return mysql.connector.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
        password=MYSQL_PASSWORD, database=MYSQL_DATABASE,
    )


def init_schema(conn) -> None:
    """Create github_hf_links if absent (mirrors migration 003)."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS github_hf_links (
            link_id         BIGINT AUTO_INCREMENT PRIMARY KEY,
            repo_full_name  VARCHAR(255) NOT NULL,
            model_id        VARCHAR(255) NOT NULL,
            link_type       ENUM('readme_direct', 'modelcard_direct',
                                 'same_username', 'fuzzy_name') NOT NULL,
            confidence      DECIMAL(3,2) NOT NULL,
            matched_text    TEXT,
            created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_link (repo_full_name, model_id, link_type),
            INDEX idx_repo       (repo_full_name),
            INDEX idx_model      (model_id),
            INDEX idx_confidence (confidence)
        )
        """
    )
    conn.commit()
    cursor.close()
    logger.info("github_hf_links schema ready")


def load_github_repos(conn) -> list[dict]:
    """ML-LoRA GitHub repos (enrichment_status='ok' excludes radio-LoRa)."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT repo_name AS repo_full_name, readme_content
        FROM github_repos_enriched
        WHERE enrichment_status = 'ok'
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    return rows


def load_hf_models(conn) -> list[dict]:
    """All HF models -- both targeted_lora and organic (organic may match too)."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT model_id, card_content
        FROM huggingface_models_bronze
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    return rows


def insert_links(conn, links: list[tuple]) -> int:
    """Bulk INSERT IGNORE; returns rows actually inserted."""
    if not links:
        return 0
    cursor = conn.cursor()
    before = _count_links(conn)
    cursor.executemany(
        """
        INSERT IGNORE INTO github_hf_links
            (repo_full_name, model_id, link_type, confidence, matched_text)
        VALUES (%s, %s, %s, %s, %s)
        """,
        links,
    )
    conn.commit()
    cursor.close()
    return _count_links(conn) - before


def _count_links(conn) -> int:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM github_hf_links")
    (count,) = cursor.fetchone()
    cursor.close()
    return count


def _context(text: str, start: int, end: int) -> str:
    lo = max(0, start - CONTEXT_CHARS)
    hi = min(len(text), end + CONTEXT_CHARS)
    return text[lo:hi].replace("\n", " ").strip()


def match_readme_direct(repos: list[dict], hf_model_ids: set[str]) -> list[tuple]:
    """Strategy 1: repo README links to a huggingface.co/<model_id> we know."""
    links = []
    for repo in repos:
        readme = repo.get("readme_content") or ""
        if not readme:
            continue
        seen = set()
        for m in HF_URL_RE.finditer(readme):
            candidate = m.group(1)
            if candidate in hf_model_ids and candidate not in seen:
                seen.add(candidate)
                links.append((
                    repo["repo_full_name"], candidate, "readme_direct", 1.00,
                    _context(readme, m.start(), m.end()),
                ))
    return links


def match_modelcard_direct(models: list[dict], gh_repo_names: set[str]) -> list[tuple]:
    """Strategy 2: HF model card links to a github.com/<owner/repo> we know."""
    links = []
    for model in models:
        card = model.get("card_content") or ""
        if not card:
            continue
        seen = set()
        for m in GH_URL_RE.finditer(card):
            candidate = m.group(1)
            # Strip a trailing ".git" the URL form sometimes carries.
            if candidate.endswith(".git"):
                candidate = candidate[:-4]
            if candidate in gh_repo_names and candidate not in seen:
                seen.add(candidate)
                links.append((
                    candidate, model["model_id"], "modelcard_direct", 1.00,
                    _context(card, m.start(), m.end()),
                ))
    return links


def match_same_username(repos: list[dict], models: list[dict],
                        already_linked: set[tuple]) -> list[tuple]:
    """Strategy 3: GitHub owner == HF author. Skips pairs already linked."""
    # bucket HF models by author for an O(n) join instead of O(n*m)
    models_by_author: dict[str, list[str]] = {}
    for model in models:
        mid = model["model_id"]
        if "/" in mid:
            author = mid.split("/", 1)[0].lower()
            models_by_author.setdefault(author, []).append(mid)

    links = []
    for repo in repos:
        rname = repo["repo_full_name"]
        if "/" not in rname:
            continue
        owner = rname.split("/", 1)[0].lower()
        for model_id in models_by_author.get(owner, []):
            if (rname, model_id) in already_linked:
                continue
            links.append((
                rname, model_id, "same_username", 0.70,
                f"github owner '{owner}' == hf author",
            ))
    return links


def _fuzzy_eligible(name_part: str) -> bool:
    return (
        len(name_part) >= FUZZY_MIN_NAME_LEN
        and name_part not in FUZZY_NAME_STOPLIST
    )


def match_fuzzy_name(repos: list[dict], models: list[dict],
                     already_linked: set[tuple], threshold: float) -> list[tuple]:
    """Strategy 4: fuzzy match of the repo name part vs. the model name part.

    Generic names ("lora", "peft", ...) and very short names are excluded on
    BOTH sides -- two repos both named "lora" are not a real link.
    """
    model_names = [
        (m["model_id"], part)
        for m in models
        for part in [m["model_id"].split("/")[-1].lower()]
        if _fuzzy_eligible(part)
    ]
    links = []
    for repo in repos:
        rname = repo["repo_full_name"]
        repo_name_part = rname.split("/")[-1].lower()
        if not _fuzzy_eligible(repo_name_part):
            continue
        for model_id, model_name_part in model_names:
            if (rname, model_id) in already_linked:
                continue
            score = fuzz_ratio(repo_name_part, model_name_part)
            if score >= threshold:
                links.append((
                    rname, model_id, "fuzzy_name", round(score, 2),
                    f"'{repo_name_part}' ~ '{model_name_part}' ({score:.2f})",
                ))
    return links


def report(conn) -> None:
    cursor = conn.cursor()

    cursor.execute(
        "SELECT link_type, COUNT(*), AVG(confidence) "
        "FROM github_hf_links GROUP BY link_type"
    )
    by_type = cursor.fetchall()

    cursor.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT repo_full_name, model_id "
        "FROM github_hf_links) t"
    )
    (unique_pairs,) = cursor.fetchone()

    cursor.execute(
        """
        SELECT CASE
            WHEN confidence >= 0.95 THEN '0.95-1.0 '
            WHEN confidence >= 0.85 THEN '0.85-0.95'
            WHEN confidence >= 0.70 THEN '0.70-0.85'
            ELSE '<0.70    '
        END AS bucket, COUNT(*)
        FROM github_hf_links GROUP BY bucket ORDER BY bucket DESC
        """
    )
    by_conf = cursor.fetchall()

    cursor.execute(
        "SELECT repo_full_name, COUNT(DISTINCT model_id) m "
        "FROM github_hf_links GROUP BY repo_full_name ORDER BY m DESC LIMIT 20"
    )
    top_repos = cursor.fetchall()

    cursor.execute(
        "SELECT repo_full_name, model_id, link_type, confidence "
        "FROM github_hf_links ORDER BY RAND() LIMIT 30"
    )
    sample = cursor.fetchall()
    cursor.close()

    logger.info("=" * 64)
    logger.info("GITHUB <-> HF RECORD LINKER -- RESULTS")
    logger.info("  total unique (repo, model) pairs: %d", unique_pairs)
    logger.info("  by link_type:")
    for ltype, count, avg_conf in by_type:
        logger.info("    %-18s: %5d  (avg confidence %.2f)", ltype, count, avg_conf)
    logger.info("  by confidence bucket:")
    for bucket, count in by_conf:
        logger.info("    %s : %d", bucket, count)
    logger.info("  top 20 repos by matched model count:")
    for rname, m in top_repos:
        logger.info("    %-45s: %d", rname, m)
    logger.info("  30 random sample links for review:")
    for rname, mid, ltype, conf in sample:
        logger.info("    [%-16s %.2f] %-40s -> %s", ltype, conf, rname, mid)
    logger.info("=" * 64)


def main() -> None:
    conn = get_connection()
    init_schema(conn)

    repos = load_github_repos(conn)
    models = load_hf_models(conn)
    logger.info("Loaded %d GitHub repos, %d HF models", len(repos), len(models))

    hf_model_ids = {m["model_id"] for m in models}
    gh_repo_names = {r["repo_full_name"] for r in repos}

    readme_links = match_readme_direct(repos, hf_model_ids)
    card_links = match_modelcard_direct(models, gh_repo_names)
    logger.info("readme_direct: %d, modelcard_direct: %d",
                len(readme_links), len(card_links))

    # pairs claimed by a higher-priority strategy -- lower ones skip them
    linked_pairs = {(link[0], link[1]) for link in readme_links}
    linked_pairs |= {(link[0], link[1]) for link in card_links}

    username_links = match_same_username(repos, models, linked_pairs)
    logger.info("same_username: %d", len(username_links))
    linked_pairs |= {(link[0], link[1]) for link in username_links}

    fuzzy_links = match_fuzzy_name(repos, models, linked_pairs, FUZZY_THRESHOLD)
    logger.info("fuzzy_name: %d (threshold %.2f)", len(fuzzy_links), FUZZY_THRESHOLD)

    all_links = readme_links + card_links + username_links + fuzzy_links
    inserted = insert_links(conn, all_links)
    logger.info("Inserted %d new links (%d generated, rest were duplicates)",
                inserted, len(all_links))

    report(conn)
    conn.close()


if __name__ == "__main__":
    main()
