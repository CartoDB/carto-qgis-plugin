"""
Code taken from the Felt QGIS Plugin
Original code at https://github.com/felt/qgis-plugin
"""

from typing import Optional

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, pyqtSignal, QTimer, QDate
from qgis.PyQt.QtWidgets import QAction, QPushButton
from qgis.core import Qgis
from qgis.gui import QgsMessageBarItem
from qgis.utils import iface

from carto.gui.authorizedialog import AuthorizeDialog
from carto.gui.authorizationsuccessdialog import AuthorizationSuccessDialog
from carto.core.auth import OAuthWorkflow
from carto.core.enums import AuthState
from carto.core.api import CARTO_API
from carto.gui.utils import icon

AUTH_CONFIG_ID = "carto_auth_id"
AUTH_CONFIG_EXPIRY = "carto_auth_expiry"


class AuthorizationManager(QObject):
    """
    Handles the GUI component of client authorization
    """

    authorized = pyqtSignal()
    authorization_failed = pyqtSignal()
    status_changed = pyqtSignal(AuthState)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.status: AuthState = AuthState.NotAuthorized
        self._workflow: Optional[OAuthWorkflow] = None
        self.oauth_close_timer: Optional[QTimer] = None

        self._authorizing_message = None
        self._authorization_failed_message = None

        self.cancel_button_used = False

        self.queued_callbacks = []

        self.login_action = QAction(self.tr("Log In…"))
        self.login_action.setIcon(icon("carto.svg"))
        self.login_action.triggered.connect(self.login)

    def _set_status(self, status: AuthState):
        """
        Sets the current authorization status
        """
        if self.status == status:
            return

        self.status = status
        self.status_changed.emit(self.status)

        if self.status == AuthState.NotAuthorized:
            self.login_action.setText(self.tr("Log In…"))
            self.login_action.setEnabled(True)
        elif self.status == AuthState.Authorizing:
            self.login_action.setText(self.tr("Authorizing…"))
            self.login_action.setEnabled(False)
        elif self.status == AuthState.Authorized:
            self.login_action.setText(self.tr("Log Out"))
            self.login_action.setEnabled(True)

    def is_authorized(self) -> bool:
        """
        Returns True if the client is authorized
        """
        return self.status == AuthState.Authorized

    def login(self):
        """
        Called when the login action is triggered
        """
        if self.status == AuthState.NotAuthorized:
            self.attempt_authorize()
        elif self.status == AuthState.Authorized:
            self.deauthorize()

    def authorization_callback(self, callback) -> bool:
        """
        Returns True if the client is already authorized, or False
        if an authorization is in progress and the operation needs to wait
        for the authorized signal before proceeding
        """
        if self.status == AuthState.Authorized:
            callback()
            return True

        self.queued_callbacks.append(callback)
        self.attempt_authorize()
        return False

    def deauthorize(self):
        """
        Deauthorizes the client
        """
        CARTO_API.clear()
        self._set_status(AuthState.NotAuthorized)

    def attempt_authorize(self):
        self.show_authorization_dialog()

    def show_authorization_dialog(self):
        """
        Shows the authorization dialog before commencing the authorization
        process
        """
        dlg = AuthorizeDialog(iface.mainWindow())
        if dlg.exec_():
            self.start_authorization_workflow(dlg.sso_org)
        else:
            self.queued_callbacks = []

    def start_authorization_workflow(self, sso_org: str):
        """
        Start an authorization process
        """

        assert not self._workflow

        self._cleanup_messages()

        self._workflow = OAuthWorkflow(sso_org)
        self._workflow.error_occurred.connect(self._authorization_error_occurred)
        self._workflow.finished.connect(self._authorization_success)

        self._set_status(AuthState.Authorizing)

        self._authorizing_message = QgsMessageBarItem(
            self.tr("Carto"), self.tr("Authorizing…"), Qgis.MessageLevel.Info
        )

        self._authorizing_message = iface.messageBar().createMessage(
            self.tr("Carto"), self.tr("Authorizing…")
        )

        def button_clicked():
            self.cancel_button_used = True
            self._authorization_error_occurred()

        button = QPushButton(self._authorizing_message)
        button.setText("Cancel")
        button.pressed.connect(button_clicked)
        self._authorizing_message.layout().addWidget(button)
        iface.messageBar().pushWidget(self._authorizing_message, Qgis.Info)

        self._workflow.start()
        return False

    def _cleanup_messages(self):
        """
        Removes outdated message bar items
        """
        if self._authorizing_message and not sip.isdeleted(self._authorizing_message):
            iface.messageBar().popWidget(self._authorizing_message)
            self._authorizing_message = None
        if self._authorization_failed_message and not sip.isdeleted(
            self._authorization_failed_message
        ):
            iface.messageBar().popWidget(self._authorization_failed_message)
            self._authorization_failed_message = None

    def _authorization_error_occurred(self):
        """
        Triggered when an authorization error occurs
        """
        self.queued_callbacks = []
        self._cleanup_messages()

        self._clean_workflow()

        self._set_status(AuthState.NotAuthorized)
        login_error = self.tr("Authorization error")

        self._authorization_failed_message = QgsMessageBarItem(
            self.tr("Carto"), login_error, Qgis.MessageLevel.Critical
        )

        retry_button = QPushButton(self.tr("Try Again"))
        retry_button.clicked.connect(self.show_authorization_dialog)
        self._authorization_failed_message.layout().addWidget(retry_button)

        iface.messageBar().pushItem(self._authorization_failed_message)

        self.queued_callbacks = []
        self.authorization_failed.emit()

    def _authorization_success(self, token: str):
        """
        Triggered when an authorization succeeds
        """
        self._cleanup_messages()

        CARTO_API.set_token(token)
        CARTO_API.configure_endpoints()
        self._set_status(AuthState.Authorized)
        iface.messageBar().pushSuccess(self.tr("Carto"), self.tr("Authorized"))

        self._clean_workflow()

        self.authorized.emit()

        dlg = AuthorizationSuccessDialog(iface.mainWindow())
        dlg.exec_()
        if dlg.logout:
            self.deauthorize()

    def cleanup(self):
        """
        Must be called when the authorization handler needs to be gracefully
        shutdown (e.g. on plugin unload)
        """
        self._close_auth_server(force_close=True)

    def _clean_workflow(self):
        """
        Cleans up the oauth workflow
        """
        if self._workflow and not sip.isdeleted(self._workflow):
            self.oauth_close_timer = QTimer(self)
            self.oauth_close_timer.setSingleShot(True)
            self.oauth_close_timer.setInterval(1000)
            self.oauth_close_timer.timeout.connect(self._close_auth_server)
            self.oauth_close_timer.start()

    def _close_auth_server(self, force_close=False):
        """
        Gracefully closes and cleans up the oauth workflow
        """
        if self.oauth_close_timer and not sip.isdeleted(self.oauth_close_timer):
            self.oauth_close_timer.timeout.disconnect(self._close_auth_server)
            self.oauth_close_timer.deleteLater()
        self.oauth_close_timer = None

        if self._workflow and not sip.isdeleted(self._workflow):
            if force_close or self.cancel_button_used:
                self.cancel_button_used = False
                self._workflow.force_stop()

            self._workflow.close_server()
            self._workflow.quit()
            self._workflow.wait()
            self._workflow.deleteLater()

        self._workflow = None


AUTHORIZATION_MANAGER = AuthorizationManager()
