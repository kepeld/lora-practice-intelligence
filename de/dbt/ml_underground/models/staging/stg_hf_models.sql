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
    is_lora_relevant,
    collection_source,
    created_at::timestamp     as created_at,
    last_modified::timestamp  as last_modified,
    ingested_at::timestamp    as ingested_at
from {{ source('bronze', 'huggingface_models_bronze') }}
