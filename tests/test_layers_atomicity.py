import pytest
import requests
from qgis.core import NULL, Qgis

FIELDS = [("id", True), ("name", False)]


def _normalized(sql):
    return [line.strip() for line in sql.strip().splitlines() if line.strip()]


def _support_repro(env, fake_layer, fake_geom):
    """Rename feature 1, replace feature 2's geometry, delete feature 3."""
    layer = fake_layer(
        FIELDS,
        {
            1: {"id": 1, "name": "renamed"},
            2: {"id": 2, "name": "two"},
        },
    )
    changes = env.start(layer)
    changes.attributes_changed = {1: {1: "renamed"}}
    changes.geoms_changed = {2: fake_geom(5)}
    changes.features_removed = [{"id": 3, "name": "three"}]
    return layer, changes


class TestStatementGeneration:
    def test_bigquery_save_is_one_transaction_in_edit_order(
        self, upload_env, fake_layer, fake_geom
    ):
        env = upload_env("bigquery")
        layer, changes = _support_repro(env, fake_layer, fake_geom)

        env.upload(layer)

        (query,) = env.sent_queries()
        wkb = changes.geoms_changed[2].asWkb().toHex().data().decode()
        assert _normalized(query) == [
            "BEGIN TRANSACTION;",
            "UPDATE `proj.dataset.table` SET name = 'renamed' WHERE id = 1;",
            f"UPDATE `proj.dataset.table` SET geom = ST_GEOGFROMWKB('{wkb}') WHERE id = 2;",
            "DELETE FROM `proj.dataset.table` WHERE id = 3;",
            "COMMIT TRANSACTION;",
        ]

    def test_snowflake_save_is_one_transaction_with_rollback(
        self, upload_env, fake_layer, fake_geom
    ):
        env = upload_env("snowflake")
        layer, _ = _support_repro(env, fake_layer, fake_geom)

        env.upload(layer)

        (query,) = env.sent_queries()
        lines = _normalized(query)
        assert lines[:2] == ["BEGIN", "BEGIN TRANSACTION;"]
        assert lines[-6:] == [
            "COMMIT;",
            "EXCEPTION",
            "WHEN OTHER THEN",
            "ROLLBACK;",
            "RAISE;",
            "END;",
        ]
        assert len(lines) == 2 + 3 + 6

    def test_postgres_save_is_one_do_block(self, upload_env, fake_layer, fake_geom):
        env = upload_env("postgres")
        layer, _ = _support_repro(env, fake_layer, fake_geom)

        env.upload(layer)

        (query,) = env.sent_queries()
        lines = _normalized(query)
        assert lines[:2] == ["DO $$", "BEGIN"]
        assert lines[-2:] == ["END;", "$$;"]

    def test_inserted_feature_includes_geometry_and_original_columns(
        self, upload_env, fake_layer, fake_geom
    ):
        env = upload_env("bigquery")
        layer = fake_layer(FIELDS + [("local_only", False)], {})
        added = fake_layer(
            FIELDS + [("local_only", False)],
            {9: {"id": 9, "name": "new", "local_only": "x"}},
            geometries={9: fake_geom(4)},
        ).getFeature(9)
        env.start(layer).features_added = [added]

        env.upload(layer)

        (query,) = env.sent_queries()
        wkb = added.geometry().asWkb().toHex().data().decode()
        assert (
            "INSERT INTO `proj.dataset.table` (geom,`id`,`name`) "
            f"VALUES (ST_GEOGFROMWKB('{wkb}'),9,'new');"
        ) in _normalized(query)

    def test_string_pk_is_quoted(self, upload_env, fake_layer):
        env = upload_env("bigquery")
        env.metadata["pk"] = "code"
        layer = fake_layer([("code", False), ("name", False)], {1: {"code": "A1"}})
        env.start(layer).attributes_changed = {1: {1: "x"}}

        env.upload(layer)

        assert (
            "UPDATE `proj.dataset.table` SET name = 'x' WHERE code = 'A1';"
            in _normalized(env.sent_queries()[0])
        )

    def test_null_pk_uses_is_null(self, upload_env, fake_layer):
        env = upload_env("bigquery")
        layer = fake_layer(FIELDS, {})
        env.start(layer).features_removed = [{"id": NULL, "name": "orphan"}]

        env.upload(layer)

        assert "DELETE FROM `proj.dataset.table` WHERE id IS NULL;" in _normalized(
            env.sent_queries()[0]
        )


