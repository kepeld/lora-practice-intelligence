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
    json_array_length(try_cast(tags as json)) as tag_count,
    base_model is not null as is_fine_tune,
    coalesce(is_lora_relevant, 0) = 1 as is_lora_relevant,
    collection_source,
    created_at,
    last_modified
from {{ ref('stg_hf_models') }}
