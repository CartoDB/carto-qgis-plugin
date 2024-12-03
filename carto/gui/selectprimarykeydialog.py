import os

from qgis.core import Qgis
from qgis.gui import QgsMessageBar

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QSizePolicy, QFileDialog
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices


WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "selectprimarykeydialog.ui")
)

class SelectPrimaryKeyDialog(BASE, WIDGET):
    def __init__(self, columns, parent=None):
        super(QDialog, self).__init__(parent)
        self.setupUi(self)

        # Connect buttons manually
        self.setPrimaryKeyButton.clicked.connect(self.setPrimaryKey)
        self.skipButton.clicked.connect(self.skip)
        self.helpButton.clicked.connect(self.showHelp)

        self.initGui(columns)

        self.pk = None

    def initGui(self, columns):
        self.comboPK.addItems(columns)

    def setPrimaryKey(self):
        self.pk = self.comboPK.currentText()
        self.accept()

    def skip(self):
        self.reject()

    def showHelp(self):
        QDesktopServices.openUrl(QUrl("https://docs.carto.com/qgis-plugi"))
