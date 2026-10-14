from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from carto.core import connection


def _table(provider_type, tableid="QA_TABLE"):
    conn = SimpleNamespace(provider_type=provider_type, name="conn")
    database = SimpleNamespace(databaseid="DB", connection=conn)
    schema = SimpleNamespace(schemaid="SCH", database=database)
    return connection.Table(tableid, tableid, 0, schema)


@pytest.fixture
def api(monkeypatch):
    api = MagicMock(name="CARTO_API")
    monkeypatch.setattr(connection, "CARTO_API", api)
    return api


class TestSnowflakePk:
    def test_reads_pk_column_from_show_primary_keys(self, api):
        api.execute_query.return_value = {
            "rows": [
                {
                    "constraint_name": "SYS_CONSTRAINT_8e7cf6a5",
                    "column_name": "ID",
                    "key_sequence": 1,
                }
            ]
        }
        assert _table("snowflake").pk() == "ID"
        sql = api.execute_query.call_args.args[1]
        assert 'SHOW PRIMARY KEYS IN TABLE "DB"."SCH"."QA_TABLE"' in sql

    def test_reads_uppercase_column_name_key(self, api):
        api.execute_query.return_value = {"rows": [{"COLUMN_NAME": "ID"}]}
        assert _table("snowflake").pk() == "ID"

    def test_escapes_double_quotes_in_identifiers(self, api):
        api.execute_query.return_value = {"rows": []}
        _table("snowflake", tableid='we"ird').pk()
        sql = api.execute_query.call_args.args[1]
        assert '"we""ird"' in sql

    def test_no_primary_key_returns_none(self, api):
        api.execute_query.return_value = {"rows": []}
        assert _table("snowflake").pk() is None


class TestBigQueryPk:
    def test_reads_pk_column(self, api):
        api.execute_query.return_value = {"rows": [{"column_name": "id"}]}
        assert _table("bigquery").pk() == "id"
