-- Per-repo LoRA hyperparameters after the priority merge (US-3.1, US-3.2).
-- Built by the lora_extraction_dag in MySQL and replicated to the DuckDB
-- BRONZE schema; this model just promotes it to the gold layer and joins
-- repo-level enrichment context for analyst convenience.
{{ config(materialized='table') }}

select
    p.repo_full_name,

    -- Tier 1
    p.rank_value,
    p.lora_alpha,
    p.target_modules,
    p.learning_rate,
    p.optimizer,

    -- Tier 2
    p.lora_dropout,
    p.lora_bias,
    p.scheduler,
    p.batch_size,
    p.gradient_accumulation_steps,
    p.num_train_epochs,
    p.warmup_steps,
    p.bf16,
    p.fp16,
    p.gradient_checkpointing,
    p.merge_and_unload,

    -- Provenance
    p.param_sources,
    p.total_params_extracted,
    p.extraction_confidence,
    p.extracted_at,

    -- Repo-level context useful for downstream analysis (US-4.2).
    r.primary_language,
    r.star_count,
    r.contributors_count,
    r.has_tests,
    r.has_ci
from {{ source('bronze', 'repo_lora_params') }} p
left join {{ ref('repos') }} r
       on p.repo_full_name = r.repo_name
