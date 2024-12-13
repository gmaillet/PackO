# coding: utf-8
"""This script create or update a cache with a list of OPI"""
import os
import sys
import argparse
import glob
import multiprocessing
from pathlib import Path, PurePosixPath
import json
import time
import re
from osgeo import gdal
from osgeo import osr

import cache_def as cache

# enable gdal/ogr exceptions
gdal.UseExceptions()

cpu_dispo = multiprocessing.cpu_count()


def read_args(with_images, with_graph, with_tile, with_overview):
    """Gestion des arguments"""

    parser = argparse.ArgumentParser()
    if with_images:
        parser.add_argument("-R", "--rgb",
                            help="input RGB OPI full path")

        parser.add_argument("-I", "--ir",
                            help="input IR OPI full path")
    if with_tile:
        parser.add_argument("-i", "--input",
                            required=True,
                            type=int,
                            nargs=5,
                            help="tile number (level, slabXMin, slabYMin, slabXMax, slabYMax)")
    
    parser.add_argument("-c", "--cache",
                        help="cache directory (default: cache)",
                        type=str,
                        default="cache")
    if with_overview:
        parser.add_argument("-o", "--overviews",
                                help="params for the mosaic (default: ressources/RGF93_LA93_5cm.json)",
                                type=str,
                                default="ressources/RGF93_LA93_5cm.json")
    if with_graph:
        parser.add_argument("-g", "--graph",
                            help="GeoPackage filename or database connection string \
                            (\"PG:host=localhost user=postgres password=postgres dbname=demo\")",
                            type=str,
                            default="")
        parser.add_argument("-t", "--table",
                            help="graph table (default: graphe_pcrs56_zone_test)",
                            type=str,
                            default="graphe_pcrs56_zone_test")
    parser.add_argument("-p", "--processors",
                        help="number of processing units to allocate (default: Max_cpu-1)",
                        type=int,
                        default=(cpu_dispo-1, 1)[cpu_dispo - 1 == 0])
    parser.add_argument("-r", "--running",
                        help="launch the process locally (default: 0, meaning no process \
                        launching, only GPAO project file creation)",
                        type=int,
                        default=0)
    parser.add_argument("-s", "--subsize",
                        help="size of the subareas for data processing, in slabs \
                        (default: 2, meaning 2x2 slabs)",
                        type=int,
                        default=2)
    parser.add_argument("-z", "--zeromtd",
                        help="allow input graph with no metadata (default: 0, metadata needed)",
                        type=int,
                        default=0)
    parser.add_argument("-v", "--verbose",
                        help="verbose (default: 0, meaning no verbose)",
                        type=int,
                        default=0)
    args = parser.parse_args()

    if args.verbose > 1:
        print("\nArguments: ", args)

    # if not export_tile and (args.rgb is not None) and os.path.isdir(args.rgb):
    #     raise SystemExit("ERROR: invalid pattern: " + args.rgb)
    # if not export_tile and (args.ir is not None) and os.path.isdir(args.ir):
    #     raise SystemExit("ERROR: invalid pattern: " + args.ir)
    # if not export_tile and (args.rgb is None) and (args.ir is None):
    #     raise SystemExit("ERROR: no input data")

    if with_overview:
        if os.path.isdir(args.cache):
            raise SystemExit("ERROR: Cache (" + args.cache + ") already in use")
    else:
        if not os.path.isdir(args.cache):
            raise SystemExit("ERROR: Cache '" + args.cache + "' doesn't exist.")

    if with_graph:
        # gestion des echappements possible sur le nom de table
        args.table = args.table.strip("'").strip('"')
        if args.table[0].isdigit():
            raise SystemExit("ERROR: First char of table is digit. "
                            "Check table name and change it if needed.")

    if args.subsize < 1:
        raise SystemExit("ERROR: subsize must be equal or greater than 1.")

    if with_graph:
        db_graph = gdal.OpenEx(args.graph, gdal.OF_VECTOR)
        if db_graph is None:
            raise SystemExit("ERROR: Connection to database failed")

        # Test pour savoir si le nom de la table est correct
        if db_graph.ExecuteSQL("select * from " + args.table) is None:
            raise SystemExit("ERROR: table " + args.table + " doesn't exist")

        # check if DATE, HEURE_TU columns exist in input graph
        if args.zeromtd == 0:
            db_graph = gdal.OpenEx(args.graph, gdal.OF_VECTOR)
            if db_graph.ExecuteSQL(
                    "SELECT DATE, HEURE_TU FROM " + args.table + " \
                        WHERE EXISTS(SELECT NULL)") is None:
                raise SystemExit("ERROR: input graph without metadata")

    return args


