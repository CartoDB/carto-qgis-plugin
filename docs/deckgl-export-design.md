# deck.gl Map Export — Design Document

Export a QGIS project as a standalone, self-contained HTML file powered by
deck.gl. The exported map reproduces the layer stack, symbology, and view
visible in QGIS — no server required to open the result.

---

## Goals

- **One-click publish**: user clicks a toolbar button, gets an HTML file they
  can open in a browser, send by email, or host on any static server.
- **Visual fidelity**: the exported map should look recognizably like the QGIS
  canvas — same colours, same classification breaks, same label placement (where
  deck.gl allows it).
- **Mixed data sources**: CARTO layers, local files, remote services — all
  handled with a reasonable strategy per source type.
- **Iterative delivery**: ship a working v0 fast, refine styling precision over
  successive phases.

---

## Phased Roadmap

### Phase 1 — Proof of Concept (single-file HTML, basic styling)

The smallest thing that works end-to-end.

**Scope**

| Area | What's included |
|---|---|
| Data sources | CARTO layers only (via `@carto/api-client` + `VectorTileLayer`) |
| Geometry types | Point, Line, Polygon |
| Renderers | Single-symbol only |
| Style props | `getFillColor`, `getLineColor`, `getLineWidth`, `getPointRadius`, opacity |
| Basemap | CARTO Positron (default) |
| View | Centre and zoom from QGIS canvas extent |
| Output | One self-contained `.html` file (CDN script tags) |
| UI | Menu entry under CARTO plugin menu |

**Architecture sketch**

```
QgsProject
  │
  ├─ for each visible layer
  │    ├─ source_translator(layer)  → { layerClass, dataProps }
  │    └─ style_translator(layer)   → { getFillColor, getLineColor, ... }
  │    └─ merge both               → complete layer JS object
  │
  ├─ view_translator(canvas)       → { longitude, latitude, zoom }
  │
  └─ html_template.render(layers, view, basemap)
       → standalone .html file
```

**Deliverables**
- `carto/core/deckgl/` module with translator functions
- HTML Jinja2 template
- Menu action wired into the existing plugin

**What "done" looks like**: open the HTML in a browser, see a deck.gl map with
the same CARTO layers shown in QGIS, coloured correctly for single-symbol
renderers.

---

### Phase 2 — Data-Driven Styling

Translate the three main QGIS classification renderers into deck.gl accessors.

**Scope**

| Renderer | deck.gl mapping |
|---|---|
| Categorized | `colorCategories` extension or JS accessor with value map |
| Graduated (equal interval / quantile / etc.) | `colorBins` or `colorContinuous` extension |
| Rule-based (simple cases) | JS accessor with conditional logic |

**Style property coverage expands to**:
- `getFillColor` — from renderer symbol colour + classification
- `getLineColor` / `getLineWidth` — per-class outlines
- `getPointRadius` — size-based renderers
- Opacity — layer-level and per-symbol alpha

**What "done" looks like**: a QGIS project with a categorized land-use layer
and a graduated population-density layer exports to an HTML file where both
layers show the correct colour ramp / category colours.

---

### Phase 3 — Non-CARTO Data Sources

Support layers that don't come from CARTO.

**Layer source classification**

```
Has CARTO metadata?
  ├─ YES → CartoLayer / VectorTileLayer (Phase 1 path)
  └─ NO
       ├─ Vector (ogr, delimitedtext, memory)
       │    ├─ Small (< ~5 MB) → embed as inline GeoJSON → GeoJsonLayer
       │    └─ Large (> ~5 MB) → warn, embed with size notice
       │
       ├─ Remote vector
       │    ├─ WFS          → GeoJsonLayer with WFS GetFeature URL
       │    ├─ ArcGIS FS    → GeoJsonLayer with /query?f=geojson URL
       │    └─ Vector tiles  → MVTLayer with URL template
       │
       ├─ Remote raster
       │    ├─ XYZ tiles     → TileLayer + BitmapLayer
       │    ├─ WMS / WMTS    → TileLayer + BitmapLayer (GetMap URL)
       │    └─ COG (remote)  → TileLayer with range-read loader
       │
       └─ Unsupported (PostGIS, local raster, etc.)
            → show warning in export dialog, skip layer
```

**Export dialog** (new UI):

