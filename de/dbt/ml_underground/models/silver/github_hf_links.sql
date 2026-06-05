-- Conformed GitHub <-> HuggingFace links: one row per (repo, model) pair,
-- collapsing the per-strategy rows from the bronze github_hf_links table.
-- best_confidence is the strongest signal found; link_types lists every
-- strategy that matched the pair.
{{ config(materialized='table') }}

with raw_links as (

    select * from {{ source('bronze', 'github_hf_links') }}

),

dedup as (

    select
        repo_full_name,
        model_id,
        max(confidence)                                              as best_confidence,
        listagg(distinct link_type, ',')
            within group (order by link_type)                        as link_types,
        max(created_at)                                              as last_linked_at
    from raw_links
    group by repo_full_name, model_id

)

select
    d.repo_full_name,
    d.model_id,
    d.best_confidence,
    d.link_types,
    d.last_linked_at,

    -- Convenience flags for downstream filters (US-4.2 Variant A):
    -- * is_high_confidence  ≥0.7  — only direct hits + strong same_username
    -- * is_signal_confidence≥0.5  — relaxed; includes fuzzy_name (use this
    --                                if you want broader recall + many-to-many)
    d.best_confidence >= 0.7  as is_high_confidence,
    d.best_confidence >= 0.5  as is_signal_confidence,

    r.primary_language,
    h.base_model,
    h.downloads,
    h.likes
from dedup d
left join {{ ref('repos') }}     r on d.repo_full_name = r.repo_name
left join {{ ref('hf_models') }} h on d.model_id       = h.model_id
