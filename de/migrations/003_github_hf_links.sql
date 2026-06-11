-- Migration 003: GitHub <-> HuggingFace record linkage
--
-- Bronze table for the record-linkage step. github_hf_linker derives links
-- between GitHub LoRA repos (github_repos_enriched) and HF models
-- (huggingface_models_bronze) without any API calls -- purely from text
-- already stored (READMEs, model cards, owner/author names).
--
-- This is a new BRONZE source, replicated into the DuckDB warehouse's BRONZE
-- schema by load_to_duckdb and refined into SILVER by the dbt model
-- silver_github_hf_links.
--
-- repo_full_name holds the GitHub "owner/name" string (what regex matches and
-- what same_username/fuzzy_name compare on) -- NOT the numeric repo_id.

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
);
