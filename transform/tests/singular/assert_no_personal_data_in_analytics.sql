-- Analysts can read the analytics schema, so no column there may hold
-- personal data. Fails the build if someone adds one.
select
    table_name,
    column_name
from information_schema.columns
where
    table_schema = 'analytics'
    and regexp_matches(
        lower(column_name),
        '^(member_id|first_name|last_name|full_name|phone|email|date_of_birth|dob|address)$'
    )
