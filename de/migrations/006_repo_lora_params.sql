-- Migration 006: per-repo LoRA params after priority merge (Step 4)
--
-- One row per LoRA repo. Built by the merge_to_gold task: groups
-- lora_configs_raw by (repo_full_name, param_name), picks the highest-
-- priority source (AST > JSON > YAML > regex > LLM), and writes the result
-- column-wise.
--
-- New BRONZE source in MySQL: dbt builds gold.repo_lora_params on top of it
-- in Snowflake (the gold schema is built only by dbt, per the medallion rule).
--
-- Naming: column "rank" is a SQL reserved word in many dialects; using
-- "rank_value" avoids needing to quote it everywhere.

CREATE TABLE IF NOT EXISTS repo_lora_params (
    repo_full_name              VARCHAR(255) PRIMARY KEY,

    -- Tier 1 (critical) --------------------------------------------------
    rank_value                  INT,
    lora_alpha                  INT,
    target_modules              JSON,
    -- DOUBLE (not DECIMAL): learning rates can be 1e-6..1.0 with arbitrary
    -- precision; scientific-notation in source files needs floating point.
    learning_rate               DOUBLE,
    optimizer                   VARCHAR(50),

    -- Tier 2 (nice-to-have) ----------------------------------------------
    lora_dropout                DOUBLE,
    lora_bias                   VARCHAR(64),
    scheduler                   VARCHAR(50),
    batch_size                  INT,
    gradient_accumulation_steps INT,
    num_train_epochs            INT,
    warmup_steps                INT,
    bf16                        BOOLEAN,
    fp16                        BOOLEAN,
    gradient_checkpointing      BOOLEAN,
    merge_and_unload            BOOLEAN,

    -- Provenance ---------------------------------------------------------
    param_sources               JSON,         -- {"rank_value":"ast", "optimizer":"yaml", ...}
    total_params_extracted      INT          DEFAULT 0,
    extraction_confidence       DECIMAL(3,2),
    extracted_at                TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_rank      (rank_value),
    INDEX idx_optimizer (optimizer),
    INDEX idx_extracted (extracted_at)
);
