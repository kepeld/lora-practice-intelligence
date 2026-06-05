{#
    Use the model's configured +schema as the schema name verbatim
    (BRONZE / STAGING / SILVER / GOLD) instead of dbt's default
    <target_schema>_<custom_schema>. Models without a +schema fall back
    to the target schema from profiles.yml.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim | upper }}
    {%- endif -%}
{%- endmacro %}
