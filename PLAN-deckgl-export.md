# CARTO QGIS Plugin — deck.gl Export Feature Plan

## Goal

Add a "Export to deck.gl HTML" action to the CARTO QGIS plugin that generates a
self-contained HTML file visualizing the current map using deck.gl + CARTO data
sources. The exported map keeps CARTO layers **remote** (fetched via the CARTO
API at view time) and translates QGIS styling to deck.gl layer properties.

---

## Research Findings

### 1. How the plugin identifies CARTO layers

- **Path-based detection**: `is_carto_layer(layer)` checks if the layer source
  path starts with the `cartolayers/` folder
  (`carto/core/layers.py:282-284`).
- **Path structure**: `{cartolayers}/{connection_name}/{database_id}/{schema_id}/{table_id}.gpkg`
- **Metadata sidecar**: Each `.gpkg` has a companion `.cartometadata` JSON file
  containing:
  ```json
  {
    "pk": "id",
    "columns": [...],
    "geom_column": "geom",
    "can_write": true,
    "schema_changed": false,
    "provider_type": "bigquery"
  }
  ```
- **Helper functions** (all in `carto/core/layers.py`):
  - `fqn_from_layer(layer)` → `"database.schema.table"` (becomes `tableName` for deck.gl)
  - `connection_from_layer(layer)` → connection name (becomes `connectionName`)
  - `layer_metadata(layer)` → full metadata dict
  - `geom_column_from_layer(layer)` → geometry column name
  - `provider_type_from_layer(layer)` → e.g. "bigquery", "postgres", "snowflake"

### 2. Authentication & token for exported HTML

- **Current session token**: `CARTO_API.token` (OAuth token, temporary)
- **API base URL**: `CARTO_API.base_url` (configured at login, e.g. `https://gcp-us-east1.api.carto.com/`)
- **Tokens API** (`POST {base_url}v3/tokens`): Can create a **permanent**,
  **scoped** API Access Token using the current OAuth token. Grants can be
  restricted to specific tables/connections.
  ```python
  grants = [{"connection_name": conn, "source": fqn} for each CARTO layer]
  response = requests.post(
      f"{CARTO_API.base_url}v3/tokens",
      headers={"Authorization": f"Bearer {CARTO_API.token}"},
      json={"grants": grants}
  )
  api_access_token = response.json()["token"]
  ```
  This is the recommended approach: create a scoped token at export time.

### 3. deck.gl CDN availability (standalone, no bundler)

Works perfectly for self-contained HTML:

```html
<!-- MapLibre GL for basemap rendering -->
<link href="https://unpkg.com/maplibre-gl/dist/maplibre-gl.css" rel="stylesheet" />
<script src="https://unpkg.com/maplibre-gl/dist/maplibre-gl.js"></script>

<!-- deck.gl core -->
<script src="https://unpkg.com/deck.gl@^9.0.0/dist.min.js"></script>

<!-- deck.gl CARTO module (vectorTableSource, VectorTileLayer, etc.) -->
<script src="https://unpkg.com/@deck.gl/carto@^9.0.0/dist.min.js"></script>
```

Global namespace: `deck.DeckGL`, `deck.carto.vectorTableSource`,
`deck.carto.VectorTileLayer`, etc.

### 4. Lessons from qgis2web (existing QGIS → web export plugin)

- Uses `isinstance()` dispatch on QGIS renderer types — same approach we'll use
- Serializes everything to GeoJSON files — we avoid this for CARTO layers
- Creator describes JS string generation as "clunky" — validates our approach of
  using an intermediate Python dict representation first, then serializing to JS
- No existing plugin exports to deck.gl — this is first-of-its-kind

### 5. CARTO Python packages (potential abstractions)

- **`carto-auth`** (`pip install carto-auth`): Provides `CartoAuth.from_oauth()`,
  `get_access_token()`, `get_api_base_url()`. Could be useful but the plugin
  already has its own auth flow.
- **CARTO CLI** (`npm install -g @carto/carto-cli`): Node.js based, not Python.
  Supports `carto auth login`, `carto maps list`, etc. Has `--json` flag for
  machine-parseable output. **Not ideal** for embedding in a Python QGIS plugin.
