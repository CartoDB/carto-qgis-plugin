import json
import math
import os
import string

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsVectorLayer,
)

from carto.core.api import CARTO_API
from carto.core.layers import is_carto_layer
from carto.core.logging import info, error, debug
from carto.core.export.style_translator import translate_layer
from carto.core.export.token_manager import create_export_token

BASEMAP_STYLES = {
    "positron": "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    "dark_matter": "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    "voyager": "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
}

DEFAULT_BASEMAP = "positron"

TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "templates", "deckgl_map.html"
)


def extract_view_state(canvas):
    """Convert the QGIS map canvas extent to a deck.gl initialViewState dict."""
    extent = canvas.extent()
    transform = QgsCoordinateTransform(
        canvas.mapSettings().destinationCrs(),
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance(),
    )
    extent_4326 = transform.transformBoundingBox(extent)
    center = extent_4326.center()

    width = extent_4326.width()
    if width <= 0:
        width = 0.01
    zoom = math.log2(360.0 / width)
    zoom = max(0, min(zoom, 22))

    return {
        "longitude": round(center.x(), 6),
        "latitude": round(center.y(), 6),
        "zoom": round(zoom, 2),
        "pitch": 0,
        "bearing": 0,
    }


def generate_html(canvas, output_path, basemap=None, layers=None):
    """Generate a deck.gl HTML file from the current QGIS project.

    Args:
        canvas: QgsMapCanvas instance (iface.mapCanvas())
        output_path: File path to write the HTML to
        basemap: Basemap key ("positron", "dark_matter", "voyager") or None for default
        layers: Optional list of QgsVectorLayer to export. If None, auto-detects
                all CARTO layers in the project.

    Returns:
        True on success, False on failure.
    """
    project = QgsProject.instance()

    if layers is not None:
        carto_layers = layers
    else:
        # Auto-detect CARTO layers
        carto_layers = []
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not is_carto_layer(layer):
                continue
            if not layer.isValid():
                continue
            carto_layers.append(layer)

    if not carto_layers:
        error("No CARTO layers found in the project")
        return False

    info(f"Exporting {len(carto_layers)} CARTO layer(s) to deck.gl HTML")

    # Create scoped API access token
    access_token = create_export_token(carto_layers)
    if not access_token:
        error("Failed to create API access token for export")
        return False

    # Translate layer styles
    layer_configs = []
    for layer in carto_layers:
        config = translate_layer(layer)
        if config is not None:
            layer_configs.append(config)
            debug(f"Translated layer: {layer.name()}")

    if not layer_configs:
        error("No layers could be translated")
        return False

    # Extract view state
    view_state = extract_view_state(canvas)
    debug(f"View state: {view_state}")

    # Resolve basemap
    basemap_style = BASEMAP_STYLES.get(basemap or DEFAULT_BASEMAP, BASEMAP_STYLES[DEFAULT_BASEMAP])

    # Read and render the HTML template
    with open(TEMPLATE_PATH, "r") as f:
        template_str = f.read()

    template = string.Template(template_str)
    html = template.safe_substitute(
        title=project.title() or "CARTO Map Export",
        api_base_url=CARTO_API.base_url,
        access_token=access_token,
        layers_json=json.dumps(layer_configs),
        view_state_json=json.dumps(view_state),
        basemap_style=basemap_style,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    info(f"deck.gl HTML exported to: {output_path}")
    return True
