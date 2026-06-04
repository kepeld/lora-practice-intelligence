-- One row per repo, anchored on the enrichment table.
--
-- The targeted LoRA collector writes discovered repos straight into
-- github_repos_enriched and never into github_repos_bronze (only the retired
-- GH Archive stream populated bronze). Anchoring on bronze therefore dropped
-- the majority of the LoRA corpus from silver.repos. We anchor on
-- github_repos_enriched so every enriched LoRA repo is represented, and LEFT
-- JOIN the bronze aggregates for the event-activity proxies (star/fork/event
-- counts) that only the GH Archive stream produced -- NULL for repos found
-- purely via targeted Search.
select
    e.repo_id,
    e.repo_name,
    b.star_count,
    b.fork_count,
    b.event_count,
    to_timestamp(b.first_seen_at)     as first_seen_at,
    to_timestamp(b.last_seen_at)      as last_seen_at,
    e.description,
    e.primary_language,
    e.topics,
    e.license,
    e.open_issues_count,
    e.readme_length,
    to_timestamp(e.repo_created_at)   as repo_created_at,
    to_timestamp(e.pushed_at)         as pushed_at,
    e.repo_size_kb,
    e.has_tests,
    e.has_ci,
    e.contributors_count,
    e.commit_count_30d,
    e.is_fork,
    e.is_archived,
    e.forks_count,
    e.subscribers_count,
    e.homepage,
    to_timestamp(e.enriched_at)       as enriched_at,
    e.enrichment_status
from {{ source('bronze', 'github_repos_enriched') }} e
left join {{ source('bronze', 'github_repos_bronze') }} b
    on e.repo_id = b.repo_id
