# CARTO QGIS Plugin

A QGIS plugin to access, visualize, and edit geospatial data in cloud data warehouses (BigQuery, Snowflake, Databricks, Redshift, PostgreSQL) via CARTO.

## Tech stack

- Python 3.12+
- QGIS API (`qgis.core`, `qgis.gui`)
- Qt via `qgis.PyQt` (not direct PyQt5/PyQt6 imports)

## Project structure

- `carto/` — plugin source (symlinked into QGIS plugins dir for development)
  - `core/` — API client, auth, connections, layer download/import, logging
  - `gui/` — Qt dialogs (.ui + Python), data provider, settings, SSO
  - `libs/` — vendored dependencies (json2html)
  - `plugin.py` — main entry point
- `helper.py` — dev tooling: install, package, publish

## Development

```sh
python helper.py install   # symlink to QGIS plugins dir
python helper.py package   # build carto.zip for distribution
```

## Code formatting

- Black (default settings, Python 3.12+ target)
- isort with `profile = black`
- flake8 with `max-line-length = 99`
