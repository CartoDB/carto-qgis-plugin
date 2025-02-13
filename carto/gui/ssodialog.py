import os

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog
from qgis.PyQt.QtGui import QPixmap


WIDGET, BASE = uic.loadUiType(os.path.join(os.path.dirname(__file__), "ssodialog.ui"))

pluginPath = os.path.dirname(__file__)


def img(f):
    return QPixmap(os.path.join(pluginPath, "img", f))


class SSODialog(BASE, WIDGET):
    def __init__(self, parent=None):
        super(QDialog, self).__init__(parent)
        self.setupUi(self)

        self.btnOk.clicked.connect(self.ok_clicked)
        self.btnCancel.clicked.connect(self.cancel_clicked)

        self.sso_org = None

        pixmap = img("cartobanner.png")
        self.labelLogo.setPixmap(pixmap)
        self.labelLogo.setScaledContents(True)
        self.resize(pixmap.width(), pixmap.height())

    def ok_clicked(self):
        self.sso_org = self.txtOrg.text()
        self.accept()

    def cancel_clicked(self):
        self.reject()