- **`pydeck-carto`**: Wrapper around pydeck for CartoLayer. Could be useful for
  server-side rendering but not for generating standalone HTML files.
- **Recommendation**: For Phase 1, call the Tokens API directly using the
  existing `CARTO_API.session` (requests session). No additional dependencies.
  Evaluate `carto-auth` for later phases if we need more auth flexibility.

---

## Architecture

### Data flow

```
QGIS Project
  ├── CARTO Layer (remote data)
  │   ├── is_carto_layer() → true
  │   ├── fqn_from_layer() → "db.schema.table"
  │   ├── connection_from_layer() → "my_connection"
  │   └── QgsVectorLayer.renderer() → QgsSingleSymbolRenderer / etc.
  │
  └── Regular Layer (local data, Phase 2+)
      └── Export as inline GeoJSON

         ↓ Style Translation (Python)

Intermediate Representation (Python dicts)
  {
    "type": "VectorTileLayer",
    "connection": "my_connection",
    "tableName": "db.schema.table",
    "getFillColor": [255, 0, 0, 200],
    "getLineColor": [0, 0, 0, 255],
    "lineWidthMinPixels": 1,
    ...
  }

         ↓ Template Rendering (Jinja2 or string.Template)

Self-contained HTML file
  - CDN script tags (deck.gl, MapLibre GL)
  - Embedded API access token (scoped, permanent)
  - Layer definitions as JavaScript
  - View state from QGIS map canvas
```

### Module structure (new files)

```
carto/
├── core/
│   ├── export/
│   │   ├── __init__.py
│   │   ├── style_translator.py    # QGIS renderer → deck.gl props
│   │   ├── token_manager.py       # Create scoped API access tokens
│   │   └── html_generator.py      # Assemble the final HTML
│   └── ...
├── gui/
│   ├── exportdialog.py            # Export dialog UI
│   └── ...
├── templates/
│   └── deckgl_map.html            # HTML template
└── plugin.py                      # Add menu action
```

---

## Phase 1 — Proof of Concept

**Scope**: Export CARTO layers with single-symbol styling to a working HTML.

### 1.1 Style Translator (`style_translator.py`)

Translate QGIS renderers to deck.gl layer properties:

```python
def translate_layer(qgs_layer) -> dict:
    """Convert a QgsVectorLayer to a deck.gl layer config dict."""
    renderer = qgs_layer.renderer()
    if isinstance(renderer, QgsSingleSymbolRenderer):
        return translate_single_symbol(qgs_layer, renderer)
    # Phase 2: QgsCategorizedSymbolRenderer, QgsGraduatedSymbolRenderer
    else:
        return translate_fallback(qgs_layer)
```

QGIS symbol → deck.gl property mapping:

| QGIS Property | deck.gl Property |
|---|---|
| `QgsSimpleFillSymbolLayer.color()` | `getFillColor` |
| `QgsSimpleFillSymbolLayer.strokeColor()` | `getLineColor` |
| `QgsSimpleFillSymbolLayer.strokeWidth()` | `getLineWidth` / `lineWidthMinPixels` |
| `QgsSimpleLineSymbolLayer.color()` | `getColor` |
| `QgsSimpleLineSymbolLayer.width()` | `getWidth` / `widthMinPixels` |
| `QgsSimpleMarkerSymbolLayer.color()` | `getFillColor` |
| `QgsSimpleMarkerSymbolLayer.size()` | `getPointRadius` / `pointRadiusMinPixels` |
| `QgsVectorLayer.opacity()` | Layer `opacity` (0-1) |
| Layer geometry type (Point/Line/Polygon) | Determines deck.gl layer type |

Color conversion: `QColor` → `[r, g, b, a]` where a is 0-255.

### 1.2 Token Manager (`token_manager.py`)

```python
def create_export_token(layers: list[QgsVectorLayer]) -> str:
    """Create a scoped API access token for the given CARTO layers."""
    grants = []
    for layer in layers:
        if is_carto_layer(layer):
            grants.append({
                "connection_name": connection_from_layer(layer),
                "source": fqn_from_layer(layer),
            })

    response = CARTO_API.session.post(
        f"{CARTO_API.base_url}v3/tokens",
        headers={"Authorization": f"Bearer {CARTO_API.token}"},
        json={"grants": grants},
    )
    response.raise_for_status()
    return response.json()["token"]
```

