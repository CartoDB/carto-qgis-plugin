from unittest.mock import MagicMock

import pytest
from conftest import FakeFeature, FakeField, FakeFields, FakeGeometry, FakeLayer
from qgis.PyQt.QtCore import QMetaType

from carto.core import importlayertask


def _layer(n_features):
    fields = FakeFields(
        [
            FakeField("id", True, QMetaType.Type.Int),
            FakeField("name", False, QMetaType.Type.QString),
            FakeField("flag", False, QMetaType.Type.Bool),
        ]
    )
    features = {
        i: FakeFeature(
            fields, {"id": i, "name": f"n{i}", "flag": i % 2 == 0}, FakeGeometry(4)
        )
        for i in range(n_features)
    }
    return FakeLayer(fields, features)


@pytest.fixture
def api(monkeypatch):
    api = MagicMock(name="CARTO_API")
    monkeypatch.setattr(importlayertask, "CARTO_API", api)
    return api


def _run(provider, n_features):
    task = importlayertask.ImportLayerTask(
        "conn", provider, "proj.dataset.table", _layer(n_features)
    )
    assert task.run() is True, task.exception
    return task


def _sent(mock):
    return [c.args[1] for c in mock.call_args_list]


def test_bigquery_import_creates_table_then_inserts_in_batches_of_ten(api):
    _run("bigquery", 23)

    (ddl,) = _sent(api.execute_query)
    assert "DROP TABLE IF EXISTS `proj.dataset.table`;" in ddl
    assert "CREATE TABLE `proj.dataset.table` (" in ddl
    assert "id INT64" in ddl and "name STRING" in ddl and "flag BOOL" in ddl
    assert "geom GEOGRAPHY" in ddl

    batches = _sent(api.execute_query_post)
    assert [b.count("INSERT INTO") for b in batches] == [10, 10, 3]
    assert "VALUES (0, 'n0', TRUE, ST_GEOGFROMWKB(" in batches[0]


@pytest.mark.parametrize("provider", ["bigquery", "snowflake", "postgres"])
def test_import_never_uses_transaction_wrapping(api, provider):
    _run(provider, 12)

    for sql in _sent(api.execute_query) + _sent(api.execute_query_post):
        assert "BEGIN TRANSACTION" not in sql
        assert "COMMIT" not in sql


def test_cancel_stops_before_inserts(api):
    task = importlayertask.ImportLayerTask(
        "conn", "bigquery", "proj.dataset.table", _layer(5)
    )
    task.isCanceled = lambda: True

    assert task.run() is False
    api.execute_query_post.assert_not_called()


def test_api_error_is_captured(api):
    api.execute_query.side_effect = RuntimeError("boom")
    task = importlayertask.ImportLayerTask(
        "conn", "bigquery", "proj.dataset.table", _layer(1)
    )

    assert task.run() is False
    assert "boom" in task.exception
