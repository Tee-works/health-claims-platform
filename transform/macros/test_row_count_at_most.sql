{% test row_count_at_most(model, max_rows) %}
select count(*) as row_count
from {{ model }}
having count(*) > {{ max_rows }}
{% endtest %}