### 1.3 HTML Template (`templates/deckgl_map.html`)

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{{ title }}</title>
  <style>body { margin: 0; width: 100vw; height: 100vh; }</style>
  <link href="https://unpkg.com/maplibre-gl/dist/maplibre-gl.css" rel="stylesheet" />
  <script src="https://unpkg.com/maplibre-gl/dist/maplibre-gl.js"></script>
  <script src="https://unpkg.com/deck.gl@^9.0.0/dist.min.js"></script>
  <script src="https://unpkg.com/@deck.gl/carto@^9.0.0/dist.min.js"></script>
</head>
<body>
<script>
  const API_BASE_URL = '{{ api_base_url }}';
  const ACCESS_TOKEN = '{{ access_token }}';

  const layerConfigs = {{ layers_json }};

  async function initMap() {
    const layers = await Promise.all(layerConfigs.map(async (config) => {
      const source = await deck.carto.vectorTableSource({
        accessToken: ACCESS_TOKEN,
        apiBaseUrl: API_BASE_URL,
        connectionName: config.connection,
        tableName: config.tableName,
      });
      return new deck.carto.VectorTileLayer({
        id: config.id,
        data: source,
        opacity: config.opacity,
        getFillColor: config.getFillColor,
        getLineColor: config.getLineColor,
        getLineWidth: config.getLineWidth,
        getPointRadius: config.getPointRadius,
        pointRadiusMinPixels: config.pointRadiusMinPixels,
        lineWidthMinPixels: config.lineWidthMinPixels,
      });
    }));

    new deck.DeckGL({
      container: document.body,
      mapStyle: '{{ basemap_style }}',
      initialViewState: {{ view_state_json }},
      controller: true,
      layers: layers,
    });
  }
  initMap();
</script>
</body>
</html>
```

### 1.4 HTML Generator (`html_generator.py`)

```python
def generate_html(project, output_path):
    """Generate a deck.gl HTML file from the current QGIS project."""
    canvas = iface.mapCanvas()
    carto_layers = [l for l in project.mapLayers().values()
                    if isinstance(l, QgsVectorLayer) and is_carto_layer(l)]

    # 1. Create scoped token
    access_token = create_export_token(carto_layers)

    # 2. Translate styles
    layer_configs = [translate_layer(l) for l in carto_layers]

    # 3. Extract view state from map canvas
    extent = canvas.extent()
    center = extent.center()
    # Transform to EPSG:4326
    view_state = {
        "longitude": center.x(),
        "latitude": center.y(),
        "zoom": estimate_zoom(extent),
    }

    # 4. Render template
    html = render_template(
        title=project.title() or "CARTO Map",
        api_base_url=CARTO_API.base_url,
        access_token=access_token,
        layers_json=json.dumps(layer_configs),
        view_state_json=json.dumps(view_state),
        basemap_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
    )

    with open(output_path, "w") as f:
        f.write(html)
```

### 1.5 Menu Integration (`plugin.py`)

Add an "Export to deck.gl" action to the existing CARTO plugin menu:

```python
# In CartoPlugin.initGui():
self.export_action = QAction("Export to deck.gl HTML...", self.iface.mainWindow())
self.export_action.triggered.connect(self.export_deckgl)
self.carto_menu.addAction(self.export_action)

# New method:
def export_deckgl(self):
    if not CARTO_API.is_logged_in():
        iface.messageBar().pushMessage("Please log in to CARTO first", ...)
        return
    path, _ = QFileDialog.getSaveFileName(None, "Export deck.gl HTML", "", "HTML (*.html)")
    if path:
        generate_html(QgsProject.instance(), path)
        iface.messageBar().pushMessage(f"Exported to {path}", ...)
