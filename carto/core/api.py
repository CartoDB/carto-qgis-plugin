try:
    from urllib.parse import urljoin
except ImportError:
    from urlparse import urljoin
import requests
import uuid
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtWidgets import QDialog
from qgis.utils import iface
from qgis.core import Qgis
from carto.core.utils import (
    setting,
    TOKEN,
)
import os
import yaml

USER_URL = "https://accounts.app.carto.com/users/me"


class CartoApi(QObject):

    token = None
    workspace_url = None
    base_url = None

    def __init__(self):
        super().__init__()

    def set_token(self, token):
        self.token = token

    def configure_endpoints(self):
        user = self.user().json()
        print(user)

        # tenant = user["user_metadata"]["tenant_domain"]
        urls_url = f"https://{tenant}/config.yaml"
        response = self.get(urls_url, verify=False)
        response.raise_for_status()
        config_content = yaml.safe_load(response.text)
        self.workspace_url = config_content["apis"]["workspaceUrl"]
        self.base_url = config_content["apis"]["baseUrl"]

    def user(self):
        return self.get(USER_URL)

    def is_logged_in(self):
        return self.token is not None

    def get(self, endpoint, params=None, verify=True):
        _params = {}
        if params:
            _params = {k: v for k, v in params.items() if v is not None}
        _params["client"] = "carto-qgis-plugin"
        url = urljoin(self.workspace_url, endpoint)
        if verify == False:
            with requests.packages.urllib3.warnings.catch_warnings():
                requests.packages.urllib3.disable_warnings(
                    requests.packages.urllib3.exceptions.InsecureRequestWarning
                )
                response = requests.get(
                    url,
                    headers={"Authorization": f"Bearer {self.token}"},
                    params=_params,
                    verify=verify,
                )
        else:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {self.token}"},
                params=_params,
            )
        return response

    def get_json(self, endpoint, params=None):
        response = self.get(endpoint, params)
        response.raise_for_status()
        return response.json()

    def execute_query(self, connectionname, query):
        url = urljoin(self.base_url, f"v3/sql/{connectionname}/query")
        query = f"""
        -- {uuid.uuid4()}
        {query}
        """
        response = self.get(
            url,
            params={"q": query},
        )
        response.raise_for_status()
        _json = response.json()
        return _json

    def execute_query_post(self, connectionname, query):
        url = urljoin(self.base_url, f"v3/sql/{connectionname}/query")
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.token}"},
            data={"q": query},
        )
        response.raise_for_status()
        _json = response.json()
        return _json

    def connections(self):
        try:
            connections = self.get_json("connections")
            return [
                {
                    "id": connection["id"],
                    "name": connection["name"],
                    "provider_type": connection["provider_id"],
                }
                for connection in connections
            ]
        except Exception as e:
            return []

    def databases(self, connectionid):
        databases = self.get_json(f"connections/{connectionid}/resources")["children"]
        return [
            {"id": database["id"].split(".")[-1], "name": database["name"]}
            for database in databases
        ]

    def schemas(self, connectionid, databaseid):
        schemas = self.get_json(f"connections/{connectionid}/resources/{databaseid}")[
            "children"
        ]
        return [
            {"id": schema["id"].split(".")[-1], "name": schema["name"]}
            for schema in schemas
        ]

    def tables(self, connectionid, databaseid, schemaid):
        tables = self.get_json(
            f"connections/{connectionid}/resources/{databaseid}.{schemaid}"
        )["children"]
        return [
            {"id": table["id"].split(".")[-1], "name": table["name"], "size": 0}
            for table in tables
            if table["type"] == "table"
        ]

    def table_info(self, connectionid, databaseid, schemaid, tableid):
        return self.get_json(
            f"connections/{connectionid}/resources/{databaseid}.{schemaid}.{tableid}"
        )


CARTO_API = CartoApi()
