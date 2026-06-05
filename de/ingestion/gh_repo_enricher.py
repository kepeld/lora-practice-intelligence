"""Repository enrichment — drains the lora_search_discovery backlog (repos the
targeted collector discovered but that are not yet in github_repos_enriched),
fetches GitHub API metadata, and writes github_repos_enriched. Mirrors the
hourly repo_enricher task."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

import mysql.connector
import requests
from dotenv import load_dotenv

load_dotenv()

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

# Root-level dependency files, in order of preference
DEP_FILES = ["requirements.txt", "pyproject.toml", "setup.py", "package.json"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

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
    readme_length       INT             DEFAULT 0,
    dependencies        JSON,
    repo_created_at     DATETIME,
    repo_size_kb        INT             DEFAULT 0,
    has_tests           BOOLEAN         DEFAULT FALSE,
    has_ci              BOOLEAN         DEFAULT FALSE,
    contributors_count  INT             DEFAULT 0,
    commit_count_30d    INT             DEFAULT 0,
    is_fork             BOOLEAN         DEFAULT FALSE,
    is_archived         BOOLEAN         DEFAULT FALSE,
    pushed_at           DATETIME,
    forks_count         INT             DEFAULT 0,
    subscribers_count   INT             DEFAULT 0,
    homepage            VARCHAR(512),
    enriched_at         DATETIME,
    enrichment_status   VARCHAR(32)     DEFAULT 'ok',
    INDEX idx_repo_id       (repo_id),
    INDEX idx_language      (primary_language),
    INDEX idx_enriched_at   (enriched_at)
);
"""

def parse_dt(value: str | None) -> datetime | None:
    """Parse a GitHub ISO timestamp into a naive UTC datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None

def decode_content(blob: dict | None) -> str | None:
    """Decode a base64 GitHub readme/contents blob into text."""
    if blob and blob.get("encoding") == "base64":
        try:
            return base64.b64decode(blob["content"]).decode("utf-8", errors="replace")
        except Exception:
            return None
    return None

def analyze_tree(tree: dict | None):
    """From a recursive git tree, derive (has_tests, has_ci, root dep file)."""
    has_tests = has_ci = False
    root_files = set()
    for entry in (tree or {}).get("tree", []):
        path = entry.get("path", "")
        lower = path.lower()
        parts = lower.split("/")
        base = parts[-1]
        if not has_tests and (
            "test" in parts or "tests" in parts
            or base.startswith("test_") or base.endswith("_test.py")
            or base.endswith(".test.js") or base.endswith(".spec.js")
        ):
            has_tests = True
        if not has_ci and (
            lower.startswith(".github/workflows/")
            or lower.startswith(".circleci/")
            or base in (".travis.yml", ".gitlab-ci.yml", "jenkinsfile")
        ):
            has_ci = True
        if "/" not in path:
            root_files.add(base)
    dep_path = next((d for d in DEP_FILES if d in root_files), None)
    return has_tests, has_ci, dep_path

class GitHubClient:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _request(self, path: str):
        """Raw GET with rate-limit handling. Returns the response or None."""
        try:
            response = self.session.get(f"{GITHUB_API_BASE}{path}", timeout=10)
            remaining = int(response.headers.get("X-RateLimit-Remaining", 999))
            if remaining < 10:
                reset_at = int(response.headers.get("X-RateLimit-Reset", 0))
                wait = max(reset_at - time.time(), 0) + 5
                logger.warning(
                    "Rate limit low (%d remaining). Sleeping %.0fs", remaining, wait
                )
                time.sleep(wait)
            return response
        except requests.RequestException as e:
            logger.error("Request failed for %s: %s", path, e)
            return None

    def get(self, path: str) -> dict | None:
        """GET returning parsed JSON, or None for any non-200 response."""
        response = self._request(path)
        if response is None or response.status_code != 200:
            return None
        return response.json()

    def count_via_pagination(self, path: str) -> int:
        """Item count via the Link rel="last" page number (use per_page=1)."""
        response = self._request(path)
        if response is None or response.status_code != 200:
            return 0
        match = re.search(
            r'[?&]page=(\d+)>;\s*rel="last"', response.headers.get("Link", "")
        )
        if match:
            return int(match.group(1))
        body = response.json()
        return len(body) if isinstance(body, list) else 0

    def get_repo(self, repo_name: str) -> dict | None:
        return self.get(f"/repos/{repo_name}")

    def get_readme(self, repo_name: str) -> str | None:
        return decode_content(self.get(f"/repos/{repo_name}/readme"))

    def get_tree(self, repo_name: str, branch: str) -> dict | None:
        return self.get(f"/repos/{repo_name}/git/trees/{branch}?recursive=1")

    def get_file_content(self, repo_name: str, path: str) -> str | None:
        return decode_content(self.get(f"/repos/{repo_name}/contents/{path}"))

    def count_contributors(self, repo_name: str) -> int:
        return self.count_via_pagination(
            f"/repos/{repo_name}/contributors?per_page=1&anon=true"
        )

    def count_commits_since(self, repo_name: str, since_iso: str) -> int:
        return self.count_via_pagination(
            f"/repos/{repo_name}/commits?since={since_iso}&per_page=1"
        )

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
    """Discovered LoRA repos (lora_search_discovery) not yet in github_repos_enriched."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT d.repo_id, d.repo_name
        FROM lora_search_discovery d
        LEFT JOIN github_repos_enriched e ON d.repo_id = e.repo_id
        WHERE e.repo_id IS NULL
        ORDER BY d.discovered_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    rows = cursor.fetchall()
    cursor.close()
    return rows

