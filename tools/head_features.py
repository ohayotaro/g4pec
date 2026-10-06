#!/usr/bin/env python3
"""Two-SiPM head features from measured channel candidates, without transport truth."""
import argparse
import csv
import json
import math
from pathlib import Path
import shutil

from analyze_sipm import analyze
from coincidences import match_pairs
from digitize_cells import csv_rows
from sipm_cells import keys, number
from sipm_dataset import parse, label, digest, load_channel, write_json

FEATURE_FIELDS = ('feature_id','left_single_id','right_single_id','time_ns','left_time_ns','right_time_ns',
                  'delta_ns','left_charge_pC','right_charge_pC','sum_charge_pC','charge_asymmetry',
                  'left_matches','right_matches','ambiguous','truncated','n_saturated','valid')
UNMATCHED_FIELDS = ('side','single_id','time_ns','charge_pC','reason')
SINGLE_FIELDS = ('single_id','channel_path','time_ns','charge_pC','n_saturated','truncated',
                 'feature_id','left_single_id','right_single_id')


def features(left, right, half_window_ns, max_pairs):
    """Pair all candidates; preserve ambiguity, quality failures and unmatched singles."""
    number(half_window_ns,'half_window_ns',strictly_positive=True)
    if type(max_pairs) is not int or not 1 <= max_pairs <= 2_000_000:
        raise ValueError('Invalid pair budget')
    lookup = {}
    for side, candidates in (('left',left),('right',right)):
        for c in candidates:
            sid=c['single_id']
            if type(sid) is not int or sid <= 0 or (side,sid) in lookup:
                raise ValueError('Invalid/duplicate candidate ID')
            number(c['time_ns'],'candidate time'); number(c['charge_pC'],'candidate charge')
            if type(c['truncated']) is not bool or type(c['n_saturated']) is not int or c['n_saturated'] < 0:
                raise ValueError('Invalid candidate quality')
            label(c['channel_path']); lookup[side,sid]=c
    pairs=match_pairs({'left':left,'right':right},[('left','right')],half_window_ns,max_pairs)
    rows, matched = [], set()
    for p in pairs:
        a,b=lookup['left',p['single_id_a']],lookup['right',p['single_id_b']]
        total=a['charge_pC']+b['charge_pC']
        if not math.isfinite(total): raise ValueError('Head charge overflow')
        valid_charge=total>0 and min(a['charge_pC'],b['charge_pC'])>=0
        # Divide first to avoid overflow in the charge difference and timestamp sum.
        ratio=(a['charge_pC']/total-b['charge_pC']/total) if valid_charge else None
        truncated=a['truncated'] or b['truncated']; saturated=a['n_saturated']+b['n_saturated']
        rows.append({'feature_id':len(rows)+1,'left_single_id':a['single_id'],'right_single_id':b['single_id'],
                     'time_ns':a['time_ns']/2+b['time_ns']/2,'left_time_ns':a['time_ns'],'right_time_ns':b['time_ns'],
                     'delta_ns':p['delta_ns'],'left_charge_pC':a['charge_pC'],'right_charge_pC':b['charge_pC'],
                     'sum_charge_pC':total,'charge_asymmetry':ratio,
                     'left_matches':p['matches_a'],'right_matches':p['matches_b'],
                     'ambiguous':p['ambiguous'],'truncated':truncated,'n_saturated':saturated,
                     'valid':valid_charge and not (p['ambiguous'] or truncated or saturated)})
        matched.update((('left',a['single_id']),('right',b['single_id'])))
    unmatched=[{'side':side,'single_id':sid,'time_ns':c['time_ns'],'charge_pC':c['charge_pC'],
                'reason':'no_opposite_candidate_in_time_window'} for (side,sid),c in sorted(lookup.items()) if (side,sid) not in matched]
    return rows,unmatched