class TestEarlyReturns:
    def _assert_nothing_sent(self, env, expected_message):
        env.api.execute_query_post.assert_not_called()
        env.api.execute_query.assert_not_called()
        assert env.messages() == [(expected_message, Qgis.MessageLevel.Warning)]

    def test_no_write_permission(self, upload_env, fake_layer, fake_geom):
        env = upload_env("bigquery")
        env.metadata["can_write"] = False
        layer, _ = _support_repro(env, fake_layer, fake_geom)

        env.upload(layer)

        self._assert_nothing_sent(
            env,
            "No permission to write. Local changes will not be saved to the original table",
        )

    def test_schema_changed_in_session(self, upload_env, fake_layer, fake_geom):
        env = upload_env("bigquery")
        layer, changes = _support_repro(env, fake_layer, fake_geom)
        changes.schema_has_changed = True

        env.upload(layer)

        self._assert_nothing_sent(
            env, "Table schema has changed: changes will not be uploaded upstream"
        )

    def test_missing_pk_and_dialog_skipped(
        self, upload_env, fake_layer, fake_geom, monkeypatch
    ):
        env = upload_env("bigquery")
        env.metadata["pk"] = None
        layer, _ = _support_repro(env, fake_layer, fake_geom)

        class SkippedDialog:
            pk = None

            def __init__(self, columns):
                pass

            def exec(self):
                pass

        monkeypatch.setattr(env.layers, "SelectPrimaryKeyDialog", SkippedDialog)

        env.upload(layer)

        self._assert_nothing_sent(
            env, "Layer has no Primary Key: changes will not be uploaded upstream"
        )


class TestUploadOutcome:
    def test_success_reports_once(self, upload_env, fake_layer, fake_geom):
        env = upload_env("bigquery")
        layer, _ = _support_repro(env, fake_layer, fake_geom)

        env.upload(layer)

        assert env.messages() == [("Layer changes uploaded", Qgis.MessageLevel.Success)]
        assert env.errors == []

    @pytest.mark.parametrize(
        "provider", ["bigquery", "snowflake", "postgres", "redshift"]
    )
    def test_failure_on_atomic_provider_says_nothing_was_applied(
        self, provider, upload_env, fake_layer, fake_geom
    ):
        env = upload_env(provider)
        layer, _ = _support_repro(env, fake_layer, fake_geom)
        env.fail_upload(
            requests.HTTPError("400 Client Error: Bad Request (invalid polygon)")
        )

        env.upload(layer)

        ((message, level),) = env.messages()
        assert level == Qgis.MessageLevel.Critical
        assert "no edit was applied to the upstream table" in message
        assert "out of sync" in message
        assert "invalid polygon" in message
        assert env.errors == [
            "Error uploading changes: 400 Client Error: Bad Request (invalid polygon)"
        ]

    def test_failure_on_databricks_warns_of_partial_apply(
        self, upload_env, fake_layer, fake_geom
    ):
        env = upload_env("databricksRest")
        layer, _ = _support_repro(env, fake_layer, fake_geom)
        env.fail_upload(requests.HTTPError("400 Client Error"))

        env.upload(layer)

        ((message, level),) = env.messages()
        assert level == Qgis.MessageLevel.Critical
        assert "some edits may have been applied" in message
        assert "no edit was applied" not in message
