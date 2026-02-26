import math

from qgis.core import (
    QgsWkbTypes,
    QgsSingleSymbolRenderer,
    QgsSymbol,
)

from carto.core.layers import (
    is_carto_layer,
    fqn_from_layer,
    connection_from_layer,
)
from carto.core.logging import debug


def _color_to_rgba(qcolor):
    """Convert a QColor to a [r, g, b, a] list (a is 0-255)."""
    return [qcolor.red(), qcolor.green(), qcolor.blue(), qcolor.alpha()]


def _get_geometry_type(layer):
    """Return 'point', 'line', or 'polygon' for a vector layer."""
    geom_type = layer.geometryType()
    if geom_type == QgsWkbTypes.PointGeometry:
        return "point"
    elif geom_type == QgsWkbTypes.LineGeometry:
        return "line"
    elif geom_type == QgsWkbTypes.PolygonGeometry:
        return "polygon"
    return "unknown"


def _translate_single_symbol(layer, renderer):
    """Translate a QgsSingleSymbolRenderer to deck.gl style props."""
    symbol = renderer.symbol()
    props = {}

    if symbol.symbolLayerCount() > 0:
        sl = symbol.symbolLayer(0)
        class_name = type(sl).__name__

        if class_name == "QgsSimpleFillSymbolLayer":
            props["getFillColor"] = _color_to_rgba(sl.color())
            props["getLineColor"] = _color_to_rgba(sl.strokeColor())
            stroke_width = sl.strokeWidth()
            if stroke_width > 0:
                props["getLineWidth"] = stroke_width
                props["lineWidthMinPixels"] = 1
            else:
                props["lineWidthMinPixels"] = 0

        elif class_name == "QgsSimpleLineSymbolLayer":
            props["getColor"] = _color_to_rgba(sl.color())
            width = sl.width()
            props["getWidth"] = width if width > 0 else 1
            props["widthMinPixels"] = 1

        elif class_name == "QgsSimpleMarkerSymbolLayer":
            props["getFillColor"] = _color_to_rgba(sl.color())
            props["getPointRadius"] = sl.size() / 2.0
            props["pointRadiusMinPixels"] = 2
            if hasattr(sl, "strokeColor"):
                props["getLineColor"] = _color_to_rgba(sl.strokeColor())
                props["lineWidthMinPixels"] = 1

        else:
            # Fallback: extract what we can from the symbol itself
            props["getFillColor"] = _color_to_rgba(symbol.color())

    props["opacity"] = layer.opacity()

    return props


def _translate_fallback(layer):
    """Fallback style for unsupported renderer types."""
    geom = _get_geometry_type(layer)
    props = {"opacity": layer.opacity()}

    if geom == "polygon":
        props["getFillColor"] = [200, 200, 200, 180]
        props["getLineColor"] = [100, 100, 100, 255]
        props["lineWidthMinPixels"] = 1
    elif geom == "line":
        props["getColor"] = [100, 100, 100, 255]
        props["widthMinPixels"] = 1
    elif geom == "point":
        props["getFillColor"] = [200, 200, 200, 180]
        props["pointRadiusMinPixels"] = 3

    return props


def translate_layer(layer):
    """Convert a CARTO QgsVectorLayer to a deck.gl layer config dict.

    Returns a dict with:
      - id, connection, tableName (source info)
      - deck.gl style properties (getFillColor, etc.)
    """
    if not is_carto_layer(layer):
        return None

    renderer = layer.renderer()
    if isinstance(renderer, QgsSingleSymbolRenderer):
        style_props = _translate_single_symbol(layer, renderer)
    else:
        debug(f"Unsupported renderer type: {type(renderer).__name__}, using fallback")
        style_props = _translate_fallback(layer)

    config = {
        "id": layer.id(),
        "name": layer.name(),
        "connection": connection_from_layer(layer),
        "tableName": fqn_from_layer(layer),
        "geometryType": _get_geometry_type(layer),
    }
    config.update(style_props)

    return config
