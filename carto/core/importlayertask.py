import traceback
from collections import defaultdict

from qgis.core import (
    Qgis,
    QgsMessageLog,
    QgsTask,
)

from carto.core.utils import (
    provider_data_type_from_qgis_type,
    quote_for_provider,
    prepare_geo_value_for_provider,
    prepare_multipart_sql,
)
from carto.core.api import CartoApi

from qgis.PyQt.QtCore import QVariant


class ImportLayerTask(QgsTask):
    def __init__(
        self,
        connection_name,
        provider_type,
        fqn,
        layer,
    ):
        super().__init__(f"Importing layer to {fqn}", QgsTask.CanCancel)
        self.exception = None
        self.fqn = fqn
        self.layer = layer
        self.connection_name = connection_name
        self.provider_type = provider_type

    def run(self):
        try:
            fqn = quote_for_provider(self.fqn, self.provider_type)
            sql_create = f"CREATE OR REPLACE TABLE {self.fqn} (\n"
            field_definitions = []

            for field in self.layer.fields():
                provider_data_type = provider_data_type_from_qgis_type(
                    field.type(), self.provider_type
                )
                field_definitions.append(f"  {field.name()} {provider_data_type}")
            geo_type = provider_data_type_from_qgis_type("geometry", self.provider_type)
            field_definitions.append(f"  geom {geo_type}")

            sql_create += ",\n".join(field_definitions) + "\n);"

            insert_statements = []

            for feature in self.layer.getFeatures():
                if self.isCanceled():
                    return False
                field_values = []
                for field in self.layer.fields():
                    value = feature[field.name()]
                    if value is None:
                        field_values.append("NULL")
                    elif field.isNumeric():
                        field_values.append(str(value))
                    elif field.type() == QVariant.Bool:
                        field_values.append("TRUE" if value else "FALSE")
                    else:
                        field_values.append(f"'{value}'")

                geom = feature.geometry()
                if geom and not geom.isEmpty():
                    field_values.append(
                        prepare_geo_value_for_provider(self.provider_type, geom)
                    )
                else:
                    field_values.append("NULL")

                insert_statement = (
                    f"INSERT INTO {fqn} VALUES (" + ", ".join(field_values) + ");"
                )
                insert_statements.append(insert_statement)

            CartoApi.instance().execute_query(self.connection_name, sql_create)
            batch_size = 10
            num_batches = len(insert_statements) // batch_size
            for i in range(num_batches):
                if self.isCanceled():
                    return False
                CartoApi.instance().execute_query_post(
                    self.connection_name,
                    prepare_multipart_sql(
                        insert_statements[i * batch_size : (i + 1) * batch_size],
                        self.provider_type,
                        self.fqn,
                    ),
                )
                self.setProgress(int(i / len(insert_statements) * 100))
            if (num_batches * batch_size) < len(insert_statements):
                CartoApi.instance().execute_query_post(
                    self.connection_name,
                    prepare_multipart_sql(
                        insert_statements[num_batches * batch_size :],
                        self.provider_type,
                        self.fqn,
                    ),
                )
            return True
        except Exception:
            self.exception = traceback.format_exc()
            return False

    def finished(self, result):
        if self.exception is not None:
            QgsMessageLog.logMessage(
                f"Could not import layer to {self.fqn}.\n{self.exception}",
                "CARTO",
                Qgis.Warning,
            )
