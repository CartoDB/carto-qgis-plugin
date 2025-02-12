import os

import requests
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QInputDialog, QMessageBox
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices, QPixmap


WIDGET, BASE = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "authorizedialog.ui")
)

SIGNUP_URL = "https://carto.com/signup"

pluginPath = os.path.dirname(__file__)


def img(f):
    return QPixmap(os.path.join(pluginPath, "img", f))


class AuthorizeDialog(BASE, WIDGET):
    def __init__(self, parent=None):
        super(QDialog, self).__init__(parent)
        self.setupUi(self)

        self.btnLogin.clicked.connect(self.accept)
        self.btnSignup.clicked.connect(self.signup)
        self.btnLoginSSO.clicked.connect(self.login_sso)

        pixmap = img("cartobanner.png")
        self.labelLogo.setPixmap(pixmap)
        self.labelLogo.setScaledContents(True)
        self.resize(pixmap.width(), pixmap.height())

    def login_sso(self):
        name, done = QInputDialog.getText(
            self, "Login with SSO", "Enter your organization name:"
        )
        if done:
            response = requests.get(
                f"https://accounts.app.carto.com/accounts/{name}/auth0_org_id"
            )
            orgid = response.json()["auth0orgId"]
            if orgid:
                self.sso_org = orgid
                self.accept()
            else:
                QMessageBox.warning(
                    self, "Invalid organization", "Invalid organization name"
                )

    def signup(self):
        QDesktopServices.openUrl(QUrl(SIGNUP_URL))
