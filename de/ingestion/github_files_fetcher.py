"""GitHub training/config file fetcher for LoRA repos.

Walks each LoRA repo's git tree and stores training scripts + config files in
the `github_files` bronze table. SHA caching makes re-runs cheap and idempotent.

Run:  python -m de.ingestion.github_files_fetcher
   or python github_files_fetcher.py   (from de/ingestion/)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import mysql.connector

# Reuse the enricher's GitHub client (rate-limit handling, tree + contents).
try:
    from de.ingestion.gh_repo_enricher import GITHUB_TOKEN, GitHubClient
except ImportError:
    try:
        from ingestion.gh_repo_enricher import GITHUB_TOKEN, GitHubClient
    except ImportError:
        from gh_repo_enricher import GITHUB_TOKEN, GitHubClient

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

# How many repos to process per run. A re-run picks up where this stopped.
REPO_LIMIT = int(os.getenv("FILES_REPO_LIMIT", "1000"))

# Largest file content we store; bigger files keep metadata, content=NULL.
MAX_FILE_BYTES = int(os.getenv("FILES_MAX_BYTES", str(1 * 1024 * 1024)))  # 1 MB

# Most matched files per repo, guards against a pathological repo.
MAX_FILES_PER_REPO = int(os.getenv("FILES_MAX_PER_REPO", "25"))

REQUEST_DELAY = 0.05

# Exact filenames -> category. Checked on the lowercased basename.
EXACT_NAME_CATEGORY = {
    "adapter_config.json": "adapter_config",
    "requirements.txt": "dependencies",
    "pyproject.toml": "dependencies",
    "environment.yml": "dependencies",
    "environment.yaml": "dependencies",
    "accelerate_config.yaml": "config",
    "deepspeed_config.json": "config",
    "ds_config.json": "config",
    "training_args.json": "config",
    "training_args.bin": None,  # binary -- recorded below as a hard skip
}

# A training script: a .py file whose basename signals training/finetuning.
TRAIN_SCRIPT_KEYWORDS = ("train", "finetune", "fine_tune", "sft", "run_lora",
                         "run_peft", "run_clm", "run_sft")

# Config files: by extension, when the path hints at training/lora config.
CONFIG_EXTENSIONS = (".yaml", ".yml", ".json", ".toml")
CONFIG_PATH_HINTS = ("config", "lora", "peft", "train", "accelerate",
                     "deepspeed", "recipe")

# Never store these even if a rule matches (binary / lock noise).
HARD_SKIP_SUFFIXES = (".bin", ".safetensors", ".lock", ".png", ".jpg", ".onnx")


def classify(path: str) -> str | None:
    """Return the github_files.file_category for a tree path, or None to skip."""
    lower = path.lower()
    if lower.endswith(HARD_SKIP_SUFFIXES):
        return None

    base = lower.rsplit("/", 1)[-1]

    exact = EXACT_NAME_CATEGORY.get(base)
    if exact is not None:
        return exact
    if base in EXACT_NAME_CATEGORY:  # mapped to None -> explicit skip
        return None

    if base.endswith(".py") and any(k in base for k in TRAIN_SCRIPT_KEYWORDS):
        return "training_script"

    if lower.endswith(CONFIG_EXTENSIONS) and any(h in lower for h in CONFIG_PATH_HINTS):
        return "config"

    return None


def get_connection():
    return mysql.connector.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
        password=MYSQL_PASSWORD, database=MYSQL_DATABASE,
    )


def init_schema(conn) -> None:
    """Create github_files if absent (mirrors migration 004)."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS github_files (
            file_id         BIGINT AUTO_INCREMENT PRIMARY KEY,
            repo_full_name  VARCHAR(255) NOT NULL,
            file_path       VARCHAR(512) NOT NULL,
            file_category   ENUM('training_script', 'config', 'dependencies',
                                 'adapter_config') NOT NULL,
            file_sha        VARCHAR(64)  NOT NULL,
            file_size       INT          DEFAULT 0,
            content         MEDIUMTEXT,
            truncated       BOOLEAN      DEFAULT FALSE,
            fetched_at      DATETIME     NOT NULL,
            UNIQUE KEY uk_file (repo_full_name, file_path),
            INDEX idx_repo     (repo_full_name),
            INDEX idx_category (file_category),
            INDEX idx_sha      (file_sha)
        )
        """
    )
    conn.commit()
    cursor.close()
    logger.info("github_files schema ready")


def load_target_repos(conn, limit: int) -> list[str]:
    """ML-LoRA repos to process (enrichment_status='ok' excludes radio-LoRa)."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT repo_name FROM github_repos_enriched
        WHERE enrichment_status = 'ok'
        ORDER BY repo_id
        LIMIT %s
        """,
        (limit,),
    )
    rows = [r[0] for r in cursor.fetchall()]
    cursor.close()
    return rows


def existing_shas(conn, repo_full_name: str) -> dict[str, str]:
    """Map file_path -> stored file_sha for a repo (SHA-cache lookup)."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT file_path, file_sha FROM github_files WHERE repo_full_name = %s",
        (repo_full_name,),
    )
    out = {path: sha for path, sha in cursor.fetchall()}
    cursor.close()
    return out


