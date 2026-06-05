-- Repos that have training/config files in github_files but yielded no
-- structured parameters in repo_lora_params.
--
-- This is the **target list** for Issue #7 (US-3.3 LLM extraction fallback).
-- For every row here, the LLM pass reads `content` from the files we already
-- have and tries to recover rank/alpha/optimizer/etc. that the AST/YAML/regex
-- layers missed.
{{ config(materialized='view') }}

with files_per_repo as (

    select
        repo_full_name,
        count(*)                                     as file_count,
        count_if(file_category = 'training_script')  as training_scripts,
        count_if(file_category = 'config')           as config_files,
        count_if(file_category = 'adapter_config')   as adapter_configs,
        sum(file_size)                               as total_bytes,
        max(fetched_at)                              as files_last_fetched
    from {{ source('bronze', 'github_files') }}
    group by repo_full_name

),

extracted as (

    select repo_full_name from {{ source('bronze', 'repo_lora_params') }}

)

select
    f.repo_full_name,
    f.file_count,
    f.training_scripts,
    f.config_files,
    f.adapter_configs,
    f.total_bytes,
    f.files_last_fetched,
    r.primary_language,
    r.star_count,
    r.contributors_count
from files_per_repo  f
left join {{ ref('repos') }}  r  on r.repo_name = f.repo_full_name
where f.repo_full_name not in (select repo_full_name from extracted)
order by f.training_scripts desc, f.file_count desc
