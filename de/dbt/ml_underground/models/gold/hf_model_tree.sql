-- base_model -> fine-tunes summary. fine_tune_count feeds the
-- fine_tune_fan_out factor in composite_success_score (US-4.1).
select
    base_model,
    count(*)                as fine_tune_count,
    sum(downloads)          as total_downloads,
    sum(likes)              as total_likes,
    array_agg(model_id)     as fine_tune_models
from {{ ref('hf_models') }}
where base_model is not null
  -- a model declaring itself as its own base is metadata noise, not a
  -- fine-tune; counting it inflates fan_out by +1 (#64)
  and model_id != base_model
group by base_model