```
┌──────────────────────────────────────────────────────────┐
│  Export to deck.gl                                        │
├──────────────────────────────────────────────────────────┤
│                                                           │
│  Layer             Source          Action         Size     │
│  ─────             ──────          ──────         ────     │
│  [x] buildings     CARTO           CartoLayer       —     │
│  [x] roads         CARTO           CartoLayer       —     │
│  [x] parks         Local .geojson  Embed GeoJSON  2 MB    │
│  [!] census        Local .gpkg     Embed GeoJSON  48 MB   │
│  [x] satellite     XYZ tiles       TileLayer        —     │
│  [ ] postgis_data  PostGIS         Not supported    —     │
│                                                           │
│  [!] 1 layer exceeds 5 MB — export may be slow            │
│                                                           │
│  [Cancel]                            [Export]             │
└──────────────────────────────────────────────────────────┘
```

**Inline GeoJSON serialisation** (runs at export time in Python):

```python
features = []
for feat in layer.getFeatures():
    geom = feat.geometry()
    geom.transform(QgsCoordinateTransform(
        layer.crs(),
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance()
    ))
    features.append({
        "type": "Feature",
        "geometry": json.loads(geom.asJson()),
        "properties": {f.name(): feat[f.name()] for f in layer.fields()},
    })
```

**What "done" looks like**: a project with a mix of CARTO layers, a local
GeoJSON, and an XYZ basemap exports correctly. Unsupported layers are shown
with a warning in the dialog and omitted from the output.

---

### Phase 4 — Interactivity and Polish

| Feature | Implementation |
|---|---|
| Hover tooltips | `pickable: true` + `getTooltip` with field names from QGIS |
| Legend | HTML overlay generated from renderer metadata |
| Layer toggle | Checkbox list that sets `layer.visible` |
| Basemap picker | Dropdown switching between CARTO basemap styles |
| Popup on click | Show all feature attributes in a card |

---

### Phase 5 — Advanced Styling

- Labels → `TextLayer` sublayer or `pointType: 'circle+text'`
- SVG / image markers → `IconLayer` with base64-encoded marker images
- Hatching / pattern fills → approximate with semi-transparent overlays
- Graduated symbol size (proportional symbols)
- Blend modes / compositing where deck.gl supports them
- Rule-based renderer with complex filter expressions → JS accessor with
  full expression evaluation

---

### Future (not scoped yet)

- **Upload to CARTO**: for large local layers, offer to import into the user's
  data warehouse so they become CartoLayers (the plugin already has
  `ImportLayerTask` — this would wire it into the export flow).
- **3D extrusion**: `extruded: true` with `getElevation` accessor from a
  numeric field.
- **Animations**: temporal data → `TripsLayer` or time-slider widget.
- **Tiling local data**: for very large local layers, pre-tile to PMTiles and
  bundle as a sidecar file.
- **Export builder UI**: an interactive dialog where users can customize the
  deck.gl map before exporting — reorder layers, tweak colours, adjust
  opacity, pick basemap, configure tooltips, etc. Rather than a blind
  snapshot of the canvas, this would be a WYSIWYG editor for the output.
  Significant UI effort; deferred until the core export pipeline is stable.

---

## Architecture

### Module layout

```
carto/
  core/
    deckgl/
      __init__.py
      exporter.py          # top-level orchestration: collect layers, render HTML
      source_translator.py # layer source → deck.gl data config
      style_translator.py  # QgsRenderer → deck.gl style props
      view_translator.py   # QgsMapCanvas → initial view state
      template.html        # Jinja2 HTML template
  gui/
    exportdeckgldialog.py  # (Phase 3+) export dialog with layer table
```

### Key design decisions

**1. Two independent translators merged at export time**

```
source_translator(layer) → { "@@type": "VectorTileLayer", data: {...} }
style_translator(layer)  → { getFillColor: [31, 120, 180], ... }

merge(source, style)     → complete deck.gl layer spec
```

The style translator is source-agnostic — it only looks at the renderer and
geometry type. The source translator only cares about where the data lives.
This keeps the two concerns cleanly separated and independently testable.

**2. Everything serialised to a JSON layer spec**

Rather than generating ad-hoc JavaScript strings, each layer is represented as
a Python dict that maps to a deck.gl layer specification. The template receives
a JSON array of these specs and does the minimal JS needed to instantiate them.

Benefits:
- Easy to unit-test (compare dicts)
- No string-interpolation bugs
- Template stays simple