def upsert_enriched(conn, data: dict):
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO github_repos_enriched
            (repo_id, repo_name, description, primary_language, topics,
             license, open_issues_count, readme_content, readme_length,
             dependencies, repo_created_at, repo_size_kb, has_tests, has_ci,
             contributors_count, commit_count_30d, is_fork, is_archived,
             pushed_at, forks_count, subscribers_count, homepage,
             enriched_at, enrichment_status)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
             %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            description         = VALUES(description),
            primary_language    = VALUES(primary_language),
            topics              = VALUES(topics),
            license             = VALUES(license),
            open_issues_count   = VALUES(open_issues_count),
            readme_content      = VALUES(readme_content),
            readme_length       = VALUES(readme_length),
            dependencies        = VALUES(dependencies),
            repo_created_at     = VALUES(repo_created_at),
            repo_size_kb        = VALUES(repo_size_kb),
            has_tests           = VALUES(has_tests),
            has_ci              = VALUES(has_ci),
            contributors_count  = VALUES(contributors_count),
            commit_count_30d    = VALUES(commit_count_30d),
            is_fork             = VALUES(is_fork),
            is_archived         = VALUES(is_archived),
            pushed_at           = VALUES(pushed_at),
            forks_count         = VALUES(forks_count),
            subscribers_count   = VALUES(subscribers_count),
            homepage            = VALUES(homepage),
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
            data.get("readme_length", 0),
            json.dumps(data.get("dependencies", {})),
            data.get("repo_created_at"),
            data.get("repo_size_kb", 0),
            data.get("has_tests", False),
            data.get("has_ci", False),
            data.get("contributors_count", 0),
            data.get("commit_count_30d", 0),
            data.get("is_fork", False),
            data.get("is_archived", False),
            data.get("pushed_at"),
            data.get("forks_count", 0),
            data.get("subscribers_count", 0),
            data.get("homepage"),
            datetime.now(timezone.utc),
            data.get("enrichment_status", "ok"),
        ),
    )
    conn.commit()
    cursor.close()

def enrich_repo(client: GitHubClient, repo_id: int, repo_name: str) -> dict:
    """Fetch all enrichment data for a single repository."""
    result = {"repo_id": repo_id, "repo_name": repo_name, "enrichment_status": "ok"}

    # --- 1x /repos: metadata fields ---
    repo_data = client.get_repo(repo_name)
    if not repo_data:
        result["enrichment_status"] = "not_found"
        return result

    license_info = repo_data.get("license") or {}
    result["description"] = repo_data.get("description")
    result["primary_language"] = repo_data.get("language")
    result["topics"] = repo_data.get("topics", [])
    result["license"] = license_info.get("spdx_id")
    result["open_issues_count"] = repo_data.get("open_issues_count", 0)
    result["repo_created_at"] = parse_dt(repo_data.get("created_at"))
    result["pushed_at"] = parse_dt(repo_data.get("pushed_at"))
    result["repo_size_kb"] = repo_data.get("size", 0)
    result["forks_count"] = repo_data.get("forks_count", 0)
    result["subscribers_count"] = repo_data.get("subscribers_count", 0)
    result["is_fork"] = bool(repo_data.get("fork", False))
    result["is_archived"] = bool(repo_data.get("archived", False))
    result["homepage"] = repo_data.get("homepage") or None
    default_branch = repo_data.get("default_branch")

    # --- 1x recursive tree: has_tests, has_ci, locate dep file ---
    has_tests = has_ci = False
    dep_path = None
    if default_branch:
        has_tests, has_ci, dep_path = analyze_tree(
            client.get_tree(repo_name, default_branch)
        )
        time.sleep(REQUEST_DELAY)
    result["has_tests"] = has_tests
    result["has_ci"] = has_ci

    # --- README ---
    readme = client.get_readme(repo_name)
    result["readme_content"] = readme
    result["readme_length"] = len(readme) if readme else 0
    time.sleep(REQUEST_DELAY)

    # --- dependency file (only the one the tree located) ---
    deps = {}
    if dep_path:
        content = client.get_file_content(repo_name, dep_path)
        if content:
            deps = {"file": dep_path, "content": content[:5000]}  # cap at 5KB
        time.sleep(REQUEST_DELAY)
    result["dependencies"] = deps

    # --- 2 expensive pagination counts ---
    since_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    result["contributors_count"] = client.count_contributors(repo_name)
    time.sleep(REQUEST_DELAY)
    result["commit_count_30d"] = client.count_commits_since(repo_name, since_30d)
    time.sleep(REQUEST_DELAY)

    return result

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
                logger.info(
                    "[%d] %s | status=%s | readme=%d | lang=%s | "
                    "tests=%s ci=%s contributors=%d commits30d=%d",
                    total_enriched,
                    repo_name,
                    data.get("enrichment_status", "ok"),
                    data.get("readme_length", 0),
                    data.get("primary_language"),
                    data.get("has_tests", False),
                    data.get("has_ci", False),
                    data.get("contributors_count", 0),
                    data.get("commit_count_30d", 0),
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