def prep_dict(args):
    """Création des différents dictionnaires"""
    with open(args.overviews) as json_overviews:
        overviews_dict = json.load(json_overviews)

    # overviews_dict = overviews_init
    overviews_dict["list_OPI"] = {}
    overviews_dict['dataSet'] = {}
    overviews_dict['dataSet']['boundingBox'] = {}
    overviews_dict['dataSet']['limits'] = {}
    overviews_dict['dataSet']['slabLimits'] = {}
    overviews_dict['dataSet']['level'] = {}
    overviews_dict['dataSet']['level'] = {
        'min': overviews_dict['level']['min'],
        'max': overviews_dict['level']['max']
    }

    color_dict = {}
    return overviews_dict, color_dict


def prep_cut_opi():
    """Cut one OPI for update/create a cache"""
    dir_script = PurePosixPath(sys.argv[0]).parent
    
    # with_images, with_graph, with_tile, with_overview
    args = read_args(True, False, False, False)
    cpu_util = args.processors

    with open(args.cache + '/overviews.json') as json_overviews:
        overviews_dict = json.load(json_overviews)

    name = args.rgb
    str_args = ' -c '+args.cache

    if args.rgb:
        str_args += ' -R ' + args.rgb
    else:
        name = args.ir
    if args.ir:
        str_args += ' -I ' + args.ir

    overviews = overviews_dict
    cmds = []

    slabLimits = cache.get_slabbox(name, overviews)
    try:
        for level in slabLimits.keys():
            level_limits = slabLimits[level]            
            for slab_x in range(level_limits["MinSlabCol"],
                                level_limits["MaxSlabCol"] + 1,
                                args.subsize):
                for slab_y in range(level_limits["MinSlabRow"],
                                    level_limits["MaxSlabRow"] + 1,
                                    args.subsize):
                    # il faut s'assurer qu'on ne va pas dépasser des max selon les deux axes
                    slab_x_max = slab_x + args.subsize - 1
                    if slab_x_max > level_limits["MaxSlabCol"]:
                        slab_x_max = level_limits["MaxSlabCol"]
                    slab_y_max = slab_y + args.subsize - 1
                    if slab_y_max > level_limits["MaxSlabRow"]:
                        slab_y_max = level_limits["MaxSlabRow"]
                    cmds.append(
                            {'name': level+'_'+str(slab_x)+'_'+str(slab_y),
                            'command': 'python '+str(dir_script/'cut_opi.py') +
                                        ' -i ' + level + ' ' +
                                        str(slab_x) + ' ' + str(slab_y) + ' ' +
                                        str(slab_x_max) + ' ' + str(slab_y_max) + str_args}
                        )
                    # print('python '+str(dir_script/'cut_opi.py'))
                    # print(cmds[len(cmds)-1])
        
        if not args.running:
            export_as_json(args.cache + '/cut_' + Path(name).stem + '.json', cmds, 'decoupage_' + Path(name).stem)
        else:
            print("Découpage de l'OPI")
            cmds = []
            for cmd in cmds:
                cmds.append(cmd['command'])
            pool = multiprocessing.Pool(cpu_util)
            time_start = time.perf_counter()

            def mycallback(r):
                del r
                mycallback.cnt += 1
                cache.display_bar(mycallback.cnt, mycallback.nb)

            mycallback.cnt = 0
            mycallback.nb = len(cmds)
            cache.display_bar(mycallback.cnt, mycallback.nb)

            results = []
            for cmd in cmds:
                r = pool.apply_async(os.system, (cmd,), callback=mycallback)
                results.append(r)
            for r in results:
                r.wait()

            time_end = time.perf_counter()

            if args.verbose > 0:
                print(f"Temps du découpage de l'OPI : {time_end - time_start:.2f} s")
    except Exception as err:
        raise SystemExit(f"ERROR: {err}")

