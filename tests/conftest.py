"""Test harness that stubs the QGIS and Qt APIs so `carto` imports without QGIS.

The stubs are installed unconditionally, before any `carto` import, so tests behave the
same with or without a QGIS install and never touch the network or a QGIS runtime.
"""

import enum
import sys
import types
from unittest.mock import MagicMock

import pytest


class _Null:
    def __eq__(self, other):
        return other is None or isinstance(other, _Null)

    def __hash__(self):
        return 0

    def __repr__(self):
        return "NULL"


class _MessageLevel:
    Info = "Info"
    Warning = "Warning"
    Critical = "Critical"
    Success = "Success"


class _Qgis:
    MessageLevel = _MessageLevel


class _QObject:
    def __init__(self, *args, **kwargs):
        pass

    def tr(self, text):
        return text


class _QMetaType:
    class Type(enum.Enum):
        QString = 10
        Int = 2
        LongLong = 4
        Double = 6
        Bool = 1


class _QSettings:
    def __init__(self, *args, **kwargs):
        pass

    def value(self, key, default=None, *args, **kwargs):
        return default

    def setValue(self, key, value):
        pass


class _QgsTask:
    class Flag:
        CanCancel = "CanCancel"

    def __init__(self, *args, **kwargs):
        self._canceled = False

    def isCanceled(self):
        return self._canceled

    def setProgress(self, progress):
        pass


class _UiWidget:
    pass


class _UiBase:
    def __init__(self, *args, **kwargs):
        pass


