-- Migration 002: targeted HuggingFace LoRA collector
--
-- The organic `hf_ingestion` task collects newest models indiscriminately.
-- This migration prepares `huggingface_models_bronze` for a targeted LoRA
-- backfill (hf_targeted_collector) and adds a discovery-tracking table,
-- mirroring the GitHub side (migration 001).
--
-- MySQL 8.0 has no ADD COLUMN IF NOT EXISTS, so each column add is guarded
-- against information_schema to keep this migration re-runnable.

-- collection_source: 'organic' (hourly hf_ingestion) | 'targeted_lora' (backfill)
SET @col_source := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'huggingface_models_bronze'
      AND column_name = 'collection_source'
);
SET @sql := IF(@col_source = 0,
    'ALTER TABLE huggingface_models_bronze
       ADD COLUMN collection_source VARCHAR(30) NOT NULL DEFAULT ''organic''',
    'SELECT ''collection_source already exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- is_lora_relevant: flagged TRUE by the targeted collector
SET @col_lora := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'huggingface_models_bronze'
      AND column_name = 'is_lora_relevant'
);
SET @sql := IF(@col_lora = 0,
    'ALTER TABLE huggingface_models_bronze
       ADD COLUMN is_lora_relevant BOOLEAN NOT NULL DEFAULT FALSE',
    'SELECT ''is_lora_relevant already exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- idx_source
SET @idx_source := (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'huggingface_models_bronze'
      AND index_name = 'idx_source'
);
SET @sql := IF(@idx_source = 0,
    'ALTER TABLE huggingface_models_bronze ADD INDEX idx_source (collection_source)',
    'SELECT ''idx_source already exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- idx_lora
SET @idx_lora := (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'huggingface_models_bronze'
      AND index_name = 'idx_lora'
);
SET @sql := IF(@idx_lora = 0,
    'ALTER TABLE huggingface_models_bronze ADD INDEX idx_lora (is_lora_relevant)',
    'SELECT ''idx_lora already exists''');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Discovery tracking for the targeted HF collector. Records which HF Hub
-- search surfaced which model, so a re-run is idempotent.
CREATE TABLE IF NOT EXISTS hf_lora_search_discovery (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    model_id        VARCHAR(255) NOT NULL UNIQUE,
    search_query    VARCHAR(255),            -- the query that surfaced this model
    discovered_at   DATETIME     NOT NULL,
    ingested        BOOLEAN      DEFAULT FALSE,
    INDEX idx_model_id  (model_id),
    INDEX idx_ingested  (ingested)
);
