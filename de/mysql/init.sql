-- ---------------------------------------------------------------------------
-- ML Underground — MySQL schema bootstrap
-- Runs automatically on first MySQL init (mounted into
-- /docker-entrypoint-initdb.d/). Recreates the bronze/enriched tables so the
-- pipeline works after a fresh start / volume wipe.
-- ---------------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS ml_underground;
USE ml_underground;

CREATE TABLE IF NOT EXISTS github_repos_bronze (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    repo_id         BIGINT       NOT NULL UNIQUE,
    repo_name       VARCHAR(255) NOT NULL,
    first_seen_at   DATETIME,
    last_seen_at    DATETIME,
    star_count      INT          DEFAULT 0,
    fork_count      INT          DEFAULT 0,
    event_count     INT          DEFAULT 0,
    INDEX idx_repo_id   (repo_id),
    INDEX idx_repo_name (repo_name)
);

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

CREATE TABLE IF NOT EXISTS huggingface_models_bronze (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    model_id        VARCHAR(255) NOT NULL UNIQUE,   -- "username/model-name"
    author          VARCHAR(128),
    base_model      VARCHAR(255),                   -- "meta-llama/Llama-3.1-8B"
    pipeline_tag    VARCHAR(128),                   -- "text-generation", "image-classification"
    library_name    VARCHAR(128),                   -- "transformers", "peft"
    downloads       INT          DEFAULT 0,
    likes           INT          DEFAULT 0,
    tags            JSON,
    card_content    MEDIUMTEXT,
    created_at      DATETIME,
    last_modified   DATETIME,
    ingested_at     DATETIME,
    INDEX idx_model_id     (model_id),
    INDEX idx_pipeline_tag (pipeline_tag),
    INDEX idx_base_model   (base_model),
    INDEX idx_downloads    (downloads)
);

-- Tracks which repos have been embedded into Qdrant (avoids re-embedding).
CREATE TABLE IF NOT EXISTS github_repos_embedded (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    repo_id         BIGINT       NOT NULL UNIQUE,
    repo_name       VARCHAR(255),
    model           VARCHAR(128),
    embedded_at     DATETIME,
    INDEX idx_repo_id (repo_id)
);

-- Tracks which HF models have been embedded into Qdrant.
CREATE TABLE IF NOT EXISTS hf_models_embedded (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    model_id        VARCHAR(255) NOT NULL UNIQUE,
    model           VARCHAR(128),
    embedded_at     DATETIME,
    INDEX idx_model_id (model_id)
);
