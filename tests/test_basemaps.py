from carto.core.utils import basemap_style_url, basemap_tile_source

STYLE_URL = "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json"
TILES = "https://tiles.basemaps.cartocdn.com/v/1/vectortiles/carto.streets/v2/{z}/{x}/{y}.mvt"


def test_style_url_without_key():
    assert basemap_style_url(STYLE_URL, None) == STYLE_URL
    assert basemap_style_url(STYLE_URL, "") == STYLE_URL


def test_style_url_with_key():
    assert basemap_style_url(STYLE_URL, "a b") == f"{STYLE_URL}?key=a+b"


def test_tile_source_from_vector_source():
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
    assert basemap_tile_source(style) == (TILES, 0, 15)


def test_tile_source_missing():
    assert (
        basemap_tile_source({"sources": {"v": {"type": "vector", "url": "x"}}}) is None
    )
    assert basemap_tile_source({}) is None
