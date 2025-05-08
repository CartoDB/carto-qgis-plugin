import uuid
import requests
import shutil
from carto.gui.utils import waitcursor

from qgis.PyQt.QtCore import QSettings, QVariant
from qgis.core import NULL, QgsMessageLog, Qgis, QgsAuthMethodConfig, QgsApplication

NAMESPACE = "carto"
TOKEN = "token"

MAX_ROWS = 1000000

setting_types = {}


def setSetting(name, value):
    QSettings().setValue(f"{NAMESPACE}/{name}", value)


def setting(name):
    v = QSettings().value(f"{NAMESPACE}/{name}", None)
    if setting_types.get(name, str) == bool:
        return str(v).lower() == str(True).lower()
    else:
        return v


@waitcursor
def download_file(url, filename):
    with requests.get(url, stream=True) as r:
        with open(filename, "wb") as f:
            shutil.copyfileobj(r.raw, f)


def quote_for_provider(value, provider_type):
    if provider_type == "bigquery":
        return f"`{value}`"
    elif provider_type in ["postgres", "redshift"]:
        parts = value.split(".")
        if len(parts) == 3:
            return f""""{parts[0].replace('"', '')}".{parts[1]}.{parts[2]}"""
        else:
            return value
    elif provider_type == "databricksRest":
        return ".".join([f"`{v.replace('`', '')}`" for v in value.split(".")])
    return value


def quote_column_name_for_provider(value, provider_type):
    if provider_type in ["databricksRest", "bigquery"]:
        return f"`{value}`"
    elif provider_type in ["postgres", "redshift", "snowflake"]:
        return f'"{value}"'
    else:
        return value


def prepare_multipart_sql(statements, provider, fqn):
    joined = "\n".join(statements)
    if provider == "redshift":
        schema_path = ".".join(fqn.split(".")[:2])
        proc_name = f"{schema_path}.carto_{uuid.uuid4().hex}"
        return [
            f"""
            CREATE OR REPLACE PROCEDURE {proc_name}()
                AS $$
                BEGIN
                {joined}
                END;
                $$ LANGUAGE plpgsql;
            """,
            f"CALL {proc_name}();",
            f"DROP PROCEDURE {proc_name}();",
        ]
    elif provider == "postgres":
        return [
            f"""
            DO $$
            BEGIN
                {joined}
            END;
            $$;
            """,
        ]
    elif provider == "databricksRest":
        return [joined]
    else:
        return [
            f"""
            BEGIN
                {joined}
            END;
            """
        ]


def provider_data_type_from_qgis_type(qgis_type, provider):
    provider = provider.lower()

    type_mapping = {
        "bigquery": {
            QVariant.String: "STRING",
            "text": "STRING",
            QVariant.Int: "INT64",
            QVariant.LongLong: "INT64",
            QVariant.Double: "FLOAT64",
            QVariant.Bool: "BOOL",
            "geometry": "GEOGRAPHY",
        },
        "snowflake": {
            QVariant.String: "VARCHAR",
            QVariant.Int: "NUMBER(38,0)",
            QVariant.LongLong: "NUMBER(38,0)",
            QVariant.Double: "FLOAT",
            QVariant.Bool: "BOOL",
            "geometry": "GEOGRAPHY",
        },
        "redshift": {
            QVariant.String: "VARCHAR(MAX)",
            QVariant.Int: "BIGINT",
            QVariant.LongLong: "BIGINT",
            QVariant.Double: "DOUBLE PRECISION",
            QVariant.Bool: "BOOLEAN",
            "geometry": "GEOMETRY",
        },
        "postgres": {
            QVariant.String: "TEXT",
            QVariant.Int: "INTEGER",
            QVariant.LongLong: "BIGINT",
            QVariant.Double: "DOUBLE PRECISION",
            QVariant.Bool: "BOOLEAN",
            "geometry": "GEOMETRY",
        },
        "databricksRest": {
            QVariant.String: "VARCHAR",
            QVariant.Int: "BIGINT",
            QVariant.LongLong: "BIGINT",
            QVariant.Double: "DOUBLE",
            QVariant.Bool: "BOOLEAN",
            "geometry": "STRING",
        },
    }

    mapping = type_mapping.get(provider)

    if not mapping:
        raise ValueError(f"Unsupported provider: {provider}")

    db_type = mapping.get(qgis_type, "STRING")
    return db_type


def prepare_geo_value_for_provider(provider_type, geom):
    if provider_type == "databricksRest":
        return f"'{geom.asWkt()}'"
    else:
        wkb = geom.asWkb().toHex().data().decode()
        if provider_type == "bigquery":
            return f"ST_GEOGFROMWKB('{wkb}')"
        elif provider_type == "snowflake":
            return f"'{wkb}'"
        elif provider_type == "redshift":
            return f"ST_GEOMFROMWKB('{wkb}')"
        else:
            return f"ST_GEOMFROMWKB(DECODE('{wkb}', 'hex'))"


def is_integer_num(n):
    if isinstance(n, int):
        return True
    if isinstance(n, float):
        return n.is_integer()
    return False


def prepare_num_string(n):
    if is_integer_num(n):
        return str(int(n))
    return str(n)


def prepare_attribute_string(value, isNumeric):
    if value == NULL:
        return "NULL"
    if isNumeric:
        return prepare_num_string(value)
    else:
        return f"'{value}'"


def set_proxy_values(session):
    settings = QSettings()
    proxyEnabled = settings.value("proxy/proxyEnabled")
    if proxyEnabled:
        proxyType = settings.value("proxy/proxyType")
        if proxyType != "HttpProxy":
            QgsMessageLog.logMessage(
                "Carto: Only HttpProxy is supported " "for connecting to the Carto API",
                level=Qgis.Warning,
            )
            return

        proxyHost = settings.value("proxy/proxyHost")
        proxyPort = settings.value("proxy/proxyPort")
        url = f"{proxyHost}:{proxyPort}"
        authid = settings.value("proxy/authcfg", "")
        if authid:
            authConfig = QgsAuthMethodConfig()
            QgsApplication.authManager().loadAuthenticationConfig(
                authid, authConfig, True
            )
            username = authConfig.config("username")
            password = authConfig.config("password")
        else:
            username = settings.value("proxy/proxyUser")
            password = settings.value("proxy/proxyPassword")

        if username:
            tokens = url.split("://")
            url = f"{tokens[0]}://{username}:{password}@{tokens[-1]}"

        session.proxies["http"] = url
        session.proxies["https"] = url
    else:
        session.proxies = {}
