-- Cleaned projection of the HuggingFace models bronze table.
select
    model_id,
    author,
    base_model,
    pipeline_tag,
    library_name,
    downloads,
    likes,
    tags,
    to_timestamp(created_at)     as created_at,
    to_timestamp(last_modified)  as last_modified,
    to_timestamp(ingested_at)    as ingested_at
from {{ source('bronze', 'huggingface_models_bronze') }}
