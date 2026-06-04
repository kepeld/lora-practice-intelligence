-- Conformed HuggingFace model entity with parsed tags.
select
    model_id,
    author,
    base_model,
    pipeline_tag,
    library_name,
    downloads,
    likes,
    tags,
    array_size(try_parse_json(tags)) as tag_count,
    base_model is not null as is_fine_tune,
    created_at,
    last_modified
from {{ ref('stg_hf_models') }}
