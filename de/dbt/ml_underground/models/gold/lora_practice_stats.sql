-- LoRA practice stats: which hyperparameter values are common vs rare, and which
-- correlate with better outcomes (US-4.2, Issue #10).
--
-- Variant D: built from the HF-side params (`hf_models_lora_params`) joined to
-- `repo_lora_outcomes` on `model_id` — both keyed on the same HF model, so no
-- GitHub<->HF linkage is required.
--
-- Rigour beyond a raw median split:
--   * base_model stratification (Risk 3) — the works/fails axis uses
--     score_vs_base = a model's composite_success_score minus the mean score of
--     its base_model peers (global mean when base_model is unknown). This credits
--     a value for beating peers on the SAME base model, not for riding a popular
--     base model.
--   * effect size — score_lift = a bucket's mean score minus the parameter's
--     pooled mean, so you can see how much a value moves the needle.
--   * min-sample gate — sample_ok flags buckets backed by >= MIN_SAMPLE models;
--     a "rare+works" cell with one model is noise, not a hidden gem.
--
-- Quadrants split on per-parameter medians: common/rare on prevalence,
-- works/fails on the base-stratified score.
{{ config(materialized='table') }}

{% set min_sample = 3 %}

with params as (

    select * from {{ ref('hf_models_lora_params') }}

),

outcomes as (

    select model_id, base_model, composite_success_score
    from {{ ref('repo_lora_outcomes') }}

),

global_mean as (

    select avg(composite_success_score) as g from outcomes

),

base_means as (

    select base_model, avg(composite_success_score) as base_avg
    from outcomes
    where base_model is not null
    group by base_model

),

-- Per-model score plus its outperformance vs same-base peers.
model_scores as (

    select
        o.model_id,
        o.composite_success_score,
        o.composite_success_score - coalesce(b.base_avg, gm.g) as score_vs_base
    from outcomes o
    cross join global_mean gm
    left join base_means b on b.base_model = o.base_model

),

-- Long-form: one row per (model, parameter, value).
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

joined as (

    -- inner join: a model with params but no outcome row (e.g. extract_hf_cards
    -- ran before hf_ingestion) has a NULL score that compares false in every
    -- quadrant CASE arm and would silently land in 'rare+fails'. Excluding such
    -- models keeps them out of the stats rather than misclassifying them.
    select
        lf.param_name,
        lf.param_value,
        lf.model_id,
        ms.composite_success_score,
        ms.score_vs_base
    from long_form lf
    join model_scores ms on ms.model_id = lf.model_id

),

bucketed as (

    select
        param_name,
        param_value,
        count(distinct model_id)        as prevalence,
        avg(composite_success_score)    as avg_score,
        avg(score_vs_base)              as avg_score_vs_base
    from joined
    group by param_name, param_value

),

param_pooled as (

    select param_name, avg(composite_success_score) as param_avg_score
    from joined
    group by param_name

),

per_param_medians as (

    select
        param_name,
        median(prevalence)        as prevalence_median,
        median(avg_score_vs_base) as vsbase_median
    from bucketed
    group by param_name

)

select
    b.param_name,
    b.param_value,
    b.prevalence,
    round(b.avg_score, 3)                       as avg_success_score,
    round(b.avg_score_vs_base, 3)               as avg_score_vs_base,
    round(b.avg_score - p.param_avg_score, 3)   as score_lift,
    b.prevalence >= {{ min_sample }}            as sample_ok,
    -- common = prevalence at/above the param median; works = base-stratified
    -- score at/above the param median.
    case
        when b.prevalence >= m.prevalence_median and b.avg_score_vs_base >= m.vsbase_median
            then 'common+works'
        when b.prevalence >= m.prevalence_median and b.avg_score_vs_base <  m.vsbase_median
            then 'common+fails'
        when b.prevalence <  m.prevalence_median and b.avg_score_vs_base >= m.vsbase_median
            then 'rare+works'
        else
            'rare+fails'
    end as quadrant
from bucketed b
join per_param_medians m using (param_name)
join param_pooled p using (param_name)
order by param_name, prevalence desc
