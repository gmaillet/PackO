# coding: utf-8
""" This script handles QGIS layers """

from qgis.core import QgsRasterLayer, QgsVectorLayer, QgsVectorFileWriter


def add_layer_to_map(data_source, layer_name, qgs_project, provider_name, is_raster=True):
    """ add layer to map """
    layer = QgsRasterLayer(data_source, layer_name, provider_name) if is_raster\
        else QgsVectorLayer(data_source, layer_name, provider_name)
    if not layer or not layer.isValid():
        raise SystemExit(f"ERROR: Layer '{layer_name}' failed to load! - "
                         f'{layer.error().summary()}')
    qgs_project.addMapLayer(layer)
    return layer


def create_vector(vector_filename, fields, geom_type, crs, qgs_project, driver_name='GPKG'):
    """ create vector """
    transform_context = qgs_project.transformContext()
    save_options = QgsVectorFileWriter.SaveVectorOptions()
    save_options.driverName = driver_name
    save_options.fileEncoding = "UTF-8"
    wrt = QgsVectorFileWriter.create(vector_filename,
                                     fields,
                                     geom_type,
                                     crs,
                                     transform_context,
                                     save_options)
    if wrt.hasError() != QgsVectorFileWriter.NoError:
        raise SystemExit(f"ERROR when creating vector '{vector_filename}': {wrt.errorMessage()}")
    # flush to disk
    del wrt
