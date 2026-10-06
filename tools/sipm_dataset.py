#!/usr/bin/env python3
"""Portable, geometry-independent SiPM response boundary; optional separate truth."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import uuid

from digitize_cells import csv_rows, unique_json, reject_constant
from sipm_cells import keys, number


def parse(data):
    return json.loads(data, object_pairs_hook=unique_json, parse_constant=reject_constant)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def label(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Identifiers and provenance must be nonempty strings')
    return value


def history_rows(data, response):
    clock = response['acquisition']
    start, lower, upper = (number(clock[k], k, minimum=0) for k in ('state_start_ns','window_start_ns','window_end_ns'))
    if not start <= lower < upper:
        raise ValueError('Invalid acquisition window')
    seen, result, observed = set(), [], 0
    for row in csv_rows(data, ('avalanche_id','time_ns','charge_pC','observed'), 'pulse history'):
        aid = int(row['avalanche_id'])
        t = number(float(row['time_ns']), 'pulse time', minimum=start)
        q = number(float(row['charge_pC']), 'pulse charge', strictly_positive=True)
        if aid <= 0 or aid in seen or t >= upper or row['observed'] not in ('True','False'):
            raise ValueError('Invalid pulse ID, time or observed flag')
        if (row['observed'] == 'True') != (t >= lower):
            raise ValueError('Pulse observation flag does not match window')
        seen.add(aid); observed += t >= lower
        result.append({'avalanche_id':aid, 'time_ns':t, 'charge_pC':q, 'observed':t >= lower})
    expected = (sum(c['detected'] for c in response['noise']['counts_including_warmup'].values())
                if 'noise' in response else response['totals']['avalanches']+response['warmup_counts']['detected'])
    if observed != response['totals']['avalanches'] or len(result) != expected:
        raise ValueError('Incomplete pulse history or inconsistent observed count')
    return sorted(result, key=lambda r:(r['time_ns'],r['avalanche_id']))


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def export_dataset(config_path, output, include_truth=False):
    config_path, output = Path(config_path), Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError('Dataset destination already exists')
    raw = config_path.read_bytes(); config = parse(raw)
    keys(config, ('schema_version','provenance','channels'), 'dataset export config')
    if type(config['schema_version']) is not int or config['schema_version'] != 1:
        raise ValueError('Unsupported export config schema')
    label(config['provenance'])
    if not isinstance(config['channels'], list) or not config['channels']:
        raise ValueError('Declare at least one channel, including inactive channels')
    prepared, ids, paths, sources = [], set(), set(), set()
    common = None
    for item in config['channels']:
        keys(item, ('channel_id','detector_id','response','history'), 'channel export')
        cid, did = label(item['channel_id']), label(item['detector_id'])
        rp, hp = [(config_path.parent/label(item[k])).resolve() for k in ('response','history')]
        if cid in ids or rp in sources or hp in sources:
            raise ValueError('Duplicate channel ID or reused response/history input')
        ids.add(cid); sources.update((rp,hp))
        rb, hb = rp.read_bytes(), hp.read_bytes(); r = parse(rb)
        if type(r.get('schema_version')) is not int or r['schema_version'] != 1 or r.get('time_basis') != 'acquisition_relative_ns':
            raise ValueError('Require schema-1 acquisition response')
        if r.get('output_hashes',{}).get('history_sha256') != digest(hb):
            raise ValueError('A matching recorded history hash is required')
        channel_path = label(r['parameters']['channel_path'])
        if channel_path in paths:
            raise ValueError('Duplicate physical channel path')
        paths.add(channel_path)
        geometry = r['inputs']['geometry']['sha256']
        if not isinstance(geometry,str) or len(geometry) != 64 or any(c not in '0123456789abcdef' for c in geometry):
            raise ValueError('Invalid geometry SHA256')
        if r.get('transport_identity') is None or r['acquisition'].get('transport_identity') != r['transport_identity']:
            raise ValueError('Acquisition and transport identity must agree')
        # Match the complete schedule, not merely the observation bounds.
        signature = (geometry, canonical(r['acquisition']), canonical(r['transport_identity']))
        if common is not None and common != signature:
            raise ValueError('Channels must share geometry, transport identity and complete acquisition timeline')
        common = signature
        pulses = history_rows(hb, r)
        prepared.append((cid,did,channel_path,r,pulses,rb,hb))
    prepared.sort(key=lambda x:x[0])
    dataset_id = str(uuid.uuid4())
    clock = {k: prepared[0][3]['acquisition'][k] for k in ('state_start_ns','window_start_ns','window_end_ns')}
    clock.update(clock_id=digest(common[1]), time_basis='acquisition_relative_ns', unit='ns',
                 convention='[window_start_ns,window_end_ns); prehistory retained from state_start_ns')
    manifest = {'schema_version':1, 'artifact_type':'sipm_response_dataset', 'dataset_id':dataset_id,
                'provenance':config['provenance'], 'export_config_sha256':digest(raw),
                'geometry_sha256':common[0], 'clock':clock, 'units':{'charge':'pC','time':'ns'},
                'detector_mapping':'Explicit user-supplied registry; not inferred from crystal count',
                'channels':[]}
    output.mkdir(parents=True, exist_ok=False)
    try:
        truth = []
        for index,(cid,did,path,r,pulses,rb,hb) in enumerate(prepared):
            folder = output/'channels'/f'{index:04d}'; folder.mkdir(parents=True)
            history = folder/'history.csv'; response = folder/'response.json'
            with history.open('x',newline='') as stream:
                writer = csv.DictWriter(stream,fieldnames=('avalanche_id','time_ns','charge_pC','observed'))
                writer.writeheader(); writer.writerows(pulses)
            context = {'dataset_id':dataset_id,'channel_id':cid,'detector_id':did,
                       'geometry_sha256':common[0],'clock_id':clock['clock_id']}
            parameters = {'cells':r['parameters'], 'noise':r.get('noise',{}).get('parameters')}
            portable = {'schema_version':1,'model':'sipm_response_channel_v1', 'time_basis':'acquisition_relative_ns',
                        'response_dataset':context, 'parameters':{'channel_path':path},
                        'response_parameters':parameters, 'response_settings_sha256':digest(canonical(parameters)),
                        'simulation':{k:r.get(k) for k in ('model','model_version','seed','random_engine')},
                        'noise_seed':r.get('noise',{}).get('noise_seed'),
                        'acquisition':{k:clock[k] for k in ('state_start_ns','window_start_ns','window_end_ns')},
                        'totals':{'avalanches':sum(p['observed'] for p in pulses)},
                        'warmup_counts':{'detected':sum(not p['observed'] for p in pulses)},
                        'source_hashes':{'response_sha256':digest(rb),'history_sha256':digest(hb)},
                        'output_hashes':{'history_sha256':digest(history.read_bytes())}}
            write_json(response, portable)
            manifest['channels'].append(dict(context, channel_path=path,
                response_settings_sha256=portable['response_settings_sha256'],
                history={'path':str(history.relative_to(output)),'sha256':digest(history.read_bytes())},
                response={'path':str(response.relative_to(output)),'sha256':digest(response.read_bytes())}))
            if include_truth:
                # Keyed separately; neither portable response nor registry requires this file.
                for row in csv_rows(hb, ('avalanche_id',), 'source history'):
                    truth.append({'dataset_id':dataset_id,'channel_id':cid,'pulse_id':row['avalanche_id'],
                                  'transport_identity':r['transport_identity'],
                                  'annotations':{k:v for k,v in row.items() if k not in ('avalanche_id','time_ns','charge_pC','observed')}})
        if include_truth:
            write_json(output/'truth.json', {'schema_version':1,'dataset_id':dataset_id,'pulses':truth})
        write_json(output/'manifest.json',manifest)
    except Exception:
        shutil.rmtree(output)
        raise
    return manifest


def load_channel(dataset, channel_id):
    """Read/verify only portable registry and response files, never GDML or truth."""
    root = Path(dataset).resolve(); manifest = parse((root/'manifest.json').read_bytes())
    if type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1 or manifest.get('artifact_type') != 'sipm_response_dataset':
        raise ValueError('Unsupported SiPM dataset')
    if manifest.get('units') != {'charge':'pC','time':'ns'}:
        raise ValueError('Unsupported response units')
    if manifest['clock'].get('unit') != 'ns' or manifest['clock'].get('time_basis') != 'acquisition_relative_ns':
        raise ValueError('Unsupported acquisition clock')
    channels = manifest['channels']
    if len({c['channel_id'] for c in channels}) != len(channels) or len({c['channel_path'] for c in channels}) != len(channels):
        raise ValueError('Duplicate channel registry entries')
    matches = [c for c in channels if c['channel_id'] == channel_id]
    if len(matches) != 1:
        raise ValueError('Unknown channel ID')
    entry = matches[0]; files = {}
    for k in ('history','response'):
        path = (root/entry[k]['path']).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Dataset file escapes its directory')
        if digest(path.read_bytes()) != entry[k]['sha256']:
            raise ValueError('Dataset file hash mismatch')
        files[k] = path
    response = parse(files['response'].read_bytes())
    if type(response.get('schema_version')) is not int or response['schema_version'] != 1 or response.get('model') != 'sipm_response_channel_v1' or response.get('time_basis') != 'acquisition_relative_ns':
        raise ValueError('Unsupported portable channel response')
    context = {k:entry[k] for k in ('dataset_id','channel_id','detector_id','geometry_sha256','clock_id')}
    if context != response['response_dataset'] or context['dataset_id'] != manifest['dataset_id'] or context['geometry_sha256'] != manifest['geometry_sha256'] or context['clock_id'] != manifest['clock']['clock_id']:
        raise ValueError('Registry/context mismatch')
    if response['parameters']['channel_path'] != entry['channel_path'] or response['acquisition'] != {k:manifest['clock'][k] for k in ('state_start_ns','window_start_ns','window_end_ns')}:
        raise ValueError('Channel path or clock mismatch')
    if digest(canonical(response['response_parameters'])) != entry['response_settings_sha256'] or response['response_settings_sha256'] != entry['response_settings_sha256']:
        raise ValueError('Response settings mismatch')
    if digest(files['history'].read_bytes()) != response['output_hashes']['history_sha256']:
        raise ValueError('Response/history mismatch')
    history_rows(files['history'].read_bytes(),response)
    return manifest, entry, files


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config',type=Path); p.add_argument('output',type=Path)
    p.add_argument('--include-truth',action='store_true')
    a=p.parse_args()
    try:
        result=export_dataset(a.config,a.output,a.include_truth)
    except (ValueError,OSError,KeyError,TypeError,OverflowError) as e:
        p.exit(1,f'Dataset export failed: {e}\n')
    print(json.dumps({'dataset_id':result['dataset_id'],'channels':len(result['channels'])}))


if __name__ == '__main__': main()
