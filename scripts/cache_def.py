# coding: utf-8
"""This script contains all functions for the creation and update of a cache"""

from pathlib import Path, PurePosixPath
from random import randrange
import os
import math
import glob
import time
import numpy as np
from numpy import base_repr
from osgeo import gdal,ogr

# enable gdal/ogr exceptions
gdal.UseExceptions()

COG_DRIVER = gdal.GetDriverByName('COG')


def get_tile_limits(filename):
    """Return tms limits for a georef image at a given level"""
    src_image = gdal.Open(filename)
    geo_trans = src_image.GetGeoTransform()
    ul_x = geo_trans[0]
    ul_y = geo_trans[3]
    x_dist = geo_trans[1]
    y_dist = geo_trans[5]
    lr_x = ul_x + src_image.RasterXSize * x_dist
    lr_y = ul_y + src_image.RasterYSize * y_dist

    tile_limits = {}
    tile_limits['LowerCorner'] = [ul_x, lr_y]
    tile_limits['UpperCorner'] = [lr_x, ul_y]

    return tile_limits


def get_slabdepth(slab_size):
    """Get the number of levels per COG"""
    slab_size = min(slab_size['width'], slab_size['height'])
    return math.floor(math.log(slab_size, 2)) + 1


def get_slabbox(filename, overviews):
    """Get the Min/MaxTileRow/Col at all levels"""
    nb_level_cog = get_slabdepth(overviews['slabSize'])
    slabbox = {}
    tile_limits = get_tile_limits(filename)

    for slab_z in range(overviews['dataSet']['level']['min'],
                        overviews['dataSet']['level']['max'] + 1):
        resolution = overviews['resolution'] * 2 ** (overviews['level']['max'] - slab_z)

        if slab_z % nb_level_cog == overviews['dataSet']['level']['max'] % nb_level_cog:

            min_slab_col = math.floor(round((tile_limits['LowerCorner'][0] -
                                             overviews['crs']['boundingBox']['xmin'])
                                            / (resolution * overviews['tileSize']['width']
                                               * overviews['slabSize']['width']), 8))
            min_slab_row = math.floor(round((overviews['crs']['boundingBox']['ymax'] -
                                             tile_limits['UpperCorner'][1])
                                            / (resolution * overviews['tileSize']['height']
                                               * overviews['slabSize']['height']), 8))
            max_slab_col = math.ceil(round((tile_limits['UpperCorner'][0] -
                                            overviews['crs']['boundingBox']['xmin'])
                                           / (resolution * overviews['tileSize']['width']
                                              * overviews['slabSize']['width']), 8)) - 1
            max_slab_row = math.ceil(round((overviews['crs']['boundingBox']['ymax'] -
                                            tile_limits['LowerCorner'][1])
                                           / (resolution * overviews['tileSize']['height']
                                              * overviews['slabSize']['height']), 8)) - 1

            slabbox_z = {
                'MinSlabCol': min_slab_col,
                'MinSlabRow': min_slab_row,
                'MaxSlabCol': max_slab_col,
                'MaxSlabRow': max_slab_row
            }
            slabbox[str(slab_z)] = slabbox_z
    return slabbox


