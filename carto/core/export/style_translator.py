import math

from qgis.core import (
    QgsWkbTypes,
    QgsSingleSymbolRenderer,
    QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer,
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


def _color_from_symbol(symbol):
    """Extract fill color from any symbol, regardless of symbol layer type."""
    if symbol.symbolLayerCount() > 0:
        sl = symbol.symbolLayer(0)
        return _color_to_rgba(sl.color())
    return _color_to_rgba(symbol.color())


def _line_color_from_symbol(symbol):
    """Extract line/stroke color from a symbol."""
    if symbol.symbolLayerCount() > 0:
        sl = symbol.symbolLayer(0)
        class_name = type(sl).__name__
        if class_name == "QgsSimpleFillSymbolLayer":
            return _color_to_rgba(sl.strokeColor())
        if class_name == "QgsSimpleMarkerSymbolLayer" and hasattr(sl, "strokeColor"):
            return _color_to_rgba(sl.strokeColor())
    return None


def _size_from_symbol(symbol):
    """Extract point radius or line width from a symbol."""
    if symbol.symbolLayerCount() > 0:
        sl = symbol.symbolLayer(0)
        class_name = type(sl).__name__
        if class_name == "QgsSimpleMarkerSymbolLayer":
            return sl.size() / 2.0
        if class_name == "QgsSimpleLineSymbolLayer":
            return sl.width()
    return None


def _translate_categorized(layer, renderer):
    """Translate a QgsCategorizedSymbolRenderer to deck.gl style props.

    Produces accessor descriptors with __type='categorized' that the
    HTML template resolves into JS accessor functions at runtime.
    """
    field = renderer.classAttribute()
    geom = _get_geometry_type(layer)
    props = {"opacity": layer.opacity()}

    # Build category -> color mapping
    fill_categories = {}
    line_categories = {}
    size_categories = {}
    default_fill = [128, 128, 128, 200]
    default_line = None
    default_size = None

    for cat in renderer.categories():
        value = cat.value()
        symbol = cat.symbol()

        # Skip the "all other values" category (empty/None value)
        if value == "" or value is None:
            default_fill = _color_from_symbol(symbol)
            default_line = _line_color_from_symbol(symbol)
            default_size = _size_from_symbol(symbol)
            continue

        # Convert value to string key for JSON serialization
        key = str(value)
        fill_categories[key] = _color_from_symbol(symbol)

        lc = _line_color_from_symbol(symbol)
        if lc:
            line_categories[key] = lc

        sz = _size_from_symbol(symbol)
        if sz is not None:
            size_categories[key] = sz

    # Fill color accessor
    color_prop = "getColor" if geom == "line" else "getFillColor"
    props[color_prop] = {
        "__type": "categorized",
        "field": field,
        "categories": fill_categories,
        "default": default_fill,
    }

    # Line color accessor (for polygons/points with strokes)
    if line_categories and geom != "line":
        props["getLineColor"] = {
            "__type": "categorized",
            "field": field,
            "categories": line_categories,
            "default": default_line or [100, 100, 100, 255],
        }
        props["lineWidthMinPixels"] = 1

    # Size accessor (for points or lines with varying size)
    if size_categories:
        size_prop = "getPointRadius" if geom == "point" else "getWidth"
        props[size_prop] = {
            "__type": "categorized",
            "field": field,
            "categories": size_categories,
            "default": default_size or 3,
        }
        if geom == "point":
            props["pointRadiusMinPixels"] = 2

    return props


def _translate_graduated(layer, renderer):
    """Translate a QgsGraduatedSymbolRenderer to deck.gl style props.

    Produces accessor descriptors with __type='graduated' that the
    HTML template resolves into JS accessor functions at runtime.
    """
    field = renderer.classAttribute()
    geom = _get_geometry_type(layer)
    props = {"opacity": layer.opacity()}

    # Build breaks and colors from ranges
    breaks = []
    fill_colors = []
    line_colors = []
    sizes = []

    for r in renderer.ranges():
        breaks.append(r.upperValue())
        fill_colors.append(_color_from_symbol(r.symbol()))

        lc = _line_color_from_symbol(r.symbol())
        if lc:
            line_colors.append(lc)

        sz = _size_from_symbol(r.symbol())
        if sz is not None:
            sizes.append(sz)

    # Fill color accessor
    color_prop = "getColor" if geom == "line" else "getFillColor"
    props[color_prop] = {
        "__type": "graduated",
        "field": field,
        "breaks": breaks,
        "colors": fill_colors,
    }

    # Line color accessor
    if line_colors and len(line_colors) == len(breaks) and geom != "line":
        props["getLineColor"] = {
            "__type": "graduated",
            "field": field,
            "breaks": breaks,
            "colors": line_colors,
        }
        props["lineWidthMinPixels"] = 1

    # Size accessor (proportional symbols)
    if sizes and len(sizes) == len(breaks):
        size_prop = "getPointRadius" if geom == "point" else "getWidth"
        props[size_prop] = {
            "__type": "graduated",
            "field": field,
            "breaks": breaks,
            "colors": sizes,  # reuse "colors" key for sizes
        }
        if geom == "point":
            props["pointRadiusMinPixels"] = 2

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
    elif isinstance(renderer, QgsCategorizedSymbolRenderer):
        style_props = _translate_categorized(layer, renderer)
    elif isinstance(renderer, QgsGraduatedSymbolRenderer):
        style_props = _translate_graduated(layer, renderer)
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
