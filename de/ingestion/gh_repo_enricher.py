"""
Repository Enrichment Service

Reads unenriched repositories from github_repos_bronze,
fetches additional metadata from the GitHub API, and writes
the result to github_repos_enriched.

Enriched fields:
  - README content (for embeddings / RAG)
  - topics
  - primary language
  - dependencies (requirements.txt / pyproject.toml / package.json)
  - description
  - license
  - open issues count
  - latest commit date
"""

import base64
import logging
import os
import time
from datetime import datetime

import mysql.connector
import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_API_BASE = "https://api.github.com"

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ml_underground")

# How many repos to enrich per run
BATCH_SIZE = 50

# Seconds to wait between GitHub API requests (rate limit: 5000/hr with token)
REQUEST_DELAY = 0.05

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MySQL schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS github_repos_enriched (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    repo_id             BIGINT          NOT NULL UNIQUE,
    repo_name           VARCHAR(255)    NOT NULL,
    description         TEXT,
    primary_language    VARCHAR(64),
    topics              JSON,
    license             VARCHAR(128),
    open_issues_count   INT             DEFAULT 0,
    readme_content      MEDIUMTEXT,
    dependencies        JSON,
    latest_commit_at    DATETIME,
    enriched_at         DATETIME,
    enrichment_status   VARCHAR(32)     DEFAULT 'ok',
    INDEX idx_repo_id       (repo_id),
    INDEX idx_language      (primary_language),
    INDEX idx_enriched_at   (enriched_at)
);
"""


# ---------------------------------------------------------------------------
# GitHub API client
# ---------------------------------------------------------------------------

class GitHubClient:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def get(self, path: str) -> dict | None:
        """Make a GET request to the GitHub API. Returns None on 404."""
        url = f"{GITHUB_API_BASE}{path}"
        try:
            response = self.session.get(url, timeout=10)

            # Check rate limit
            remaining = int(response.headers.get("X-RateLimit-Remaining", 999))
            if remaining < 10:
                reset_at = int(response.headers.get("X-RateLimit-Reset", 0))
                wait = max(reset_at - time.time(), 0) + 5
                logger.warning("Rate limit low (%d remaining). Sleeping %.0fs", remaining, wait)
                time.sleep(wait)

            if response.status_code == 404:
                return None
            if response.status_code == 403:
                logger.warning("403 Forbidden for %s — skipping", path)
                return None

            response.raise_for_status()
            return response.json()

        except requests.RequestException as e:
            logger.error("Request failed for %s: %s", path, e)
            return None

    def get_repo(self, repo_name: str) -> dict | None:
        return self.get(f"/repos/{repo_name}")

    def get_readme(self, repo_name: str) -> str | None:
        """Fetch and decode the README content."""
        data = self.get(f"/repos/{repo_name}/readme")
        if not data:
            return None
        try:
            content = data.get("content", "")
            encoding = data.get("encoding", "base64")
            if encoding == "base64":
                return base64.b64decode(content).decode("utf-8", errors="replace")
            return content
        except Exception as e:
            logger.warning("Failed to decode README for %s: %s", repo_name, e)
            return None

    def get_topics(self, repo_name: str) -> list:
        data = self.get(f"/repos/{repo_name}/topics")
        if not data:
            return []
        return data.get("names", [])

    def get_dependencies(self, repo_name: str) -> dict:
        """
        Try to fetch dependency files in order of preference.
        Returns a dict with the file name and raw content.
        """
        dependency_files = [
            "requirements.txt",
            "pyproject.toml",
            "setup.py",
            "package.json",
            "Pipfile",
        ]
        for filename in dependency_files:
            data = self.get(f"/repos/{repo_name}/contents/{filename}")
            if data and data.get("encoding") == "base64":
                try:
                    content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                    return {"file": filename, "content": content[:5000]}  # cap at 5KB
                except Exception:
                    continue
        return {}

    def get_latest_commit(self, repo_name: str) -> str | None:
        """Return ISO timestamp of the latest commit on the default branch."""
        data = self.get(f"/repos/{repo_name}/commits?per_page=1")
        if not data or not isinstance(data, list):
            return None
        try:
            return data[0]["commit"]["committer"]["date"]
        except (KeyError, IndexError):
            return None


# ---------------------------------------------------------------------------
# MySQL helpers
# ---------------------------------------------------------------------------

def get_connection():
    return mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
    )


def init_schema(conn):
    cursor = conn.cursor()
    for statement in SCHEMA_SQL.strip().split(";"):
        s = statement.strip()
        if s:
            cursor.execute(s)
    conn.commit()
    cursor.close()
    logger.info("Schema initialized")


def fetch_unenriched_repos(conn, limit: int) -> list:
    """
    Return repos from bronze that have not yet been enriched.
    Uses a LEFT JOIN to find repos missing from the enriched table.
    """
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT b.repo_id, b.repo_name
        FROM github_repos_bronze b
        LEFT JOIN github_repos_enriched e ON b.repo_id = e.repo_id
        WHERE e.repo_id IS NULL
        ORDER BY b.event_count DESC
        LIMIT %s
        """,
        (limit,),
    )
    rows = cursor.fetchall()
    cursor.close()
    return rows


