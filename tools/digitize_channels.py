#!/usr/bin/env python3
"""Independent stateful SiPM channels on one transport/acquisition clock."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
from digitize_cells import digitize, validate_geometry
from sipm_cells import CellConfig, keys
from sipm_noise import NoiseConfig
from sipm_dataset import parse, label, export_dataset, write_json


def channel_seed(seed, channel_path):
    return int.from_bytes(hashlib.sha256(f'g4pec-channel-v1:{seed}:{channel_path}'.encode()).digest()[:8], 'big')


def run(photons, events, geometry, timeline, config_path, output):
    config_path, output = Path(config_path), Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError('Channel response destination already exists')
    config = parse(config_path.read_bytes())
    keys(config, ('schema_version','provenance','seed','channels'), 'channel response config')
    if type(config['schema_version']) is not int or config['schema_version'] != 1:
        raise ValueError('Unsupported multi-channel schema')
    label(config['provenance'])
    if type(config['seed']) is not int or not 0 <= config['seed'] < 2**64:
        raise ValueError('Seed must be an integer in [0,2**64)')
    if not isinstance(config['channels'],list) or not config['channels']:
        raise ValueError('Every physical SiPM must be configured')
    prepared, ids, paths = [], set(), set()
    gdml = Path(geometry).read_bytes()
    for item in config['channels']:
        keys(item, ('channel_id','cells','noise'), 'channel response entry')
        cid=label(item['channel_id'])
        cells=CellConfig.from_dict(item['cells'])
        if cid in ids or cells.channel_path in paths:
            raise ValueError('Duplicate logical or physical channel')
        ids.add(cid); paths.add(cells.channel_path)
        footprint=validate_geometry(cells, gdml, select_channel=True)
        if item['noise'] is not None: NoiseConfig.from_dict(item['noise'])
        prepared.append((cid,item,footprint))
    if paths != set(prepared[0][2]['geometry_channels']):
        raise ValueError('Configuration must cover every GDML SiPM, including inactive channels')
    # Snapshot inputs so every channel consumes identical bytes and remains reproducible.
    data={k:Path(p).read_bytes() for k,p in (('photons.csv',photons),('events.csv',events),('timeline.json',timeline))}
    data['geometry.gdml']=gdml
    output.mkdir(parents=True,exist_ok=False)
    try:
        inputs=output/'inputs'; inputs.mkdir()
        for name,raw in data.items(): (inputs/name).write_bytes(raw)
        write_json(inputs/'channels.json',config)
        exports=[]; report=[]
        for index,(cid,item,footprint) in enumerate(sorted(prepared)):
            folder=output/'responses'/f'{index:04d}'; folder.mkdir(parents=True)
            cp=folder/'cells.json'; write_json(cp,item['cells'])
            np=None
            if item['noise'] is not None:
                np=folder/'noise.json'; write_json(np,item['noise'])
            seed=channel_seed(config['seed'],item['cells']['channel_path'])
            prefix=folder/'response'
            r=digitize(inputs/'photons.csv',inputs/'events.csv',prefix,cp,inputs/'geometry.gdml',
                       seed=seed,timeline_path=inputs/'timeline.json',noise_path=np,select_channel=True)
            exports.append({'channel_id':cid,'detector_id':footprint['detector_id'],
                            'response':str((folder/'response_response.json').relative_to(output)),
                            'history':str((folder/'response_history.csv').relative_to(output))})
            report.append({'channel_id':cid,'channel_path':item['cells']['channel_path'],
                           'detector_id':footprint['detector_id'],'seed':seed,'totals':r['totals']})
        ep=output/'export.json'; write_json(ep,{'schema_version':1,'provenance':config['provenance'],'channels':exports})
        dataset=export_dataset(ep,output/'dataset',include_truth=True)
        result={'schema_version':1,'provenance':config['provenance'],'master_seed':config['seed'],
                'seed_policy':'SHA256(g4pec-channel-v1:seed:physical_path), first 8 bytes big endian',
                'channel_model':'Independent cell/noise state per SiPM; no electrical cross-channel coupling',
                'dataset_id':dataset['dataset_id'],'channels':report,
                'inputs':{k:hashlib.sha256(v).hexdigest() for k,v in data.items()}}
        write_json(output/'run.json',result)
    except Exception:
        shutil.rmtree(output)
        raise
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('photons','events','geometry','timeline','config','output'): p.add_argument(name,type=Path)
    a=p.parse_args()
    try: r=run(a.photons,a.events,a.geometry,a.timeline,a.config,a.output)
    except (ValueError,OSError,KeyError,TypeError,OverflowError,ET.ParseError) as e:
        p.exit(1,f'Channel response failed: {e}\n')
    print(json.dumps(r['channels']))


if __name__=='__main__': main()