def _module(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    module.__getattr__ = lambda attr: MagicMock(name=f"{name}.{attr}")
    return module


def _install_qgis_stubs():
    core = _module(
        "qgis.core",
        NULL=_Null(),
        Qgis=_Qgis,
        QgsTask=_QgsTask,
        QgsSettings=_QSettings,
    )
    qtcore = _module(
        "qgis.PyQt.QtCore", QObject=_QObject, QSettings=_QSettings, QMetaType=_QMetaType
    )
    uic = _module("qgis.PyQt.uic", loadUiType=lambda *a, **k: (_UiWidget, _UiBase))
    pyqt = _module(
        "qgis.PyQt",
        QtCore=qtcore,
        QtWidgets=_module("qgis.PyQt.QtWidgets"),
        QtGui=_module("qgis.PyQt.QtGui"),
        QtNetwork=_module("qgis.PyQt.QtNetwork"),
        uic=uic,
    )
    modules = {
        "qgis": _module("qgis", core=core, PyQt=pyqt),
        "qgis.core": core,
        "qgis.gui": _module("qgis.gui"),
        "qgis.utils": _module("qgis.utils"),
        "qgis.PyQt": pyqt,
        "qgis.PyQt.QtCore": qtcore,
        "qgis.PyQt.QtWidgets": pyqt.QtWidgets,
        "qgis.PyQt.QtGui": pyqt.QtGui,
        "qgis.PyQt.QtNetwork": pyqt.QtNetwork,
        "qgis.PyQt.uic": uic,
    }
    sys.modules.update(modules)


_install_qgis_stubs()


class FakeWkb:
    def __init__(self, hex_string):
        self._hex = hex_string

    def toHex(self):
        return self

    def data(self):
        return self._hex.encode()


class FakeGeometry:
    def __init__(self, n_vertices=4):
        self.n_vertices = n_vertices
        coords = ", ".join(f"{i} {i}" for i in range(n_vertices))
        self._wkt = f"POLYGON(({coords}))"
        # Polygon WKB: 1 byte order + 4 type + 4 rings + 4 points + 16 bytes per vertex.
        self._hex = "01" + "03000000" + "01000000" + "00" * 4 + "ab" * 16 * n_vertices

    def asWkt(self):
        return self._wkt

    def asWkb(self):
        return FakeWkb(self._hex)

    def isEmpty(self):
        return self.n_vertices == 0


class FakeField:
    def __init__(self, name, numeric=False, field_type=_QMetaType.Type.QString):
        self._name = name
        self._numeric = numeric
        self._type = field_type

    def name(self):
        return self._name

    def isNumeric(self):
        return self._numeric

    def type(self):
        return self._type


class FakeFields:
    def __init__(self, fields):
        self._fields = list(fields)

    def at(self, idx):
        return self._fields[idx]

    def indexOf(self, name):
        for i, f in enumerate(self._fields):
            if f.name() == name:
                return i
        return -1

    def count(self):
        return len(self._fields)

    def names(self):
        return [f.name() for f in self._fields]

    def __iter__(self):
        return iter(self._fields)


class FakeFeature:
    def __init__(self, fields, attributes, geometry=None):
        self._fields = fields
        self._attributes = dict(attributes)
        self._geometry = geometry

    def __getitem__(self, name):
        return self._attributes[name]

    def fields(self):
        return self._fields

    def geometry(self):
        return self._geometry


class FakeLayer:
    def __init__(self, fields, features, layer_id="layer-1"):
        self._fields = fields
        self._features = features
        self._id = layer_id

    def id(self):
        return self._id

    def fields(self):
        return self._fields

    def getFeature(self, featureid):
        return self._features[featureid]

    def getFeatures(self):
        return iter(self._features.values())


@pytest.fixture
def fake_geom():
    return FakeGeometry


@pytest.fixture
def fake_layer():
    def build(field_specs, rows, geometries=None, layer_id="layer-1"):
        """`field_specs`: [(name, numeric)]; `rows`: {featureid: {name: value}}."""
        fields = FakeFields(FakeField(name, numeric) for name, numeric in field_specs)
        geometries = geometries or {}
        features = {
            fid: FakeFeature(fields, attrs, geometries.get(fid))
            for fid, attrs in rows.items()
        }
        return FakeLayer(fields, features, layer_id)

    return build


class UploadEnv:
    """`LayerTracker.upload_changes` with CARTO_API, iface and layer metadata replaced."""

    def __init__(self, monkeypatch, provider_type):
        from carto.core import layers

        self.layers = layers
        self.metadata = {
            "provider_type": provider_type,
            "geom_column": "geom",
            "pk": "id",
            "schema_changed": False,
            "can_write": True,
            "columns": [
                {"name": "id", "type": "integer"},
                {"name": "name", "type": "string"},
                {"name": "geom", "type": "geometry"},
            ],
        }
        self.api = MagicMock(name="CARTO_API")
        self.iface = MagicMock(name="iface")
        self.errors = []
        monkeypatch.setattr(layers, "CARTO_API", self.api)
        monkeypatch.setattr(layers, "iface", self.iface)
        monkeypatch.setattr(layers, "error", self.errors.append)
        monkeypatch.setattr(layers, "layer_metadata", lambda layer: self.metadata)
        monkeypatch.setattr(layers, "save_layer_metadata", lambda layer, md: None)
        monkeypatch.setattr(
            layers, "fqn_from_layer", lambda layer: "proj.dataset.table"
        )
        monkeypatch.setattr(layers, "connection_from_layer", lambda layer: "conn")
        monkeypatch.setattr(layers.LayerTracker, "_LayerTracker__instance", None)
        self.tracker = layers.LayerTracker.instance()

    def start(self, layer):
        changes = self.layers.Changes()
        self.tracker.layer_changes[layer.id()] = changes
        return changes

    def upload(self, layer):
        self.tracker.upload_changes(layer)

    def sent_queries(self):
        """Queries sent upstream, whichever transport `upload_changes` uses."""
        calls = (
            self.api.execute_query.call_args_list
            + self.api.execute_query_post.call_args_list
        )
        return [c.args[1] for c in calls]

    def fail_upload(self, exception):
        self.api.execute_query.side_effect = exception
        self.api.execute_query_post.side_effect = exception

    def messages(self):
        return [
            (c.args[0], c.kwargs.get("level"))
            for c in self.iface.messageBar.return_value.pushMessage.call_args_list
        ]


@pytest.fixture
def upload_env(monkeypatch):
    def build(provider_type="bigquery"):
        return UploadEnv(monkeypatch, provider_type)

    return build


@pytest.fixture
def fake_session():
    session = MagicMock(name="session")
    response = MagicMock(name="response")
    response.json.return_value = {"rows": []}
    session.get.return_value = response
    session.post.return_value = response
    return session
