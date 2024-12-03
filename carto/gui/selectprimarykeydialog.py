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

        self.buttonBox.accepted.connect(self.okClicked)
        self.buttonBox.rejected.connect(self.reject)

        self.initGui(columns)

        self.pk = None

    def initGui(self, columns):
        self.comboPK.addItems(columns)

    def okClicked(self):
        self.pk = self.comboPK.currentText()
        self.accept()

    def showHelp(self):
        # Replace the URL with the documentation link
        QDesktopServices.openUrl(QUrl("https://docs.carto.com/qgis-plugi"))