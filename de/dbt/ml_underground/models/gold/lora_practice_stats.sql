-- LoRA practice stats: prevalence and outcome-correlated success per
-- hyperparameter value (US-4.2, Issue #10).
--
-- Variant D: built from the HF-side params + outcomes JOIN, NOT from
-- GitHub↔HF linkage. We extract LoRA params directly from HF model cards
-- (`hf_models_lora_params`) and join to `repo_lora_outcomes` on `model_id`
-- — both keyed on the same HF model, so no linkage is needed.
--
-- Output: one row per (parameter_name, parameter_value) bucket with
--   * prevalence    — how many models picked this value
--   * avg_score     — average composite_success_score
--   * quadrant      — common+works | common+fails | rare+works | rare+fails
--
-- Quadrants are computed against medians of prevalence and avg_score across
-- buckets within each parameter, so each parameter has its own thresholds.
--
-- composite_success_score is the percentile-weighted blend finalised in Issue
-- #6; this model recomputes against it automatically.
{{ config(materialized='table') }}

with params as (

    select * from {{ ref('hf_models_lora_params') }}

),

outcomes as (

    select model_id, composite_success_score
    from {{ ref('repo_lora_outcomes') }}

),

-- Long-form: one row per (model, parameter, value) so we can group cleanly.
long_form as (

    select model_id, 'rank_value' as param_name, rank_value::varchar as param_value
    from params where rank_value is not null
    union all
    select model_id, 'lora_alpha', lora_alpha::varchar
    from params where lora_alpha is not null
    union all
    select model_id, 'optimizer', optimizer
    from params where optimizer is not null
    union all
    select model_id, 'scheduler', scheduler
    from params where scheduler is not null
    union all
    select model_id, 'batch_size', batch_size::varchar
    from params where batch_size is not null
    union all
    select model_id, 'num_train_epochs', num_train_epochs::varchar
    from params where num_train_epochs is not null
    union all
    select model_id, 'gradient_accumulation_steps', gradient_accumulation_steps::varchar
    from params where gradient_accumulation_steps is not null
    union all
    select model_id, 'lora_dropout', lora_dropout::varchar
    from params where lora_dropout is not null
    union all
    select model_id, 'bf16', bf16::varchar
    from params where bf16 is not null

),

bucketed as (

    select
        lf.param_name,
        lf.param_value,
        count(distinct lf.model_id)             as prevalence,
        avg(o.composite_success_score)          as avg_score
    from long_form lf
    left join outcomes o on o.model_id = lf.model_id
    group by lf.param_name, lf.param_value

),

per_param_medians as (

    select
        param_name,
        median(prevalence) as prevalence_median,
        median(avg_score)  as score_median
    from bucketed
    group by param_name

)

select
    b.param_name,
    b.param_value,
    b.prevalence,
    round(b.avg_score, 3)                       as avg_success_score,
    -- common = prevalence at or above median; rare = below
    -- works  = avg_score at or above median;  fails = below
    case
        when b.prevalence >= m.prevalence_median and b.avg_score >= m.score_median
            then 'common+works'
        when b.prevalence >= m.prevalence_median and b.avg_score <  m.score_median
            then 'common+fails'
        when b.prevalence <  m.prevalence_median and b.avg_score >= m.score_median
            then 'rare+works'
        else
            'rare+fails'
    end as quadrant
from bucketed b
join per_param_medians m using (param_name)
order by param_name, prevalence desc