def set_limits(tile_limits, overviews):
    """Get the Min/MaxTileRow/Col at all levels"""
    nb_level_cog = get_slabdepth(overviews['slabSize'])
    overviews['dataSet']['boundingBox'] = tile_limits
    
    for slab_z in range(overviews['dataSet']['level']['min'],
                        overviews['dataSet']['level']['max'] + 1):
        resolution = overviews['resolution'] * 2 ** (overviews['level']['max'] - slab_z)

        min_tile_col = math.floor(round((tile_limits['LowerCorner'][0] -
                                         overviews['crs']['boundingBox']['xmin'])
                                        / (resolution * overviews['tileSize']['width']), 8))
        min_tile_row = math.floor(round((overviews['crs']['boundingBox']['ymax'] -
                                         tile_limits['UpperCorner'][1])
                                        / (resolution * overviews['tileSize']['height']), 8))
        max_tile_col = math.ceil(round((tile_limits['UpperCorner'][0] -
                                        overviews['crs']['boundingBox']['xmin'])
                                       / (resolution * overviews['tileSize']['width']), 8)) - 1
        max_tile_row = math.ceil(round((overviews['crs']['boundingBox']['ymax'] -
                                        tile_limits['LowerCorner'][1])
                                       / (resolution * overviews['tileSize']['height']), 8)) - 1

        overviews['dataSet']['limits'][str(slab_z)] = {
            'MinTileCol': min_tile_col,
            'MinTileRow': min_tile_row,
            'MaxTileCol': max_tile_col,
            'MaxTileRow': max_tile_row,
        }

        if slab_z % nb_level_cog == overviews['dataSet']['level']['max'] % nb_level_cog:

            min_slab_col = math.floor(round((tile_limits['LowerCorner'][0] -
                                             overviews['crs']['boundingBox']['xmin'])
                                            / (resolution * overviews['tileSize']['width']
                                               * overviews['slabSize']['width']), 8))
            min_slab_row = math.floor(round((overviews['crs']['boundingBox']['ymax'] -
                                             tile_limits['UpperCorner'][1])
                                            / (resolution * overviews['tileSize']['height']
                                               * overviews['slabSize']['height']), 8))
            max_slab_col = math.ceil(round((tile_limits['UpperCorner'][0] -
                                            overviews['crs']['boundingBox']['xmin'])
                                           / (resolution * overviews['tileSize']['width']
                                              * overviews['slabSize']['width']), 8)) - 1
            max_slab_row = math.ceil(round((overviews['crs']['boundingBox']['ymax'] -
                                            tile_limits['LowerCorner'][1])
                                           / (resolution * overviews['tileSize']['height']
                                              * overviews['slabSize']['height']), 8)) - 1

            overviews['dataSet']['slabLimits'][str(slab_z)] = {
                'MinSlabCol': min_slab_col,
                'MinSlabRow': min_slab_row,
                'MaxSlabCol': max_slab_col,
                'MaxSlabRow': max_slab_row
            }


def new_color(image, color_dict):
    """Choose a new color [R,G,B] for an image"""
    """
    the relation color <-> image will be saved in 2 different files :
    - a dictionnary at 3 level ("R"/"G"/"B") to find the OPI name based on the 3 colors in string
        (variable color_dict saved in cache_mtd.json)
    - a dictionnary at 1 level to find the int array of colors [R,G,B] based on the OPI name
        (color saved in overviews.json under "list_OPI")
    """
    color_str = [str(randrange(255)), str(randrange(255)), str(randrange(255))]
    while (color_str[0] in color_dict)\
            and (color_str[1] in color_dict[color_str[0]])\
            and (color_str[2] in color_dict[color_str[0]][color_str[1]]):
        color_str = [str(randrange(255)), str(randrange(255)), str(randrange(255))]
    if color_str[0] not in color_dict:
        color_dict[color_str[0]] = {}
    if color_str[1] not in color_dict[color_str[0]]:
        color_dict[color_str[0]][color_str[1]] = {}

    color_dict[color_str[0]][color_str[1]][color_str[2]] = image
    return [int(color_str[0]), int(color_str[1]), int(color_str[2])]


def get_slab_path(slab_x, slab_y, path_depth):
    """Calcul du chemin en base 36 avec la bonne profondeur"""
    str_x = base_repr(slab_x, 36).zfill(path_depth+1)
    str_y = base_repr(slab_y, 36).zfill(path_depth+1)
    slab_path = ''
    for i in range(path_depth+1):
        if i!=0:
            slab_path += '/'
        slab_path += str_x[i] + str_y[i]
    return slab_path


def assert_square(obj):
    """Verify that obj is square"""
    if obj['width'] != obj['height']:
        raise ValueError("Object is not square!")


def display_bar(current, nb_total, width=50):
    if not nb_total > 0:
        return
    width_per_step = width/nb_total
    width_done = int(current*width_per_step)
    print("\r |" + width_done*'#' + (width-width_done)*'-'+'|', end="", flush=True)
    if current == nb_total:
        print()


def create_blank_slab(overviews, slab, nb_bands, spatial_ref):
    """Return a blank georef image for a slab"""
    origin_x = overviews['crs']['boundingBox']['xmin']\
        + slab['x'] * slab['resolution']\
        * overviews['tileSize']['width']\
        * overviews['slabSize']['width']
    origin_y = overviews['crs']['boundingBox']['ymax']\
        - slab['y'] * slab['resolution']\
        * overviews['tileSize']['height']\
        * overviews['slabSize']['height']
    target_ds = gdal.GetDriverByName('MEM').Create('',
                                                   overviews['tileSize']['width']
                                                   * overviews['slabSize']['width'],
                                                   overviews['tileSize']['height']
                                                   * overviews['slabSize']['height'],
                                                   nb_bands,
                                                   gdal.GDT_Byte)
    target_ds.SetGeoTransform((origin_x, slab['resolution'], 0,
                               origin_y, 0, -slab['resolution']))
    target_ds.SetProjection(spatial_ref)
    target_ds.FlushCache()
    return target_ds


