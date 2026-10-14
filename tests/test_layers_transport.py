from qgis.core import Qgis

FIELDS = [("id", True), ("name", False)]


def _layer_with_moved_vertex(fake_layer, fake_geom, n_vertices):
    layer = fake_layer(FIELDS, {1: {"id": 1, "name": "parcel"}})
    return layer, {1: fake_geom(n_vertices)}


def test_large_geometry_edit_is_sent_in_request_body(upload_env, fake_layer, fake_geom):
    env = upload_env("bigquery")
    layer, geoms = _layer_with_moved_vertex(fake_layer, fake_geom, 300)
    env.start(layer).geoms_changed = geoms

    env.upload(layer)

    env.api.execute_query.assert_not_called()
    (query,) = env.sent_queries()
    wkb = geoms[1].asWkb().toHex().data().decode()
    assert f"ST_GEOGFROMWKB('{wkb}')" in query
    assert len(query) > 8_200
    assert env.api.execute_query_post.call_args.args[0] == "conn"
    assert env.messages() == [("Layer changes uploaded", Qgis.MessageLevel.Success)]


def test_redshift_sends_every_statement_in_order(upload_env, fake_layer, fake_geom):
    env = upload_env("redshift")
    layer, geoms = _layer_with_moved_vertex(fake_layer, fake_geom, 4)
    env.start(layer).geoms_changed = geoms

    env.upload(layer)

    env.api.execute_query.assert_not_called()
    create, call, drop = env.sent_queries()
    assert "CREATE OR REPLACE PROCEDURE" in create
    assert call.startswith("CALL ")
    assert drop.startswith("DROP PROCEDURE ")
    proc_name = call[len("CALL ") : -len("();")]
    assert proc_name in create
    assert drop == f"DROP PROCEDURE {proc_name}();"
