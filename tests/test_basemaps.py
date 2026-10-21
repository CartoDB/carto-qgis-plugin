from carto.core.utils import (
    basemap_style_url,
    basemap_tile_source,
    basemap_vector_source,
)

STYLE_URL = "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json"
TILES = "https://tiles.basemaps.cartocdn.com/v/1/vectortiles/carto.streets/v2/{z}/{x}/{y}.mvt"


def test_style_url_without_key():
    assert basemap_style_url(STYLE_URL, None) == STYLE_URL
    assert basemap_style_url(STYLE_URL, "") == STYLE_URL


def test_style_url_with_key():
    assert basemap_style_url(STYLE_URL, "a b") == f"{STYLE_URL}?key=a+b"


def test_inline_tiles_source():
    style = {
        "sources": {
            "raster": {
                "type": "raster",
                "tiles": ["https://example.com/{z}/{x}/{y}.png"],
            },
            "protomaps": {
                "type": "vector",
                "tiles": [TILES],
                "minzoom": 0,
                "maxzoom": 15,
            },
        }
    }
    source = basemap_vector_source(style)
    assert source is style["sources"]["protomaps"]
    assert basemap_tile_source(source) == (TILES, 0, 15)


def test_tilejson_source():
    source = {"type": "vector", "url": "https://example.com/tiles.json"}
    style = {"sources": {"carto": source}}
    assert basemap_vector_source(style) is source
    tilejson = {"tiles": [TILES], "minzoom": 0, "maxzoom": 14}
    assert basemap_tile_source(source, tilejson) == (TILES, 0, 14)
    assert basemap_tile_source({**source, "maxzoom": 12}, tilejson) == (TILES, 0, 12)


def test_no_vector_source():
    assert basemap_vector_source({"sources": {"v": {"type": "vector"}}}) is None
    assert basemap_vector_source({}) is None
    assert basemap_tile_source({"type": "vector", "url": "x"}, None) is None
