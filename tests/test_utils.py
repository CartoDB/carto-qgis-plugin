import uuid

import pytest
from qgis.core import NULL

from carto.core import utils
from carto.core.utils import (
    prepare_attribute_string,
    prepare_geo_value_for_provider,
    prepare_multipart_sql,
    prepare_num_string,
    quote_column_name_for_provider,
    quote_for_provider,
)

STATEMENTS = ["UPDATE t SET a = 1 WHERE id = 1;", "DELETE FROM t WHERE id = 2;"]
JOINED = "\n".join(STATEMENTS)
FIXED_UUID = uuid.UUID("12345678123456781234567812345678")


@pytest.fixture
def fixed_uuid(monkeypatch):
    monkeypatch.setattr(utils.uuid, "uuid4", lambda: FIXED_UUID)


def _normalized(sql):
    return [line.strip() for line in sql.strip().splitlines() if line.strip()]


class TestPrepareMultipartSqlDefault:
    def test_bigquery_uses_plain_script_block(self):
        assert prepare_multipart_sql(STATEMENTS, "bigquery", "p.d.t") == [f"""
            BEGIN
                {JOINED}
            END;
            """]

    def test_snowflake_uses_plain_script_block(self):
        assert prepare_multipart_sql(STATEMENTS, "snowflake", "d.s.t") == [f"""
            BEGIN
                {JOINED}
            END;
            """]

    def test_postgres_uses_do_block(self):
        assert prepare_multipart_sql(STATEMENTS, "postgres", "d.s.t") == [
            f"""
            DO $$
            BEGIN
                {JOINED}
            END;
            $$;
            """,
        ]

    def test_redshift_creates_calls_and_drops_procedure(self, fixed_uuid):
        proc = f"d.s.carto_{FIXED_UUID.hex}"
        assert prepare_multipart_sql(STATEMENTS, "redshift", "d.s.t") == [
            f"""
            CREATE OR REPLACE PROCEDURE {proc}()
                AS $$
                BEGIN
                {JOINED}
                END;
                $$ LANGUAGE plpgsql;
            """,
            f"CALL {proc}();",
            f"DROP PROCEDURE {proc}();",
        ]

    def test_databricks_sends_statements_unwrapped(self):
        assert prepare_multipart_sql(STATEMENTS, "databricksRest", "c.s.t") == [JOINED]


class TestPrepareMultipartSqlTransaction:
    def test_bigquery_wraps_in_transaction(self):
        (sql,) = prepare_multipart_sql(
            STATEMENTS, "bigquery", "p.d.t", transaction=True
        )

        assert _normalized(sql) == [
            "BEGIN TRANSACTION;",
            *STATEMENTS,
            "COMMIT TRANSACTION;",
        ]

    def test_snowflake_wraps_in_transaction_with_rollback(self):
        (sql,) = prepare_multipart_sql(
            STATEMENTS, "snowflake", "d.s.t", transaction=True
        )

        assert _normalized(sql) == [
            "BEGIN",
            "BEGIN TRANSACTION;",
            *STATEMENTS,
            "COMMIT;",
            "EXCEPTION",
            "WHEN OTHER THEN",
            "ROLLBACK;",
            "RAISE;",
            "END;",
        ]

    @pytest.mark.parametrize("provider", ["postgres", "redshift", "databricksRest"])
    def test_other_providers_are_unchanged(self, provider, fixed_uuid):
        assert prepare_multipart_sql(
            STATEMENTS, provider, "d.s.t", transaction=True
        ) == prepare_multipart_sql(STATEMENTS, provider, "d.s.t")


class TestPrepareGeoValueForProvider:
    @pytest.mark.parametrize(
        "provider, template",
        [
            ("bigquery", "ST_GEOGFROMWKB('{}')"),
            ("snowflake", "'{}'"),
            ("redshift", "ST_GEOMFROMWKB('{}')"),
            ("postgres", "ST_GEOMFROMWKB(DECODE('{}', 'hex'))"),
        ],
    )
    def test_wkb_providers(self, provider, template, fake_geom):
        geom = fake_geom(4)
        wkb = geom.asWkb().toHex().data().decode()

        assert prepare_geo_value_for_provider(provider, geom) == template.format(wkb)

    def test_databricks_uses_wkt(self, fake_geom):
        geom = fake_geom(4)

        assert (
            prepare_geo_value_for_provider("databricksRest", geom)
            == f"'{geom.asWkt()}'"
        )

    def test_large_geometry_produces_long_literal(self, fake_geom):
        value = prepare_geo_value_for_provider("bigquery", fake_geom(300))

        assert len(value) > 8_200


class TestPrepareAttributeString:
    @pytest.mark.parametrize(
        "value, numeric, expected",
        [
            (NULL, True, "NULL"),
            (NULL, False, "NULL"),
            (None, False, "NULL"),
            (5, True, "5"),
            (5.0, True, "5"),
            (5.5, True, "5.5"),
            ("abc", False, "'abc'"),
            (7, False, "'7'"),
        ],
    )
    def test_values(self, value, numeric, expected):
        assert prepare_attribute_string(value, numeric) == expected


class TestPrepareNumString:
    @pytest.mark.parametrize(
        "value, expected", [(3, "3"), (3.0, "3"), (-2.0, "-2"), (3.25, "3.25")]
    )
    def test_values(self, value, expected):
        assert prepare_num_string(value) == expected


class TestQuoting:
    @pytest.mark.parametrize(
        "provider, expected",
        [
            ("bigquery", "`p.d.t`"),
            ("databricksRest", "`p`.`d`.`t`"),
            ("postgres", '"p".d.t'),
            ("redshift", '"p".d.t'),
            ("snowflake", "p.d.t"),
        ],
    )
    def test_quote_for_provider(self, provider, expected):
        assert quote_for_provider("p.d.t", provider) == expected

    @pytest.mark.parametrize("provider", ["postgres", "redshift"])
    def test_quote_for_provider_strips_existing_database_quotes(self, provider):
        assert quote_for_provider('"p".d.t', provider) == '"p".d.t'

    def test_quote_for_provider_leaves_non_fqn_postgres_names(self):
        assert quote_for_provider("d.t", "postgres") == "d.t"

    @pytest.mark.parametrize(
        "provider, expected",
        [
            ("bigquery", "`name`"),
            ("databricksRest", "`name`"),
            ("postgres", '"name"'),
            ("redshift", '"name"'),
            ("snowflake", '"name"'),
        ],
    )
    def test_quote_column_name_for_provider(self, provider, expected):
        assert quote_column_name_for_provider("name", provider) == expected