```

### 1.6 View State Extraction

Convert QGIS map canvas extent to deck.gl `initialViewState`:

```python
def extract_view_state(canvas) -> dict:
    extent = canvas.extent()
    # Transform extent to EPSG:4326
    transform = QgsCoordinateTransform(
        canvas.mapSettings().destinationCrs(),
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance(),
    )
    extent_4326 = transform.transformBoundingBox(extent)
    center = extent_4326.center()

    # Estimate zoom from extent width
    zoom = math.log2(360 / extent_4326.width())

    return {
        "longitude": round(center.x(), 6),
        "latitude": round(center.y(), 6),
        "zoom": round(zoom, 2),
        "pitch": 0,
        "bearing": 0,
    }
```

---

## Phase 2 — Categorized & Graduated Styles

### 2.1 Categorized Renderer (`QgsCategorizedSymbolRenderer`)

Maps to deck.gl accessor functions that return different colors per category:

```javascript
// Generated JS for a categorized renderer on field "type"
getFillColor: (d) => {
  const val = d.properties.type;
  if (val === 'residential') return [65, 182, 196, 200];
  if (val === 'commercial') return [253, 141, 60, 200];
  if (val === 'industrial') return [189, 0, 38, 200];
  return [128, 128, 128, 200]; // default
}
```

### 2.2 Graduated Renderer (`QgsGraduatedSymbolRenderer`)

Maps to color ramps based on numeric ranges:

```javascript
// Generated JS for a graduated renderer on field "population"
getFillColor: (d) => {
  const val = d.properties.population;
  if (val < 1000) return [255, 255, 178, 200];
  if (val < 5000) return [254, 204, 92, 200];
  if (val < 10000) return [253, 141, 60, 200];
  if (val < 50000) return [240, 59, 32, 200];
  return [189, 0, 38, 200];
}
```

### 2.3 Legend Panel

Generate an HTML legend overlay from the renderer categories/ranges.

---

## Phase 3 — Non-CARTO Layers & Export Dialog

### 3.1 Local/non-CARTO layers

Export non-CARTO layers as inline GeoJSON embedded in the HTML, rendered with
`deck.GeoJsonLayer` instead of `deck.carto.VectorTileLayer`.

### 3.2 Export Dialog

A proper dialog with:
- Layer list with checkboxes (select which layers to export)
- Basemap selector (Positron, Dark Matter, Voyager)
- Title / description fields
- Option to open in browser after export

### 3.3 Popup / Tooltip support

Generate `getTooltip` configuration from QGIS layer display settings.

---

## Future Phases

- **Hosted publishing**: Similar to Builder published maps — host the HTML on
  CARTO infrastructure with a shareable URL. Requires CARTO backend support.
- **Rule-based renderer**: More complex conditional styling
- **Labels**: Text layers from QGIS labeling configuration
- **3D extrusion**: Translate QGIS 3D properties to deck.gl extrusion
- **Interactivity**: Click handlers, filters, widgets
- **Live data**: Auto-refresh from CARTO data sources
- **Export builder UI**: Richer configuration (deck.gl-specific settings,
  animation, arc layers, etc.)

---

## Open Questions / Decisions Made

| Question | Decision |
|---|---|
| deck.gl version | v9 via CDN (unpkg) |
| CARTO data source API | `@deck.gl/carto` CDN bundle (`vectorTableSource` + `VectorTileLayer`) |
| Auth token strategy | Create scoped API Access Token via `POST /v3/tokens` at export time |
| Basemap | CARTO basemaps via MapLibre GL (Positron default) |
| Non-CARTO layers (Phase 1) | Skip — only export CARTO layers |
| Template engine | Python `string.Template` or manual f-string (no Jinja2 dependency) |
| Additional Python deps | None for Phase 1 (use existing `requests` session) |
| CARTO CLI / carto-auth | Not needed for Phase 1; evaluate for future phases |

---

## Testing Strategy

1. **Unit tests**: Style translator (QGIS renderer → dict) with mock renderers
2. **Integration test**: Full export pipeline with a mock QGIS project
3. **Manual test**: Export a real CARTO project, open HTML in browser, verify:
   - Map renders with correct basemap
   - CARTO layers load data
   - Colors/sizes match QGIS styling
   - View state matches QGIS canvas position
   - Token works (data loads without auth errors)