def upsert_file(conn, row: dict) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO github_files
            (repo_full_name, file_path, file_category, file_sha,
             file_size, content, truncated, fetched_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            file_category = VALUES(file_category),
            file_sha      = VALUES(file_sha),
            file_size     = VALUES(file_size),
            content       = VALUES(content),
            truncated     = VALUES(truncated),
            fetched_at    = VALUES(fetched_at)
        """,
        (
            row["repo_full_name"], row["file_path"], row["file_category"],
            row["file_sha"], row["file_size"], row["content"],
            row["truncated"], datetime.now(timezone.utc),
        ),
    )
    conn.commit()
    cursor.close()


def fetch_repo_files(client: GitHubClient, conn, repo_full_name: str) -> dict:
    """Fetch new/changed training+config files for one repo; returns stats dict."""
    stats = {"matched": 0, "fetched": 0, "cached": 0, "skipped": 0}

    tree = client.get_tree(repo_full_name, "HEAD")
    if not tree:
        stats["skipped"] = -1  # tree unavailable (empty repo / 404)
        return stats
    if tree.get("truncated"):
        # GitHub caps recursive trees (~100k entries / 7 MB); a partial listing
        # hides some training/config files. Record + surface it instead of
        # silently treating the repo as having no such files.
        stats["truncated"] = 1
        logger.warning("%s: git tree truncated -- file inventory incomplete", repo_full_name)
    time.sleep(REQUEST_DELAY)

    cache = existing_shas(conn, repo_full_name)

    candidates = []
    for entry in tree.get("tree", []):
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        category = classify(path)
        if category:
            candidates.append((path, category, entry.get("sha", "")))
    candidates = candidates[:MAX_FILES_PER_REPO]
    stats["matched"] = len(candidates)

    for path, category, sha in candidates:
        # SHA cache: skip files whose blob is unchanged since last run.
        if cache.get(path) == sha and sha:
            stats["cached"] += 1
            continue

        content = client.get_file_content(repo_full_name, path)
        time.sleep(REQUEST_DELAY)

        truncated = False
        if content is None:
            # binary or unfetchable -- record metadata, no content
            file_size = 0
        else:
            raw = content.encode("utf-8", errors="ignore")
            file_size = len(raw)
            if file_size > MAX_FILE_BYTES:
                # truncate on bytes (not chars) so the stored text stays within
                # the byte budget and file_size matches what we actually keep.
                content = raw[:MAX_FILE_BYTES].decode("utf-8", errors="ignore")
                file_size = len(content.encode("utf-8"))
                truncated = True

        upsert_file(conn, {
            "repo_full_name": repo_full_name,
            "file_path": path,
            "file_category": category,
            "file_sha": sha or "unknown",
            "file_size": file_size,
            "content": content,
            "truncated": truncated,
        })
        stats["fetched"] += 1

    return stats


def report(conn) -> None:
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM github_files")
    (total_files,) = cursor.fetchone()

    cursor.execute("SELECT COUNT(DISTINCT repo_full_name) FROM github_files")
    (repos_with_files,) = cursor.fetchone()

    cursor.execute(
        "SELECT file_category, COUNT(*) FROM github_files GROUP BY file_category"
    )
    by_category = cursor.fetchall()

    cursor.execute(
        "SELECT SUM(truncated), AVG(file_size) FROM github_files"
    )
    truncated, avg_size = cursor.fetchone()

    cursor.execute(
        "SELECT repo_full_name, COUNT(*) c FROM github_files "
        "GROUP BY repo_full_name ORDER BY c DESC LIMIT 15"
    )
    top_repos = cursor.fetchall()
    cursor.close()

    logger.info("=" * 64)
    logger.info("GITHUB FILES FETCHER -- RESULTS")
    logger.info("  total files stored: %d", total_files)
    logger.info("  repos with >=1 file: %d", repos_with_files)
    logger.info("  by file_category:")
    for cat, count in by_category:
        logger.info("    %-18s: %d", cat, count)
    logger.info("  truncated (size-capped): %s", truncated or 0)
    logger.info("  avg file size: %.0f bytes", avg_size or 0)
    logger.info("  top 15 repos by file count:")
    for rname, c in top_repos:
        logger.info("    %-48s: %d", rname, c)
    logger.info("=" * 64)


def main() -> None:
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set. Add it to your .env file.")

    client = GitHubClient(GITHUB_TOKEN)
    conn = get_connection()
    init_schema(conn)

    repos = load_target_repos(conn, REPO_LIMIT)
    logger.info("Processing %d LoRA repos", len(repos))

    totals = {"matched": 0, "fetched": 0, "cached": 0, "empty": 0}
    for i, repo in enumerate(repos, start=1):
        try:
            stats = fetch_repo_files(client, conn, repo)
            if stats["skipped"] == -1:
                totals["empty"] += 1
            else:
                totals["matched"] += stats["matched"]
                totals["fetched"] += stats["fetched"]
                totals["cached"] += stats["cached"]
            if i % 50 == 0:
                logger.info("[%d/%d] processed | fetched so far: %d",
                            i, len(repos), totals["fetched"])
        except Exception as e:
            logger.error("Failed on %s: %s", repo, e)

    logger.info("Done: matched=%d fetched=%d cached(skip)=%d empty_repos=%d",
                totals["matched"], totals["fetched"], totals["cached"],
                totals["empty"])
    report(conn)
    conn.close()


if __name__ == "__main__":
    main()
