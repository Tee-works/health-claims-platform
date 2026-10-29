{#- A stable, salted key for a member. The same member always gets the same key,
    so analysts can count and join, but the key cannot be reversed to an ID
    without the salt, which only the transform role can read. -#}
{% macro member_key(column) -%}
    sha256(concat('{{ var("pii_salt") }}', '|', {{ column }}))
{%- endmacro %}
