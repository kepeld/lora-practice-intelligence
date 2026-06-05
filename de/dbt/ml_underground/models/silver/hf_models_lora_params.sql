-- Per-HF-model LoRA hyperparameters (Variant D for US-4.2).
-- Same shape as gold.repo_lora_params, but keyed on model_id (Variant D, US-4.2).
-- Built by the extract_hf_cards Airflow task that parses
-- huggingface_models_bronze.card_content with the layered extractor.
{{ config(materialized='table') }}

select
    p.model_id,

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

    -- Model-level context useful downstream
    m.base_model,
    m.pipeline_tag,
    m.library_name,
    m.downloads,
    m.likes
from {{ source('bronze', 'hf_models_lora_params') }} p
left join {{ ref('hf_models') }} m on m.model_id = p.model_id
