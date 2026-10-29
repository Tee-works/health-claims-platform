"""The no-personal-data test must actually fail the build when PII appears.

Kept in its own module: it needs write access to the warehouse, so no other
test may hold a connection open while it runs.
"""

import duckdb

from tests.conftest import dbt


def test_build_fails_if_someone_adds_personal_data_to_analytics(platform):
    path = str(platform["paths"].warehouse)
    with duckdb.connect(path) as c:
        c.execute("create table analytics.leaky_export as select 'RH-000001' as member_id")
    try:
        result = dbt("test", "--select", "assert_no_personal_data_in_analytics")
        assert result.returncode != 0
        assert "leaky_export" in result.stdout or "FAIL" in result.stdout
    finally:
        with duckdb.connect(path) as c:
            c.execute("drop table analytics.leaky_export")