def write_csv(path, fields, rows):
    with path.open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def run(dataset, config_path, output):
    config_path, output=Path(config_path),Path(output)
    if output.exists() or output.is_symlink(): raise FileExistsError('Head analysis output exists')
    raw=config_path.read_bytes(); config=parse(raw)
    keys(config,('schema_version','provenance','detector_id','half_window_ns','max_pairs','channels'),'head analysis')
    if type(config['schema_version']) is not int or config['schema_version']!=1:
        raise ValueError('Unsupported head analysis schema')
    label(config['provenance']);label(config['detector_id'])
    number(config['half_window_ns'],'half_window_ns',strictly_positive=True)
    if type(config['max_pairs']) is not int or not 1<=config['max_pairs']<=2_000_000:
        raise ValueError('Invalid pair budget')
    if not isinstance(config['channels'],list) or len(config['channels'])!=2:
        raise ValueError('This head feature model requires two ordered SiPM channels')
    prepared=[]; seen=set()
    for item in config['channels']:
        keys(item,('channel_id','time_offset_ns','readout','gate'),'head channel')
        cid=label(item['channel_id']);number(item['time_offset_ns'],'time_offset_ns')
        if cid in seen: raise ValueError('Head channels must be distinct')
        seen.add(cid)
        manifest,entry,_=load_channel(dataset,cid)
        if entry['detector_id']!=config['detector_id']: raise ValueError('Head channels belong to a different detector')
        adc=(config_path.parent/label(item['readout'])).resolve()
        gate=(config_path.parent/label(item['gate'])).resolve() if item['gate'] is not None else None
        prepared.append((item,entry,adc,gate))
    output.mkdir(parents=True,exist_ok=False)
    try:
        candidates=[]; provenance=[]; windows=[]
        for side,(item,entry,adc,gate) in zip(('left','right'),prepared):
            r=analyze(dataset,item['channel_id'],output/side,adc,gate)
            windows.append(tuple(number(r[k]+item['time_offset_ns'],k)
                                 for k in ('window_start_ns','window_end_ns')))
            path=output/(side+'_singles.csv'); data=path.read_bytes()
            if digest(data)!=r['output_hashes']['singles_sha256']: raise ValueError('Singles hash mismatch')
            selected=[]
            for row in csv_rows(data,('single_id','channel_path','time_ns','charge_pC','n_saturated','truncated'),'head input'):
                if row['truncated'] not in ('True','False'): raise ValueError('Invalid truncation flag')
                selected.append({'single_id':int(row['single_id']),'channel_path':row['channel_path'],
                                 'time_ns':float(row['time_ns'])+item['time_offset_ns'],'charge_pC':float(row['charge_pC']),
                                 'n_saturated':int(row['n_saturated']),'truncated':row['truncated']=='True'})
            candidates.append(selected)
            provenance.append({'side':side,'channel_id':item['channel_id'],'response_settings_sha256':entry['response_settings_sha256'],
                               'readout_manifest_sha256':digest((output/(side+'_readout.json')).read_bytes()),
                               'singles_sha256':digest(data),'n_singles':len(selected)})
        paired,unmatched=features(*candidates,config['half_window_ns'],config['max_pairs'])
        write_csv(output/'features.csv',FEATURE_FIELDS,paired)
        write_csv(output/'unmatched.csv',UNMATCHED_FIELDS,unmatched)
        # A logical head stream, not a physical SiPM placement or calibrated energy.
        head_path='head:'+config['detector_id']
        singles=[{'single_id':p['feature_id'],'channel_path':head_path,'time_ns':p['time_ns'],
                  'charge_pC':p['sum_charge_pC'],'n_saturated':p['n_saturated'],'truncated':p['truncated'],
                  **{k:p[k] for k in ('feature_id','left_single_id','right_single_id')}}
                 for p in paired if p['valid']]
        write_csv(output/'singles.csv',SINGLE_FIELDS,singles)
        single_manifest={'schema_version':1,'model':'two_sipm_head_singles_v1',
                         'time_basis':'acquisition_relative_ns','channel_path':head_path,
                         'window_start_ns':windows[0][0]/2+windows[1][0]/2,
                         'window_end_ns':windows[0][1]/2+windows[1][1]/2,
                         'n_singles':len(singles),
                         'response_head':{'dataset_id':manifest['dataset_id'],
                             'detector_id':config['detector_id'],'geometry_sha256':manifest['geometry_sha256'],
                             'clock_id':manifest['clock']['clock_id'],
                             'channel_ids':[item['channel_id'] for item in config['channels']]},
                         'selection':'valid features only; single_id equals feature_id',
                         'calibration':{'energy':None,'doi':None,'timing':None},
                         'features_sha256':digest((output/'features.csv').read_bytes()),
                         'config_sha256':digest(raw),
                         'output_hashes':{'singles_sha256':digest((output/'singles.csv').read_bytes())}}
        write_json(output/'singles.json',single_manifest)
        report={'schema_version':1,'model':'two_sipm_candidate_features_v1','parameters':config,'config_sha256':digest(raw),
                'dataset_manifest_sha256':digest((Path(dataset)/'manifest.json').read_bytes()),
                'dataset_id':manifest['dataset_id'],'geometry_sha256':manifest['geometry_sha256'],'clock_id':manifest['clock']['clock_id'],
                'inputs':provenance,'n_pairs':len(paired),'n_valid_pairs':sum(p['valid'] for p in paired),
                'n_ambiguous_pairs':sum(p['ambiguous'] for p in paired),'n_unmatched':len(unmatched),
                'definitions':{'window':'-W <= t_right-t_left < W; all pairs retained',
                               'time_ns':'Arithmetic mean of offset-corrected channel trigger times; not timing calibration',
                               'charge':'Sum/asymmetry of independently gated channel charges; no energy or DOI calibration',
                               'valid':'Unique match on both sides, no clipping/rails, nonnegative charges and positive sum',
                               'truth':'No event IDs, crystal positions or transport truth used'},
                'output_hashes':{name:digest((output/name).read_bytes()) for name in ('features.csv','unmatched.csv','singles.csv','singles.json')}}
        write_json(output/'head.json',report)
    except Exception:
        shutil.rmtree(output);raise
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','config','output'):p.add_argument(name,type=Path)
    a=p.parse_args()
    try:r=run(a.dataset,a.config,a.output)
    except (ValueError,OSError,KeyError,TypeError,OverflowError) as e:p.exit(1,f'Head analysis failed: {e}\n')
    print(json.dumps({k:r[k] for k in ('n_pairs','n_valid_pairs','n_ambiguous_pairs','n_unmatched')}))


if __name__=='__main__':main()
