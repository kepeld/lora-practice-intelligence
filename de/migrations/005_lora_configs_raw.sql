-- Migration 005: LoRA-config raw extraction (Step 4, US-3.1 / US-3.2)
--
-- Per-source raw extraction of LoRA hyperparameters from bronze.github_files.
-- Multiple rows per (repo, file) allowed when several params are extracted.
-- A repo's final value is picked in gold.repo_lora_params via a priority
-- merge (AST > JSON > YAML > regex > LLM).
--
-- New BRONZE source: replicated to Snowflake by load_to_snowflake; dbt builds
-- the silver.lora_configs_raw model on top of it.
--
-- INDEX on file_id (not FK): keeps SHA-cache rebuilds of github_files cheap
-- and avoids cascade pain. Referential integrity is checked by a GE
-- expectation instead.
--
-- ENUM keeps 'llm' as forward compatibility for the future LLM fallback
-- (US-3.3, Issue #7) -- this Step 4 produces no LLM rows.

CREATE TABLE IF NOT EXISTS lora_configs_raw (
    config_id       BIGINT AUTO_INCREMENT PRIMARY KEY,
    repo_full_name  VARCHAR(255) NOT NULL,
    file_id         BIGINT       NOT NULL,
    source          ENUM('ast', 'yaml', 'json', 'regex', 'llm') NOT NULL,
    param_name      VARCHAR(100) NOT NULL,
    param_value     TEXT,
    confidence      DECIMAL(3,2) NOT NULL DEFAULT 1.00,
    extracted_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_param (repo_full_name, file_id, source, param_name),
    INDEX idx_repo    (repo_full_name),
    INDEX idx_file    (file_id),
    INDEX idx_param   (param_name),
    INDEX idx_source  (source)
);