**3. CDN-hosted dependencies (Phase 1)**

The HTML loads deck.gl and CARTO libraries from unpkg/jsdelivr CDN via
`<script>` tags. No build step, no bundler, no node_modules. The file is
self-contained except for these CDN references.

Later phases could optionally inline the libraries for fully offline use, but
that adds ~2 MB to the file size.

**4. Coordinate handling**

All geometries are reprojected to EPSG:4326 (WGS 84) at export time. deck.gl
works in longitude/latitude by default. The `view_translator` converts the QGIS
canvas extent (which may be in any CRS) to a lng/lat centre + zoom level.

---

## Style Translation Reference

### Single Symbol

```python
# Input: QgsSingleSymbolRenderer
symbol = renderer.symbol()
color = symbol.color()  # QColor

# Output:
{"getFillColor": [color.red(), color.green(), color.blue(), color.alpha()]}
```

### Categorized

```python
# Input: QgsCategorizedSymbolRenderer
field = renderer.classAttribute()

# Build value → color map
categories = {}
for cat in renderer.categories():
    c = cat.symbol().color()
    categories[cat.value()] = [c.red(), c.green(), c.blue(), c.alpha()]

# Output option A — colorCategories extension:
{
    "getFillColor": {
        "@@function": "colorCategories",
        "attr": field,
        "domain": list(categories.keys()),
        "colors": list(categories.values()),
    }
}

# Output option B — inline JS accessor:
# function(d) {
#   const v = d.properties['landuse'];
#   if (v === 'residential') return [255, 0, 0, 255];
#   if (v === 'commercial') return [0, 0, 255, 255];
#   return [200, 200, 200, 255];
# }
```

### Graduated

```python
# Input: QgsGraduatedSymbolRenderer
field = renderer.classAttribute()
ranges = renderer.ranges()  # list of QgsRendererRange

breaks = [r.upperValue() for r in ranges]
colors = []
for r in ranges:
    c = r.symbol().color()
    colors.append([c.red(), c.green(), c.blue(), c.alpha()])

# Output — colorBins extension:
{
    "getFillColor": {
        "@@function": "colorBins",
        "attr": field,
        "domain": breaks,
        "colors": colors,
    }
}
```

---

## Data Source Translation Reference

| QGIS provider | Condition | deck.gl layer | Data prop |
|---|---|---|---|
| CARTO (has metadata) | — | `VectorTileLayer` | `vectorTableSource(...)` |
| `ogr`, `delimitedtext`, `memory` | < 5 MB | `GeoJsonLayer` | inline `{type: "FeatureCollection", ...}` |
| `ogr`, `delimitedtext`, `memory` | >= 5 MB | `GeoJsonLayer` | inline (with warning) |
| `wfs` | — | `GeoJsonLayer` | WFS GetFeature URL (`outputFormat=application/json`) |
| `arcgisfeatureserver` | — | `GeoJsonLayer` | REST query URL (`f=geojson`) |
| `vectortile` (MVT) | — | `MVTLayer` | URL template `{z}/{x}/{y}.pbf` |
| `wms` / XYZ | — | `TileLayer` + `BitmapLayer` | tile URL template |
| `gdal` (remote) | HTTP(S) URL | `TileLayer` + `BitmapLayer` | COG URL |
| `gdal` (local) | local path | skip | warning: local raster |
| `postgres` | — | skip | warning: no browser access |

---

## Open Questions

1. **deck.gl v8 vs v9**: v9 has a cleaner CARTO integration
   (`@carto/api-client` replaces `@deck.gl/carto`), but CDN bundle naming
   differs. Need to verify CDN availability for v9.

2. **CORS for WFS/ArcGIS**: remote services may not have CORS headers.
   Should we add a warning, or attempt to proxy? For Phase 3 we just warn.

3. **Label placement**: deck.gl's text rendering is simpler than QGIS. We may
   need to accept visual differences or skip labels in early phases.

4. **Large inline GeoJSON**: browsers struggle above ~50 MB. Should we set a
   hard cap and refuse, or just warn? Current design: warn at 5 MB, no hard
   cap.

5. **Authentication for CARTO layers**: the exported HTML needs a CARTO API
   key or access token. How is this provided? Options: embed in the HTML
   (simple but exposes the token), require the user to paste it, or use a
   public-access token scoped to read-only.
