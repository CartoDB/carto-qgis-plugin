import traceback

from qgis.core import Qgis, QgsProject, QgsVectorLayer
from qgis.utils import iface

from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QComboBox,
    QLabel,
    QTextEdit,
    QDialogButtonBox,
    QFileDialog,
    QAbstractItemView,
    QCheckBox,
)
from qgis.PyQt.QtCore import Qt

from carto.core.layers import is_carto_layer
from carto.core.export.compatibility import check_layer
from carto.core.export.html_generator import generate_html, BASEMAP_STYLES
from carto.core.logging import error as log_error


STATUS_ICONS = {
    "full": "\u2713",      # checkmark
    "partial": "\u26A0",   # warning triangle
    "unsupported": "\u2717",  # cross
}

STATUS_LABELS = {
    "full": "Supported",
    "partial": "Partial",
    "unsupported": "Not supported",
}


class ExportDeckGLDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export to deck.gl HTML")
        self.setMinimumSize(620, 420)
        self.resize(680, 480)

        self.layer_reports = []  # list of (layer, report) tuples

        self._build_ui()
        self._populate_layers()

    def _build_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # --- Layer table ---
        layout.addWidget(QLabel("Layers to export:"))

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Export", "Layer", "Renderer", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.currentCellChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        # --- Warnings ---
        layout.addWidget(QLabel("Warnings:"))
        self.warnings_text = QTextEdit()
        self.warnings_text.setReadOnly(True)
        self.warnings_text.setMaximumHeight(100)
        self.warnings_text.setStyleSheet("color: #8B6914; background: #FFF8E1;")
        layout.addWidget(self.warnings_text)

        # --- Basemap ---
        basemap_layout = QHBoxLayout()
        basemap_layout.addWidget(QLabel("Basemap:"))
        self.basemap_combo = QComboBox()
        self.basemap_combo.addItem("Positron (light)", "positron")
        self.basemap_combo.addItem("Dark Matter (dark)", "dark_matter")
        self.basemap_combo.addItem("Voyager (colorful)", "voyager")
        basemap_layout.addWidget(self.basemap_combo)
        basemap_layout.addStretch()
        layout.addLayout(basemap_layout)

        # --- Buttons ---
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Cancel
        )
        self.export_btn = self.button_box.addButton(
            "Export...", QDialogButtonBox.AcceptRole
        )
        self.export_btn.setDefault(True)
        self.button_box.accepted.connect(self._on_export)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _populate_layers(self):
        project = QgsProject.instance()
        carto_layers = []
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not is_carto_layer(layer):
                continue
            if not layer.isValid():
                continue
            carto_layers.append(layer)

        self.table.setRowCount(len(carto_layers))
        self.layer_reports = []

        all_warnings = []

        for row, layer in enumerate(carto_layers):
            report = check_layer(layer)
            self.layer_reports.append((layer, report))

            # Checkbox
            checkbox = QCheckBox()
            enabled = report["status"] != "unsupported"
            checkbox.setChecked(enabled)
            checkbox.setEnabled(enabled)
            checkbox_layout = QHBoxLayout()
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.setAlignment(Qt.AlignCenter)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            from qgis.PyQt.QtWidgets import QWidget
            checkbox_container = QWidget()
            checkbox_container.setLayout(checkbox_layout)
            self.table.setCellWidget(row, 0, checkbox_container)

            # Layer name
            name_item = QTableWidgetItem(report["layer_name"])
            if not enabled:
                name_item.setForeground(Qt.gray)
            self.table.setItem(row, 1, name_item)

            # Renderer type
            renderer_item = QTableWidgetItem(report["renderer_label"])
            if not enabled:
                renderer_item.setForeground(Qt.gray)
            self.table.setItem(row, 2, renderer_item)

            # Status
            icon = STATUS_ICONS.get(report["status"], "?")
            label = STATUS_LABELS.get(report["status"], "?")
            status_item = QTableWidgetItem(f"{icon} {label}")
            if report["status"] == "unsupported":
                status_item.setForeground(Qt.red)
            elif report["status"] == "partial":
                status_item.setForeground(Qt.darkYellow)
            self.table.setItem(row, 3, status_item)

            # Collect warnings
            for w in report["warnings"]:
                all_warnings.append(f"{report['layer_name']}: {w}")

        if all_warnings:
            self.warnings_text.setPlainText("\n".join(all_warnings))
        else:
            self.warnings_text.setPlainText("No warnings — all layers fully supported.")
            self.warnings_text.setStyleSheet("color: #2E7D32; background: #E8F5E9;")

        if not carto_layers:
            self.warnings_text.setPlainText("No CARTO layers found in the project.")
            self.warnings_text.setStyleSheet("color: #C62828; background: #FFEBEE;")
            self.export_btn.setEnabled(False)

    def _on_selection_changed(self, row, col, prev_row, prev_col):
        if row < 0 or row >= len(self.layer_reports):
            return
        _, report = self.layer_reports[row]
        if report["warnings"]:
            self.warnings_text.setPlainText(
                "\n".join(f"- {w}" for w in report["warnings"])
            )
        else:
            self.warnings_text.setPlainText("No warnings for this layer.")

    def _get_selected_layers(self):
        selected = []
        for row, (layer, report) in enumerate(self.layer_reports):
            container = self.table.cellWidget(row, 0)
            checkbox = container.findChild(QCheckBox)
            if checkbox and checkbox.isChecked():
                selected.append(layer)
        return selected

    def _on_export(self):
        selected_layers = self._get_selected_layers()
        if not selected_layers:
            iface.messageBar().pushMessage(
                "CARTO", "No layers selected for export.",
                level=Qgis.Warning, duration=5,
            )
            return

        basemap = self.basemap_combo.currentData()

        path, _ = QFileDialog.getSaveFileName(
            self, "Save deck.gl HTML", "", "HTML Files (*.html)"
        )
        if not path:
            return

        try:
            success = generate_html(
                iface.mapCanvas(), path,
                basemap=basemap,
                layers=selected_layers,
            )
            if success:
                iface.messageBar().pushMessage(
                    "CARTO", f"Map exported to {path}",
                    level=Qgis.Success, duration=5,
                )
                self.accept()
            else:
                iface.messageBar().pushMessage(
                    "CARTO",
                    "Export failed. Check View > Log Messages > CARTO tab.",
                    level=Qgis.Critical, duration=10,
                )
        except Exception as e:
            tb = traceback.format_exc()
            log_error(f"deck.gl export error: {tb}")
            iface.messageBar().pushMessage(
                "CARTO", f"Export error: {e}",
                level=Qgis.Critical, duration=10,
            )