def update_ortho(filename, mask, ortho, nb_bands):
    """Apply mask"""
    opi = gdal.Open(filename)
    for i in range(nb_bands):
        opi_i = opi.GetRasterBand(i + 1).ReadAsArray()
        opi_i[(mask == 0)] = 0
        ortho_i = ortho.GetRasterBand(i + 1).ReadAsArray()
        ortho_i[(mask != 0)] = 0
        ortho.GetRasterBand(i + 1).WriteArray(np.add(opi_i, ortho_i))


def create_graph_1arg(arg):
    """Create graph on a specified slab"""
    # print(arg)
    overviews = arg['overviews']

    # on cree le graphe
    img_graph = create_blank_slab(overviews, arg['slab'],
                                  3, arg['gdalOption']['spatialRef'])

    slab_path = get_slab_path(arg['slab']['x'], arg['slab']['y'], overviews['pathDepth'])
    slab_graph = arg['cache'] + '/graph/' + str(arg['slab']['level']) + '/' + slab_path + '.tif'
    print(slab_graph)
    print(PurePosixPath(slab_graph))
    is_empty = True

    # il faut selectionner la liste des images dans le slab
    db_graph = gdal.OpenEx(arg['dbOption']['connString'], gdal.OF_VECTOR)
    # la bbox
    xmin = overviews['crs']['boundingBox']['xmin']\
        + arg['slab']['x'] * arg['slab']['resolution']\
        * overviews['tileSize']['width']\
        * overviews['slabSize']['width']
    ymax = overviews['crs']['boundingBox']['ymax']\
        - arg['slab']['y'] * arg['slab']['resolution']\
        * overviews['tileSize']['height']\
        * overviews['slabSize']['height']
    dx = overviews['tileSize']['width'] * overviews['slabSize']['width'] * arg['slab']['resolution']
    dy = overviews['tileSize']['height'] * overviews['slabSize']['height'] * arg['slab']['resolution']
    
    # Appliquer le filtre spatial
    graph_layer = db_graph.GetLayer(arg['dbOption']['table'])
    # graph_layer.SetSpatialFilter(bbox_geom)
    graph_layer.SetSpatialFilterRect(xmin, ymax-dy,xmin+dx,ymax)
    geom_name = graph_layer.GetGeometryColumn()

    # Parcourir les features filtrées
    for feature in graph_layer:
        cliche = feature.GetField('cliche')
        color = overviews["list_OPI"][cliche]["color"]
        # print(cliche, color)
        # on cree une image mono canal pour la tuile
        mask = create_blank_slab(overviews, arg['slab'], 1, arg['gdalOption']['spatialRef'])
        gdal.Rasterize(mask,
                        db_graph,
                        SQLStatement=f'select {geom_name} from '
                        + arg['dbOption']['table']
                        + ' where cliche like \'%' + cliche + '%\'')
        img_mask = mask.GetRasterBand(1).ReadAsArray()
        # si mask est vide, on ne fait rien
        val_max = np.amax(img_mask)
        if val_max > 0:
            is_empty = False
            for i in range(3):
                graph_i = img_graph.GetRasterBand(i + 1).ReadAsArray()
                graph_i[(img_mask != 0)] = color[i]
                img_graph.GetRasterBand(i + 1).WriteArray(graph_i)

    if not is_empty:
        # si necessaire on cree les dossiers de tuile pour le graph
        Path(slab_graph).parent.mkdir(parents=True, exist_ok=True)
        # pylint: disable=unused-variable
        assert_square(overviews['tileSize'])
        print("create copy ", slab_graph)
        dst_graph = COG_DRIVER.CreateCopy(slab_graph, img_graph,
                                          options=["BLOCKSIZE="
                                                   + str(overviews['tileSize']['width']),
                                                   "COMPRESS=LZW",
                                                   "RESAMPLING=NEAREST",
                                                   "PREDICTOR=YES"])

        dst_graph = None  # noqa: F841
        # pylint: enable=unused-variable
    img_graph = None


