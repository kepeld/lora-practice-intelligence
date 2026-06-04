-- Migration 007: per-HF-model LoRA hyperparameters (Variant D for US-4.2).
--
-- Mirror of `repo_lora_params` but keyed on HF model_id instead of GitHub
-- repo_full_name. Used by gold.lora_practice_stats to compute common/rare
-- prevalence statistics WITHOUT needing GitHub↔HF linkage — outcomes
-- (downloads/likes/fan-out) and extracted params live on the same model_id.
--
-- The merge logic and column types mirror migration 006; only the key
-- changes. DOUBLE for learning_rate/lora_dropout (scientific notation),
-- VARCHAR(64) for lora_bias (matches widened col on repo_lora_params).
--
-- Replicated to Snowflake by load_to_snowflake; dbt builds
-- silver.hf_models_lora_params on top.

CREATE TABLE IF NOT EXISTS hf_models_lora_params (
    model_id                    VARCHAR(255) PRIMARY KEY,

    -- Tier 1
    rank_value                  INT,
    lora_alpha                  INT,
    target_modules              JSON,
    learning_rate               DOUBLE,
    optimizer                   VARCHAR(50),

    -- Tier 2
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

    -- Provenance
    param_sources               JSON,
    total_params_extracted      INT          DEFAULT 0,
    extraction_confidence       DECIMAL(3,2),
    extracted_at                TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_rank      (rank_value),
    INDEX idx_optimizer (optimizer),
    INDEX idx_extracted (extracted_at)
);