def generate_tiles_opi():
    """ cut an opi for a group of tiles"""
    # with_images, with_graph, with_tile, with_overview
    args = read_args(True, False, True, False)
    with open(args.cache + '/overviews.json') as json_overviews:
        overviews_dict = json.load(json_overviews)

    resolution = overviews_dict['resolution'] * 2 ** (overviews_dict['level']['max'] - args.input[0])
    size_width = overviews_dict['tileSize']['width'] * overviews_dict['slabSize']['width']
    dx = size_width * resolution
    size_height = overviews_dict['tileSize']['height'] * overviews_dict['slabSize']['height']
    dy = size_height * resolution
    for slab_x in range(args.input[1], args.input[3] + 1):
        for slab_y in range(args.input[2], args.input[4] + 1):
            slab_root = args.cache + '/opi/' + str(args.input[0]) + '/'\
                        + cache.get_slab_path(slab_x, slab_y, overviews_dict['pathDepth'])
            # si necessaire, on cree le dossier
            Path(slab_root[:-2]).mkdir(parents=True, exist_ok=True)

            ulx = round(overviews_dict['crs']['boundingBox']['xmin'] + slab_x * dx,2)
            uly = round(overviews_dict['crs']['boundingBox']['ymax'] - slab_y * dy,2)
            lrx = round(ulx + dx,2)
            lry = round(uly - dy,2)

            cmd="gdal_translate "
            cmd+="-projwin " + str(ulx) + " " + str(uly) + " " + str(lrx) + " " + str(lry) + " "
            cmd+="-a_srs epsg:2154 "
            cmd+="-r nearest "
            cmd+="-outsize "+str(size_width)+" "+str(size_height)+" "
            cmd+="-of COG -co COMPRESS=JPEG -co QUALITY=90 -co BLOCKSIZE="+str(overviews_dict['tileSize']['width'])+" -co OVERVIEWS=IGNORE_EXISTING "
            
            if args.rgb:
                cmd_rgb = cmd + args.rgb + ' ' + slab_root + '_' + Path(args.rgb).stem + '.tif'
                print(cmd_rgb)
                os.system(cmd_rgb)
            if args.ir:
                cmd_ir = cmd + args.ir + ' ' + slab_root + '_' + Path(args.ir).stem + '.tif'
                print(cmd_ir)
                os.system(cmd_ir)


def generate_tiles_graph():
    """rasterize graph for a group of tiles"""
    # with_images, with_graph, with_tile, with_overview
    args = read_args(False, True, True, False)
    args.cache = os.path.abspath(args.cache)
    with open(args.cache + '/overviews.json') as json_overviews:
        overviews_dict = json.load(json_overviews)

    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromEPSG(overviews_dict['crs']['code'])
    spatial_ref_wkt = spatial_ref.ExportToWkt()

    resol = overviews_dict['resolution'] * 2 ** (overviews_dict['level']['max'] - args.input[0])
    for slab_x in range(args.input[1], args.input[3] + 1):
        for slab_y in range(args.input[2], args.input[4] + 1):
            args_create_graph = {
                'slab': {
                    'x': slab_x,
                    'y': slab_y,
                    'level': args.input[0],
                    'resolution': resol
                },
                'overviews': overviews_dict,
                'dbOption': {
                    'connString': args.graph,
                    'table': args.table
                },
                'cache': args.cache,
                'gdalOption':  {
                    'spatialRef': spatial_ref_wkt
                }
            }
            cache.create_graph_1arg(args_create_graph)


def generate_tiles_ortho():
    """rasterize ortho for a group of tiles"""
    # with_images, with_graph, with_tile, with_overview
    args = read_args(False, False, True, False)
    args.cache = os.path.abspath(args.cache)
    with open(args.cache + '/overviews.json') as json_overviews:
        overviews_dict = json.load(json_overviews)

    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromEPSG(overviews_dict['crs']['code'])
    spatial_ref_wkt = spatial_ref.ExportToWkt()

    resol = overviews_dict['resolution'] * 2 ** (overviews_dict['level']['max'] - args.input[0])
    for slab_x in range(args.input[1], args.input[3] + 1):
        for slab_y in range(args.input[2], args.input[4] + 1):
            args_create_ortho = {
                'slab': {
                    'x': slab_x,
                    'y': slab_y,
                    'level': args.input[0],
                    'resolution': resol
                },
                'overviews': overviews_dict,
                'cache': args.cache,
                'gdalOption':  {
                    'spatialRef': spatial_ref_wkt
                }
            }
            cache.create_ortho_1arg(args_create_ortho)


def export_as_json(filename, jobs, name):
    """Export json file for gpao"""
    gpao = {'projects': [
        {'name': name, 'jobs': []}
        ]}
    for job in jobs:
        gpao['projects'][0]['jobs'].append(job)
    with open(filename, 'w') as file:
        json.dump(gpao, file)


