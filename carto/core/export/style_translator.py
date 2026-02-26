import math

from qgis.core import (
    QgsWkbTypes,
    QgsSingleSymbolRenderer,
    QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer,
    QgsSymbol,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
)

from carto.core.layers import (
    is_carto_layer,
    fqn_from_layer,
    connection_from_layer,
)
from carto.core.logging import debug


def _color_to_rgba(qcolor, opacity=1.0):
    """Convert a QColor to a [r, g, b, a] list (a is 0-255).

    The opacity parameter (0-1) is multiplied into the alpha channel
    to account for symbol-level opacity in QGIS.
    """
    a = int(qcolor.alpha() * opacity)
    return [qcolor.red(), qcolor.green(), qcolor.blue(), a]


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


def _extract_sl_props(sl, sym_opacity):
    """Extract deck.gl-compatible properties from any symbol layer.

    Handles known types with their specific properties, and falls back
    to extracting color() for unknown types (gradient fills, pattern
    fills, SVG markers, etc.).
    """
    class_name = type(sl).__name__
    props = {}

    if class_name == "QgsSimpleFillSymbolLayer":
        # brushStyle(): 0=NoBrush (transparent), 1=SolidPattern, 2+=patterns
        brush_style = sl.brushStyle() if hasattr(sl, "brushStyle") else 1
        if brush_style == 0:
            props["getFillColor"] = [0, 0, 0, 0]  # transparent
        else:
            props["getFillColor"] = _color_to_rgba(sl.color(), sym_opacity)
        props["getLineColor"] = _color_to_rgba(sl.strokeColor(), sym_opacity)
        stroke_width = sl.strokeWidth()
        if stroke_width > 0:
            props["getLineWidth"] = stroke_width
            props["lineWidthMinPixels"] = 1
        else:
            props["lineWidthMinPixels"] = 0

    elif class_name == "QgsSimpleLineSymbolLayer":
        props["getColor"] = _color_to_rgba(sl.color(), sym_opacity)
        width = sl.width()
        props["getWidth"] = width if width > 0 else 1
        props["widthMinPixels"] = 1

    elif class_name == "QgsSimpleMarkerSymbolLayer":
        props["getFillColor"] = _color_to_rgba(sl.color(), sym_opacity)
        props["getPointRadius"] = sl.size() / 2.0
        props["pointRadiusMinPixels"] = 2
        if hasattr(sl, "strokeColor"):
            props["getLineColor"] = _color_to_rgba(sl.strokeColor(), sym_opacity)
            props["lineWidthMinPixels"] = 1

    elif class_name == "QgsGradientFillSymbolLayer":
        # Gradient fill: extract full gradient parameters for shader rendering
        props["getFillColor"] = _color_to_rgba(sl.color(), sym_opacity)
        color2 = _color_to_rgba(sl.color2(), sym_opacity) if hasattr(sl, "color2") else props["getFillColor"]
        # gradientType(): 0=linear, 1=radial, 2=conical
        grad_type = sl.gradientType() if hasattr(sl, "gradientType") else 0
        # referencePoint1/2: QPointF (0-1 range)
        ref1 = [0.5, 0.0]
        ref2 = [0.5, 1.0]
        if hasattr(sl, "referencePoint1"):
            p1 = sl.referencePoint1()
            ref1 = [p1.x(), p1.y()]
        if hasattr(sl, "referencePoint2"):
            p2 = sl.referencePoint2()
            ref2 = [p2.x(), p2.y()]
        # angle offset
        angle = sl.angle() if hasattr(sl, "angle") else 0
        # gradientSpread(): 0=pad, 1=reflect, 2=repeat
        spread = sl.gradientSpread() if hasattr(sl, "gradientSpread") else 0
        # coordinateMode(): 0=feature, 1=viewport
        coord_mode = 0
        if hasattr(sl, "coordinateMode"):
            coord_mode = sl.coordinateMode()

        # Extract multi-stop color ramp if available
        color_stops = None
        if hasattr(sl, "colorRamp"):
            ramp = sl.colorRamp()
            if ramp and hasattr(ramp, "stops"):
                stops = ramp.stops()
                if stops:
                    # Build full stops list: color1 at 0, intermediates, color2 at 1
                    all_stops = [[0.0, _color_to_rgba(ramp.color1(), sym_opacity)]]
                    for s in stops:
                        all_stops.append([s.offset, _color_to_rgba(s.color, sym_opacity)])
                    all_stops.append([1.0, _color_to_rgba(ramp.color2(), sym_opacity)])
                    color_stops = all_stops
                    debug(f"Gradient color ramp: {len(all_stops)} stops")

        props["gradient"] = {
            "color1": props["getFillColor"],
            "color2": color2,
            "type": grad_type,  # 0=linear, 1=radial, 2=conical
            "ref1": ref1,
            "ref2": ref2,
            "angle": angle,
            "spread": spread,  # 0=pad, 1=reflect, 2=repeat
            "coordMode": coord_mode,  # 0=feature, 1=viewport
        }
        if color_stops:
            props["gradient"]["stops"] = color_stops
        debug(f"Gradient fill extracted: type={grad_type}, angle={angle}, coordMode={coord_mode}")

    elif class_name == "QgsShapeburstFillSymbolLayer":
        # Shapeburst: extract colors, render as simple gradient
        props["getFillColor"] = _color_to_rgba(sl.color(), sym_opacity)
        color2 = _color_to_rgba(sl.color2(), sym_opacity) if hasattr(sl, "color2") else props["getFillColor"]
        props["gradient"] = {
            "color1": props["getFillColor"],
            "color2": color2,
            "type": 1,  # radial approximation
            "ref1": [0.5, 0.5],
            "ref2": [1.0, 1.0],
            "angle": 0,
            "spread": 0,
        }

    elif class_name in (
        "QgsLinePatternFillSymbolLayer",
        "QgsPointPatternFillSymbolLayer",
        "QgsSVGFillSymbolLayer",
        "QgsRasterFillSymbolLayer",
    ):
        # Pattern fills: extract color as solid
        props["getFillColor"] = _color_to_rgba(sl.color(), sym_opacity)

    elif class_name == "QgsMarkerLineSymbolLayer":
        # Marker line: renders markers along a line/border.
        # Extract marker properties for dash-dot rendering via PathStyleExtension.
        marker_color = None
        marker_size = 3.0
        marker_interval = 10.0
        try:
            # Get color and size from the sub-symbol (the actual marker)
            sub = sl.subSymbol() if hasattr(sl, "subSymbol") else None
            if sub:
                marker_color = _color_to_rgba(sub.color(), sym_opacity)
                for j in range(sub.symbolLayerCount()):
                    msl = sub.symbolLayer(j)
                    if hasattr(msl, "size"):
                        marker_size = msl.size()
                        break
                    if hasattr(msl, "color"):
                        marker_color = _color_to_rgba(msl.color(), sym_opacity)
            if not marker_color:
                marker_color = _color_to_rgba(sl.color(), sym_opacity)
            # Interval between markers
            if hasattr(sl, "interval"):
                marker_interval = sl.interval()
        except Exception:
            marker_color = marker_color or [100, 100, 100, 255]

        props["getLineColor"] = marker_color
        # Use marker size as line width so dashes become visible dots
        props["getLineWidth"] = max(marker_size, 2.0)
        props["lineWidthMinPixels"] = max(int(marker_size), 2)
        # Store marker line config for PathStyleExtension dash rendering
        # dashArray is [dashSize, gapSize] relative to line width
        # A very short dash + gap approximates dots
        gap_ratio = max(marker_interval / max(marker_size, 0.5), 1.0)
        props["markerLine"] = {
            "dashArray": [0.5, gap_ratio],
            "color": marker_color,
            "width": marker_size,
        }
        debug(f"Marker line extracted: size={marker_size}, interval={marker_interval}, gap_ratio={gap_ratio}")

    elif class_name in ("QgsSvgMarkerSymbolLayer", "QgsRasterMarkerSymbolLayer",
                         "QgsFontMarkerSymbolLayer"):
        # Non-simple markers: extract color and size
        props["getFillColor"] = _color_to_rgba(sl.color(), sym_opacity)
        if hasattr(sl, "size"):
            props["getPointRadius"] = sl.size() / 2.0
            props["pointRadiusMinPixels"] = 2

    else:
        # Unknown type: best effort — extract color if available
        try:
            props["getFillColor"] = _color_to_rgba(sl.color(), sym_opacity)
        except Exception:
            pass

    return props


