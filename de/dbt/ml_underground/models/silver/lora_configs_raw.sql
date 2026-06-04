-- Silver passthrough of bronze.lora_configs_raw — one row per
-- (repo, file, source, param). The gold.repo_lora_params model collapses
-- this to one row per repo via the priority merge.
{{ config(materialized='table') }}

select
    config_id,
    repo_full_name,
    file_id,
    source,
    param_name,
    param_value,
    confidence,
    extracted_at
from {{ source('bronze', 'lora_configs_raw') }}
