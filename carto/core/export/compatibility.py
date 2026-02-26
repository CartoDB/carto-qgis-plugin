from qgis.core import (
    QgsVectorLayer,
    QgsWkbTypes,
    QgsSingleSymbolRenderer,
    QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer,
    QgsRuleBasedRenderer,
    QgsVectorLayerSimpleLabeling,
)


# Symbol layer types with full deck.gl support
FULL_SUPPORT_SYMBOL_LAYERS = {
    "QgsSimpleFillSymbolLayer",
    "QgsSimpleLineSymbolLayer",
    "QgsSimpleMarkerSymbolLayer",
}

# Symbol layer types where we can extract color (rendered as solid/circle)
PARTIAL_SUPPORT_SYMBOL_LAYERS = {
    "QgsGradientFillSymbolLayer",
    "QgsShapeburstFillSymbolLayer",
    "QgsLinePatternFillSymbolLayer",
    "QgsPointPatternFillSymbolLayer",
    "QgsSVGFillSymbolLayer",
    "QgsRasterFillSymbolLayer",
    "QgsSvgMarkerSymbolLayer",
    "QgsRasterMarkerSymbolLayer",
    "QgsFontMarkerSymbolLayer",
}

# Non-solid fill styles that we render as solid (with warning)
# Qt.BrushStyle enum: 0=NoBrush, 1=SolidPattern, 2-14=patterns
SOLID_BRUSH_STYLE = "solid"


def _check_symbol(symbol):
    """Inspect a QgsSymbol and return warnings and symbol layer details."""
    warnings = []
    sl_details = []

    count = symbol.symbolLayerCount()
    if count > 1:
        warnings.append(
            f"Symbol has {count} stacked layers — only the first will be exported"
        )

    for i in range(count):
        sl = symbol.symbolLayer(i)
        sl_type = type(sl).__name__
        full = sl_type in FULL_SUPPORT_SYMBOL_LAYERS
        partial = sl_type in PARTIAL_SUPPORT_SYMBOL_LAYERS

        detail = {"type": sl_type, "supported": full or partial}
        sl_details.append(detail)

        if not full and not partial:
            warnings.append(
                f"{sl_type} not supported — color extracted as fallback"
            )
            continue

        if partial:
            # These are handled but with visual degradation
            friendly = sl_type.replace("Qgs", "").replace("SymbolLayer", "")
            if "GradientFill" in sl_type:
                warnings.append(
                    f"{friendly}: rendered via custom shader (viewport-relative)"
                )
            elif "Shapeburst" in sl_type:
                warnings.append(
                    f"{friendly}: approximated as radial gradient via shader"
                )
            elif "Pattern" in sl_type or "SVGFill" in sl_type or "RasterFill" in sl_type:
                warnings.append(
                    f"{friendly}: pattern will render as solid color"
                )
            elif "Marker" in sl_type:
                warnings.append(
                    f"{friendly}: will render as circle with extracted color"
                )
            continue

        # Check sub-properties of fully supported types
        if sl_type == "QgsSimpleFillSymbolLayer":
            style = sl.brushStyle()
            # Qt.SolidPattern = 1
            if style != 1:
                warnings.append(
                    "Pattern fill (hatching/dots) will render as solid color"
                )

        elif sl_type == "QgsSimpleMarkerSymbolLayer":
            props = sl.properties()
            shape = props.get("name", "circle")
            if shape != "circle":
                warnings.append(
                    f"Marker shape '{shape}' will render as circle"
                )

    return warnings, sl_details


def _check_symbols_in_list(symbols):
    """Check a list of symbols (from categorized/graduated categories)."""
    all_warnings = []
    all_details = []
    seen_warnings = set()

    for symbol in symbols:
        w, d = _check_symbol(symbol)
        all_details.extend(d)
        for warning in w:
            if warning not in seen_warnings:
                seen_warnings.add(warning)
                all_warnings.append(warning)

    return all_warnings, all_details


def check_layer(layer):
    """Inspect a QgsVectorLayer and return a compatibility report.

    Returns a dict with:
        layer_name: str
        status: "full" | "partial" | "unsupported"
        renderer: str (class name)
        warnings: list[str]
        symbol_layers: list[dict]
        has_labels: bool
        labels_warning: str | None
    """
    report = {
        "layer_name": layer.name(),
        "status": "full",
        "renderer": "",
        "renderer_label": "",
        "warnings": [],
        "symbol_layers": [],
        "has_labels": False,
        "labels_warning": None,
    }

    renderer = layer.renderer()
    if renderer is None:
        report["status"] = "unsupported"
        report["renderer"] = "None"
        report["renderer_label"] = "No renderer"
        report["warnings"].append("Layer has no renderer")
        return report

    renderer_type = type(renderer).__name__
    report["renderer"] = renderer_type

    # --- Renderer dispatch ---
    if isinstance(renderer, QgsSingleSymbolRenderer):
        report["renderer_label"] = "Single Symbol"
        symbol = renderer.symbol()
        warnings, details = _check_symbol(symbol)
        report["warnings"].extend(warnings)
        report["symbol_layers"] = details

    elif isinstance(renderer, QgsCategorizedSymbolRenderer):
        report["renderer_label"] = "Categorized"
        field = renderer.classAttribute()
        symbols = [cat.symbol() for cat in renderer.categories()]
        warnings, details = _check_symbols_in_list(symbols)
        report["warnings"].extend(warnings)
        report["symbol_layers"] = details

    elif isinstance(renderer, QgsGraduatedSymbolRenderer):
        report["renderer_label"] = "Graduated"
        symbols = [r.symbol() for r in renderer.ranges()]
        warnings, details = _check_symbols_in_list(symbols)
        report["warnings"].extend(warnings)
        report["symbol_layers"] = details

    elif isinstance(renderer, QgsRuleBasedRenderer):
        report["renderer_label"] = "Rule-based"
        report["status"] = "partial"
        report["warnings"].append(
            "Rule-based renderer: rules will be ignored, fallback style applied"
        )

    else:
        report["renderer_label"] = renderer_type.replace("Qgs", "").replace("Renderer", "")
        report["status"] = "unsupported"
        report["warnings"].append(
            f"{renderer_type} is not supported for deck.gl export"
        )

    # --- Labels ---
    labeling = layer.labeling()
    if labeling is not None:
        report["has_labels"] = True
        report["labels_warning"] = "Labels are not yet exported (future phase)"
        report["warnings"].append(report["labels_warning"])

    # --- Determine overall status ---
    if report["status"] != "unsupported":
        has_unsupported_sl = any(
            not sl["supported"] for sl in report["symbol_layers"]
        )
        if has_unsupported_sl or len(report["warnings"]) > 0:
            if report["status"] != "unsupported":
                report["status"] = "partial" if report["warnings"] else "full"

    return report