def _translate_single_symbol(layer, renderer):
    """Translate a QgsSingleSymbolRenderer to deck.gl style props.

    Walks ALL symbol layers in the stack and merges their properties.
    Later layers override earlier ones, so the top-most visual properties win.
    """
    symbol = renderer.symbol()
    sym_opacity = symbol.opacity()
    props = {}

    for i in range(symbol.symbolLayerCount()):
        sl = symbol.symbolLayer(i)
        sl_props = _extract_sl_props(sl, sym_opacity)
        # Merge: later symbol layers override earlier ones,
        # but preserve gradient config if the new layer doesn't provide one
        if "gradient" in props and "gradient" not in sl_props:
            saved_gradient = props["gradient"]
            saved_fill = props.get("getFillColor")
            props.update(sl_props)
            props["gradient"] = saved_gradient
            if saved_fill:
                props["getFillColor"] = saved_fill
        else:
            props.update(sl_props)

    # If no symbol layer set a fill color (e.g. outline-only styles),
    # use transparent fill for polygons so the basemap shows through
    if "getFillColor" not in props and "gradient" not in props:
        geom = _get_geometry_type(layer)
        if geom == "polygon":
            props["getFillColor"] = [0, 0, 0, 0]  # transparent
        elif not props:
            props["getFillColor"] = _color_to_rgba(symbol.color(), sym_opacity)

    props["opacity"] = layer.opacity()

    return props