def get_checked_date_time(opi_feature):
    """Get checked values for metadata"""
    date = opi_feature.GetField('DATE')
    # yyyy-mm-dd | yyyy/mm/dd
    pattern_date = "[0-9]{4}[/-][0-9]{2}[/-][0-9]{2}"
    if date is None or not re.match(pattern_date, date):
        raise SystemExit(f"ERROR: '{date=}' not in the correct format "
                         "(expected: yyyy-mm-dd or yyyy/mm/dd)")
    time_ut = opi_feature.GetField('HEURE_TU')
    # HHhmm | HH:mm
    pattern_time_ut = "[0-9]{2}[h:][0-5][0-9]"
    if time_ut is None or not re.match(pattern_time_ut, time_ut):
        raise SystemExit(f"ERROR: '{time_ut=}' not in the correct format "
                         "(expected: HHhmm or HH:mm)")
    return date, time_ut


def create_cache():
    """Create a cache from a graph"""

    dir_script = PurePosixPath(sys.argv[0]).parent
    print(dir_script)

    # with_images, with_graph, with_tile, with_overview
    args = read_args(True, True, False, True)
    overviews_dict, color_dict = prep_dict(args)

    list_filename_rgb = []
    list_filename_ir = []
    nb_files = 0
    with_rgb = False
    with_ir = False
    if args.rgb:
        list_filename_rgb = glob.glob(args.rgb)
        nb_files = len(list_filename_rgb)
        with_rgb = True
    if args.ir:
        list_filename_ir = glob.glob(args.ir)
        dir_ir = os.path.dirname(list_filename_ir[0])
        nb_files = max(nb_files, len(list_filename_ir))
        with_ir = True
    list_filename = list_filename_rgb
    if len(list_filename_rgb) == 0:
        list_filename = list_filename_ir

    cpu_util = args.processors

    # on analyse le graphe pour recuperer l'emprise et la liste des cliches
    db_graph = gdal.OpenEx(args.graph, gdal.OF_VECTOR)
    graph_layer = db_graph.GetLayer(args.table)
    extent = graph_layer.GetExtent()
    tile_limits = {}
    tile_limits['LowerCorner'] = [extent[0], extent[2]]
    tile_limits['UpperCorner'] = [extent[1], extent[3]]
    cache.set_limits(tile_limits, overviews_dict)    

    for feature in graph_layer:
        # Récupérer les attributs de l'objet
        basename = feature.items()['cliche']
        # pas de metadonnees en entree, on met des valeurs fictives
        # (DATE: "1900-01-01", HEURE_TU: "00:00")
        date = "1900-01-01"
        time_ut = "00:00"

        overviews_dict["list_OPI"][basename] = {
            'color': cache.new_color(basename, color_dict),
            'date': date.replace('/', '-'),
            'time_ut': time_ut.replace('h', ':'),
            'with_rgb': with_rgb,
            'with_ir': with_ir
        }

    # si necessaire, on cree le dossier et on exporte les MTD
    Path(args.cache).mkdir(parents=True, exist_ok=True)

    with open(args.cache + '/cache_mtd.json', 'w') as outfile:
        json.dump(color_dict, outfile)

    with open(args.cache + '/overviews.json', 'w') as outfile:
        json.dump(overviews_dict, outfile)
    
    slabbox_export = overviews_dict['dataSet']['slabLimits']
    try:
        gpao = {'projects': []}
        cmds_generate_graph = []
        
        # Calcul des graph
        if args.table.strip('"')[0].isdigit():
            table = '"\\' + args.table + '\\"'
        else:
            table = args.table
        for level in slabbox_export.keys():
            level_limits = slabbox_export[level]
            for slab_x in range(level_limits["MinSlabCol"],
                                level_limits["MaxSlabCol"] + 1,
                                args.subsize):
                for slab_y in range(level_limits["MinSlabRow"],
                                    level_limits["MaxSlabRow"] + 1,
                                    args.subsize):
                    # il faut s'assurer qu'on ne va pas dépasser des max selon les deux axes
                    slab_x_max = slab_x + args.subsize - 1
                    if slab_x_max > level_limits["MaxSlabCol"]:
                        slab_x_max = level_limits["MaxSlabCol"]
                    slab_y_max = slab_y + args.subsize - 1
                    if slab_y_max > level_limits["MaxSlabRow"]:
                        slab_y_max = level_limits["MaxSlabRow"]
                    cmds_generate_graph.append(
                        {'name': level+'_'+str(slab_x)+'_'+str(slab_y),
                         'command': 'python '+str(dir_script/'generate_tiles_graph.py') +
                                    ' -i ' + level + ' ' +
                                    str(slab_x) + ' ' + str(slab_y) + ' ' +
                                    str(slab_x_max) + ' ' + str(slab_y_max) + ' -c ' +
                                    args.cache + ' -g ' + args.graph + ' -t ' + table + ' -z 1'}
                    )

        gpao['projects'].append({'name': 'generate_tiles_graph', 'jobs': cmds_generate_graph})
        # if args.running:
        #     print("Génération tuiles graphe")
        #     cmds = []
        #     for cmd in cmds:
        #         cmds.append(cmd['command'])
        #     pool = multiprocessing.Pool(cpu_util)
        #     time_start_graph = time.perf_counter()

        #     def mycallback(r):
        #         del r
        #         mycallback.cnt += 1
        #         cache.display_bar(mycallback.cnt, mycallback.nb)

        #     mycallback.cnt = 0
        #     mycallback.nb = len(cmds)
        #     cache.display_bar(mycallback.cnt, mycallback.nb)

        #     results = []
        #     for cmd in cmds:
        #         r = pool.apply_async(os.system, (cmd,), callback=mycallback)
        #         results.append(r)
        #     for r in results:
        #         r.wait()

        #     time_end = time.perf_counter()

        #     if args.verbose > 0:
        #         time_graph = time_end - time_start_graph
        #         print(f"Temps création tuiles graphe : {time_graph:.2f} s")

        # decoupage des OPI
        cmds_generate_opi = []
        for filename in list_filename:
            filename = Path(filename).as_posix()
            # print(filename)
            # print(Path(filename).as_posix())
            basename = Path(filename).stem
            slabLimits = cache.get_slabbox(filename, overviews_dict)
            print(slabLimits)
            for level in slabLimits.keys():
                level_limits = slabLimits[level]            
                for slab_x in range(level_limits["MinSlabCol"],
                                    level_limits["MaxSlabCol"] + 1,
                                    args.subsize):
                    for slab_y in range(level_limits["MinSlabRow"],
                                        level_limits["MaxSlabRow"] + 1,
                                        args.subsize):
                        # il faut s'assurer qu'on ne va pas dépasser des max selon les deux axes
                        slab_x_max = slab_x + args.subsize - 1
                        if slab_x_max > level_limits["MaxSlabCol"]:
                            slab_x_max = level_limits["MaxSlabCol"]
                        slab_y_max = slab_y + args.subsize - 1
                        if slab_y_max > level_limits["MaxSlabRow"]:
                            slab_y_max = level_limits["MaxSlabRow"]
                        cmds_generate_opi.append(
                                {'name': basename+'_'+level+'_'+str(slab_x)+'_'+str(slab_y),
                                'command': 'python '+str(dir_script/'generate_tiles_opi.py') +
                                            ' -i ' + level + ' ' +
                                            str(slab_x) + ' ' + str(slab_y) + ' ' +
                                            str(slab_x_max) + ' ' + str(slab_y_max) + ' -c '+args.cache + ' -R '+filename}
                            )
        gpao['projects'].append({'name': 'generate_tiles_opi', 'jobs': cmds_generate_opi, 'deps': [{'id': 0}]})

        # export des ortho
        cmds_generate_ortho = []
        for level in slabbox_export.keys():
            level_limits = slabbox_export[level]
            for slab_x in range(level_limits["MinSlabCol"],
                                level_limits["MaxSlabCol"] + 1,
                                args.subsize):
                for slab_y in range(level_limits["MinSlabRow"],
                                    level_limits["MaxSlabRow"] + 1,
                                    args.subsize):
                    # il faut s'assurer qu'on ne va pas dépasser des max selon les deux axes
                    slab_x_max = slab_x + args.subsize - 1
                    if slab_x_max > level_limits["MaxSlabCol"]:
                        slab_x_max = level_limits["MaxSlabCol"]
                    slab_y_max = slab_y + args.subsize - 1
                    if slab_y_max > level_limits["MaxSlabRow"]:
                        slab_y_max = level_limits["MaxSlabRow"]
                    cmds_generate_ortho.append(
                            {'name': level+'_'+str(slab_x)+'_'+str(slab_y),
                            'command': 'python '+str(dir_script/'generate_tiles_ortho.py') +
                                        ' -i ' + level + ' ' +
                                        str(slab_x) + ' ' + str(slab_y) + ' ' +
                                        str(slab_x_max) + ' ' + str(slab_y_max) + ' -c '+args.cache}
                        )
        gpao['projects'].append({'name': 'generate_tiles_ortho', 'jobs': cmds_generate_ortho, 'deps': [{'id': 1}]})
        with open(args.cache + '/create.json', 'w') as file:
            json.dump(gpao, file)


    except Exception as err:
        raise SystemExit(f"ERROR: {err}")



