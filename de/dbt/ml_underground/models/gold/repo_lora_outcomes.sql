-- Preliminary success-score mart for LoRA models (US-4.1).
--
-- The weights below (0.4 / 0.3 / 0.3) are a placeholder so the downstream
-- insights pipeline has a working number to consume until the real formula
-- lands in Issue #6. The log-transform is applied because downloads / likes /
-- fan-out are heavy-tailed (a handful of models with millions, the rest with
-- hundreds).
--
-- Grain: one row per HuggingFace model.
-- Joins:
--   * hf_models       — base metrics (downloads, likes, base_model)
--   * hf_model_tree   — number of fine-tunes that derive from THIS model
--                       (this is the `fine_tune_fan_out` factor)
{{ config(materialized='table') }}

with hf as (

    select
        model_id,
        author,
        base_model,
        pipeline_tag,
        library_name,
        downloads,
        likes,
        is_fine_tune
    from {{ ref('hf_models') }}

),

-- A model's fan-out = how many *other* models declared THIS one as their
-- base_model. We join hf_model_tree.base_model = hf.model_id.
fan_out as (

    select
        base_model        as model_id,
        fine_tune_count   as fine_tune_fan_out
    from {{ ref('hf_model_tree') }}

)

select
    hf.model_id,
    hf.author,
    hf.base_model,
    hf.pipeline_tag,
    hf.library_name,
    hf.downloads,
    hf.likes,
    coalesce(f.fine_tune_fan_out, 0)                                  as fine_tune_fan_out,
    hf.is_fine_tune,

    -- preliminary composite score (placeholder weights — see banner above)
    0.4 * ln(coalesce(hf.downloads, 0) + 1)
  + 0.3 * ln(coalesce(hf.likes, 0) + 1)
  + 0.3 * ln(coalesce(f.fine_tune_fan_out, 0) + 1)                    as composite_success_score

from hf
left join fan_out f on f.model_id = hf.model_id