def _color_from_symbol(symbol):
    """Extract fill color from any symbol, walking all symbol layers."""
    op = symbol.opacity()
    color = None
    for i in range(symbol.symbolLayerCount()):
        sl = symbol.symbolLayer(i)
        try:
            color = _color_to_rgba(sl.color(), op)
        except Exception:
            pass
    return color or _color_to_rgba(symbol.color(), op)


def _line_color_from_symbol(symbol):
    """Extract line/stroke color from a symbol, walking all symbol layers."""
    op = symbol.opacity()
    for i in range(symbol.symbolLayerCount()):
        sl = symbol.symbolLayer(i)
        class_name = type(sl).__name__
        if class_name == "QgsSimpleFillSymbolLayer":
            return _color_to_rgba(sl.strokeColor(), op)
        if class_name == "QgsSimpleLineSymbolLayer":
            return _color_to_rgba(sl.color(), op)
        if class_name == "QgsSimpleMarkerSymbolLayer" and hasattr(sl, "strokeColor"):
            return _color_to_rgba(sl.strokeColor(), op)
    return None


def _size_from_symbol(symbol):
    """Extract point radius or line width from a symbol, walking all symbol layers."""
    for i in range(symbol.symbolLayerCount()):
        sl = symbol.symbolLayer(i)
        class_name = type(sl).__name__
        if class_name == "QgsSimpleMarkerSymbolLayer":
            return sl.size() / 2.0
        if class_name == "QgsSimpleLineSymbolLayer":
            return sl.width()
        if hasattr(sl, "size"):
            try:
                return sl.size() / 2.0
            except Exception:
                pass
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

    # If gradient uses feature coordinate mode, add layer extent (in EPSG:4326)
    if "gradient" in config and config["gradient"].get("coordMode", 0) == 0:
        try:
            extent = layer.extent()
            crs = layer.crs()
            if crs.authid() != "EPSG:4326":
                transform = QgsCoordinateTransform(
                    crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()
                )
                extent = transform.transformBoundingBox(extent)
            config["gradient"]["extent"] = [
                extent.xMinimum(), extent.yMinimum(),
                extent.xMaximum(), extent.yMaximum(),
            ]
            debug(f"Gradient extent: {config['gradient']['extent']}")
        except Exception as e:
            debug(f"Could not get layer extent for gradient: {e}")

    return config