def upsert_enriched(conn, data: dict):
    import json
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO github_repos_enriched
            (repo_id, repo_name, description, primary_language, topics,
             license, open_issues_count, readme_content, dependencies,
             latest_commit_at, enriched_at, enrichment_status)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            description         = VALUES(description),
            primary_language    = VALUES(primary_language),
            topics              = VALUES(topics),
            license             = VALUES(license),
            open_issues_count   = VALUES(open_issues_count),
            readme_content      = VALUES(readme_content),
            dependencies        = VALUES(dependencies),
            latest_commit_at    = VALUES(latest_commit_at),
            enriched_at         = VALUES(enriched_at),
            enrichment_status   = VALUES(enrichment_status)
        """,
        (
            data["repo_id"],
            data["repo_name"],
            data.get("description"),
            data.get("primary_language"),
            json.dumps(data.get("topics", [])),
            data.get("license"),
            data.get("open_issues_count", 0),
            data.get("readme_content"),
            json.dumps(data.get("dependencies", {})),
            data.get("latest_commit_at"),
            datetime.utcnow(),
            data.get("enrichment_status", "ok"),
        ),
    )
    conn.commit()
    cursor.close()


# ---------------------------------------------------------------------------
# Enrichment logic
# ---------------------------------------------------------------------------

def enrich_repo(client: GitHubClient, repo_id: int, repo_name: str) -> dict:
    """
    Fetch all enrichment data for a single repository.
    Returns a dict ready for upsert_enriched().
    """
    result = {
        "repo_id": repo_id,
        "repo_name": repo_name,
        "enrichment_status": "ok",
    }

    # Core repo metadata
    repo_data = client.get_repo(repo_name)
    if not repo_data:
        result["enrichment_status"] = "not_found"
        return result

    result["description"] = repo_data.get("description")
    result["primary_language"] = repo_data.get("language")
    result["open_issues_count"] = repo_data.get("open_issues_count", 0)

    license_info = repo_data.get("license")
    result["license"] = license_info.get("spdx_id") if license_info else None

    # Topics (requires separate API call)
    result["topics"] = client.get_topics(repo_name)
    time.sleep(REQUEST_DELAY)

    # README
    result["readme_content"] = client.get_readme(repo_name)
    time.sleep(REQUEST_DELAY)

    # Dependencies
    result["dependencies"] = client.get_dependencies(repo_name)
    time.sleep(REQUEST_DELAY)

    # Latest commit
    latest_commit_raw = client.get_latest_commit(repo_name)
    if latest_commit_raw:
        try:
            result["latest_commit_at"] = datetime.fromisoformat(
                latest_commit_raw.replace("Z", "+00:00")
            )
        except ValueError:
            pass
    time.sleep(REQUEST_DELAY)

    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set. Add it to your .env file.")

    client = GitHubClient(GITHUB_TOKEN)
    conn = get_connection()
    init_schema(conn)

    total_enriched = 0

    while True:
        repos = fetch_unenriched_repos(conn, BATCH_SIZE)

        if not repos:
            logger.info("No unenriched repos found. Sleeping 5 minutes.")
            time.sleep(300)
            continue

        logger.info("Enriching %d repositories", len(repos))

        for repo in repos:
            repo_name = repo["repo_name"]
            repo_id = repo["repo_id"]

            try:
                data = enrich_repo(client, repo_id, repo_name)
                upsert_enriched(conn, data)
                total_enriched += 1

                status = data.get("enrichment_status", "ok")
                readme_len = len(data.get("readme_content") or "")
                logger.info(
                    "[%d] %s | status=%s | readme=%d chars | lang=%s | topics=%s",
                    total_enriched,
                    repo_name,
                    status,
                    readme_len,
                    data.get("primary_language"),
                    data.get("topics", []),
                )

            except Exception as e:
                logger.error("Failed to enrich %s: %s", repo_name, e)
                upsert_enriched(conn, {
                    "repo_id": repo_id,
                    "repo_name": repo_name,
                    "enrichment_status": "error",
                })


if __name__ == "__main__":
    main()
