import os
import warnings

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QWidget,
    QLabel,
    QLineEdit,
)
from qgis.PyQt.QtGui import QIcon

from qgis.gui import (
    QgsOptionsPageWidget,
)
from qgis.core import QgsSettings

from carto.core.utils import (
    setting,
    setSetting,
    ENABLE_LOG,
    BASEMAPS_API_KEY,
    BASEMAPS_API_KEY_URL,
)

pluginPath = os.path.split(os.path.dirname(__file__))[0]


class CartoOptionsPage(QgsOptionsPageWidget):

    def __init__(self, parent):
        super().__init__(parent)
        self.config_widget = ConfigDialog()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        layout.addWidget(self.config_widget)
        self.setObjectName("cartoOptions")

    def apply(self):
        self.config_widget.accept()

    def helpKey(self):
        return ""


class ConfigDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)

        # Create layout
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Create checkbox for enable log
        self.enable_log_checkbox = QCheckBox("Enable debug log")
        layout.addWidget(self.enable_log_checkbox)

        layout.addWidget(QLabel("Basemaps API key"))
        self.basemaps_api_key_edit = QLineEdit()
        layout.addWidget(self.basemaps_api_key_edit)
        api_key_link = QLabel(
            f'<a href="{BASEMAPS_API_KEY_URL}">Get a free CARTO basemaps API key</a>'
        )
        api_key_link.setOpenExternalLinks(True)
        layout.addWidget(api_key_link)

        # Add some spacing
        layout.addStretch()

        # Load current settings
        self.load_settings()

    def load_settings(self):
        """Load current settings into the dialog"""
        self.enable_log_checkbox.setChecked(setting(ENABLE_LOG))
        self.basemaps_api_key_edit.setText(setting(BASEMAPS_API_KEY) or "")

    def save_settings(self):
        """Save settings from the dialog"""
        setSetting(ENABLE_LOG, self.enable_log_checkbox.isChecked())
        setSetting(BASEMAPS_API_KEY, self.basemaps_api_key_edit.text().strip())

    def accept(self):
        """Called when OK is clicked"""
        self.save_settings()
        super().accept()
