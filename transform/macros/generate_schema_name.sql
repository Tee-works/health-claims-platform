{#- Use the folder's schema name as-is (staging, analytics, ...) instead of
    prefixing it with the target schema, so access policies can name schemas. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}
