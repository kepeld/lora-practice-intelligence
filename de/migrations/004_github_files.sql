-- Migration 004: GitHub training/config file extraction
--
-- Bronze table for the file-extraction step. github_files_fetcher walks the
-- recursive git tree of each LoRA repo (github_repos_enriched, status='ok'),
-- selects training scripts + config files, and stores their content here so
-- the LoRA-practice analysis can mine hyperparameters from real code.
--
-- file_sha is the GitHub blob SHA. A re-run compares the tree's current SHA
-- against the stored one and only re-fetches changed files (SHA caching).
--
-- New BRONZE source: replicated to DuckDB by load_to_duckdb.

CREATE TABLE IF NOT EXISTS github_files (
    file_id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    repo_full_name  VARCHAR(255) NOT NULL,
    file_path       VARCHAR(512) NOT NULL,
    file_category   ENUM('training_script', 'config', 'dependencies',
                         'adapter_config') NOT NULL,
    file_sha        VARCHAR(64)  NOT NULL,    -- GitHub blob SHA, for caching
    file_size       INT          DEFAULT 0,
    content         MEDIUMTEXT,               -- NULL if skipped (too large/binary)
    truncated       BOOLEAN      DEFAULT FALSE,-- TRUE if content was size-capped
    fetched_at      DATETIME     NOT NULL,
    UNIQUE KEY uk_file (repo_full_name, file_path),
    INDEX idx_repo     (repo_full_name),
    INDEX idx_category (file_category),
    INDEX idx_sha      (file_sha)
);