def create_ortho_1arg(arg):
    """Create ortho on a specified slab"""
    # print(arg)
    overviews = arg['overviews']

    # on cree l'ortho
    first_opi = list(overviews["list_OPI"].values())[0]
    with_rgb = first_opi['with_rgb']
    with_ir = first_opi['with_ir']
    img_ortho_rgb = None
    if with_rgb:
        img_ortho_rgb = create_blank_slab(overviews, arg['slab'],
                                          3, arg['gdalOption']['spatialRef'])
    img_ortho_ir = None
    if with_ir:
        img_ortho_ir = create_blank_slab(overviews, arg['slab'],
                                         1, arg['gdalOption']['spatialRef'])

    slab_path = get_slab_path(arg['slab']['x'], arg['slab']['y'], overviews['pathDepth'])
    slab_opi_root = arg['cache'] + '/opi/' + str(arg['slab']['level']) + '/' + slab_path
    slab_ortho_rgb = arg['cache'] + '/ortho/' + str(arg['slab']['level']) + '/' + slab_path + '.tif'
    slab_ortho_ir = arg['cache'] + '/ortho/' + str(arg['slab']['level']) + '/' + slab_path + 'i.tif'
    slab_graph = arg['cache'] + '/graph/' + str(arg['slab']['level']) + '/' + slab_path + '.tif'
    # slab_graph = Path(arg['cache'])/'graph'/str(arg['slab']['level'])/slab_path.with_suffix('.tif')
    is_empty = True

    
    # si la tuile de graphe n'existe pas, on passe
    if not os.path.exists(slab_graph):
        print('la tuile de graph n existe pas')
        return
    
    # on lit le graph de la tuile
    graph = gdal.Open(slab_graph)
    graph_img = graph.ReadAsArray()
    graph = None

    # on selectionne la liste des OPI dispo
    # todo: on pourrait filtrer la liste des OPI à mettre à jour
    for filename in glob.glob(slab_opi_root + '*.tif'):
        print(filename)
        stem = Path(filename).stem[3:]
        print(stem)
        if stem in overviews["list_OPI"]:
            color = overviews["list_OPI"][stem]["color"]
            # preparation du masque
            mask = np.logical_and(graph_img[0] == color[0], np.logical_and(graph_img[1] == color[1], graph_img[2] == color[2]))
            val_max = np.amax(mask)
            print(val_max)
            if val_max == 0:
                continue
            is_empty = False
            filename_rgb = filename
            filename_ir = None
            if not with_rgb:
                filename_ir = filename
                filename_rgb = None
            if with_ir:
                filename_ir = os.path.join(os.path.dirname(filename),
                                           os.path.basename(filename.replace('x', '_ix')))
            if with_rgb:
                opi = gdal.Open(filename_rgb)
                for i in range(3):
                    opi_i = opi.GetRasterBand(i + 1).ReadAsArray()
                    opi_i[(mask == 0)] = 0
                    ortho_i = img_ortho_rgb.GetRasterBand(i + 1).ReadAsArray()
                    ortho_i[(mask != 0)] = 0
                    img_ortho_rgb.GetRasterBand(i + 1).WriteArray(np.add(opi_i, ortho_i))
                opi = None
            if with_ir:
                opi = gdal.Open(filename_ir)
                for i in range(1):
                    opi_i = opi.GetRasterBand(i + 1).ReadAsArray()
                    opi_i[(mask == 0)] = 0
                    ortho_i = img_ortho_ir.GetRasterBand(i + 1).ReadAsArray()
                    ortho_i[(mask != 0)] = 0
                    img_ortho_ir.GetRasterBand(i + 1).WriteArray(np.add(opi_i, ortho_i))
                opi = None
    if not is_empty:
        print("ici", with_rgb, with_ir)
         # si necessaire on cree les dossiers de tuile pour le graph et l'ortho
        Path(slab_ortho_rgb).parent.mkdir(parents=True, exist_ok=True)
        Path(slab_ortho_ir).parent.mkdir(parents=True, exist_ok=True)
        # pylint: disable=unused-variable
        assert_square(overviews['tileSize'])

        if with_rgb:
            print(slab_ortho_rgb)
            dst_ortho_rgb = COG_DRIVER.CreateCopy(slab_ortho_rgb, img_ortho_rgb,
                                                  options=["BLOCKSIZE="
                                                           + str(overviews['tileSize']['width']),
                                                           "COMPRESS=JPEG", "QUALITY=90"])
            dst_ortho_rgb = None  # noqa: F841
        if with_ir:
            dst_ortho_ir = COG_DRIVER.CreateCopy(slab_ortho_ir, img_ortho_ir,
                                                 options=["BLOCKSIZE="
                                                          + str(overviews['tileSize']['width']),
                                                          "COMPRESS=JPEG", "QUALITY=90"])
            dst_ortho_ir = None  # noqa: F841
    if img_ortho_rgb:
        img_ortho_rgb = None
    if img_ortho_ir:
        img_ortho_ir = None
