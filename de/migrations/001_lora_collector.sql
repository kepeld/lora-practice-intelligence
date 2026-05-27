-- Migration 001: targeted LoRA collector
--
-- Adds a discovery-tracking table for the one-time LoRA backfill. The backfill
-- itself writes enriched rows to the existing `github_repos_enriched` table
-- (created by gh_repo_enricher); this table records which repos the GitHub
-- Search API surfaced, via which query, so a re-run is idempotent and can skip
-- repos already discovered + enriched.

CREATE TABLE IF NOT EXISTS lora_search_discovery (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    repo_id         BIGINT       NOT NULL UNIQUE,
    repo_name       VARCHAR(255) NOT NULL,
    search_source   VARCHAR(32)  NOT NULL,   -- 'repo_search' | 'code_search'
    search_query    VARCHAR(512),            -- the query that surfaced this repo
    discovered_at   DATETIME     NOT NULL,
    enriched        BOOLEAN      DEFAULT FALSE,
    INDEX idx_repo_id   (repo_id),
    INDEX idx_source    (search_source),
    INDEX idx_enriched  (enriched)
);
