-- Composite success score per LoRA model (US-4.1, Issue #6).
--
-- Each outcome signal (downloads, likes, fine-tune fan-out) is mapped to its
-- population percentile rank in [0,1] (PERCENT_RANK), then blended with fixed
-- weights. Percentile normalisation fixes the previous placeholder's
-- scale-mixing problem: raw ln(downloads) spanned ~0–16 while ln(likes) and
-- ln(fan_out) spanned far less, so downloads dominated regardless of its
-- weight. Now every signal contributes on the same [0,1] scale and the weights
-- mean what they say.
--
-- Weights (tunable): fine-tune fan-out is the hardest signal to game — other
-- people chose to build on the model — so it carries the most weight.
--   fine_tune_fan_out 0.5 | downloads 0.3 | likes 0.2
--
-- Caveat (Risk 3, selection bias): only models published to HF are scored, and
-- popularity is influenced by author reach, not just technique. Treat the score
-- as a correlational popularity signal, not a causal measure of a recipe's
-- quality. Stratified, significance-aware comparison is handled in #10.
--
-- Grain: one row per HuggingFace model.
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

),

joined as (

    select
        hf.*,
        coalesce(f.fine_tune_fan_out, 0) as fine_tune_fan_out
    from hf
    left join fan_out f on f.model_id = hf.model_id

),

ranked as (

    select
        *,
        percent_rank() over (order by downloads)         as downloads_pct,
        percent_rank() over (order by likes)             as likes_pct,
        percent_rank() over (order by fine_tune_fan_out) as fan_out_pct
    from joined

)

select
    model_id,
    author,
    base_model,
    pipeline_tag,
    library_name,
    downloads,
    likes,
    fine_tune_fan_out,
    is_fine_tune,

    -- per-signal percentiles, exposed for transparency / the dashboard
    round(downloads_pct, 4) as downloads_pct,
    round(likes_pct, 4)     as likes_pct,
    round(fan_out_pct, 4)   as fan_out_pct,

    -- weighted blend of the percentile-normalised signals, in [0,1]
    round(0.3 * downloads_pct + 0.2 * likes_pct + 0.5 * fan_out_pct, 4)
        as composite_success_score

from ranked
