#!/usr/bin/env python3
"""Directed ideal 511 keV gamma pair -> optical transport -> two heads -> coincidences."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from digitize_channels import run as respond
from head_features import run as analyze_head
from coincidences import select
from make_timeline import make_timeline
from sipm_dataset import digest,write_json
from bgo_response import rows


def run(executable,out,events,geometry=None):
    if not 2<=events<=256:raise ValueError('Require 2..256 events')
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    geometry=Path(geometry) if geometry is not None else ROOT/'examples/opposed_heads.gdml'
    # Retain the exact input geometry even when the caller supplied a temporary variant.
    snapshot=out/'input.gdml';snapshot.write_bytes(geometry.read_bytes());geometry=snapshot
    commands=['/random/setSeeds 12345 67890','/run/initialize']
    for i,direction in enumerate((1,-1)):
        if i:commands.append('/gps/source/add 1')
        commands.extend(['/gps/particle gamma','/gps/energy 511 keV','/gps/pos/type Point',
                         '/gps/pos/centre 0 0 0 mm',f'/gps/direction 0 0 {direction}','/gps/time 0 ns'])
    commands+=['/gps/source/multiplevertex true',f'/run/beamOn {events}']
    macro=out/'source.mac';macro.write_text('\n'.join(commands)+'\n')
    result=subprocess.run([str(Path(executable).resolve()),str(geometry),str(macro),str(out/'transport')],
                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
    (out/'transport.log').write_text(result.stdout)
    if result.returncode or any(s in result.stdout for s in ('GeomVol1002','COMMAND NOT FOUND','***** Illegal')):
        raise RuntimeError(result.stdout[-8000:])
    prefix=out/'transport_run0'
    files={k:Path(str(prefix)+'_'+k+ext) for k,ext in [('events','.csv'),('photons','.csv'),('tracks','.csv'),('steps','.csv'),('geometry','.gdml')]}
    # Source validation is separate from reconstruction; event IDs never select coincidences.
    primary=[r for r in rows(files['tracks']) if r['parent_id']=='0']
    if len(primary)!=2*events:raise ValueError('Expected two primaries per event')
    for event in range(events):
        ps=[r for r in primary if int(r['event_id'])==event]
        if len(ps)!=2 or sorted(float(r['dz']) for r in ps)!=[-1,1]:raise ValueError('Invalid pair directions')
        for r in ps:
            if r['particle']!='gamma' or abs(float(r['kinetic_energy_keV'])-511)>1e-9 or any(float(r[k])!=0 for k in ('dx','dy','time_ns','vertex_x_mm','vertex_y_mm','vertex_z_mm')):
                raise ValueError('Invalid ideal gamma pair')
    timeline=out/'timeline.json'
    make_timeline(files['events'],timeline,10000,1000+events*10000,first_offset_ns=1000,
                  provenance='Directed ideal gamma pairs; periodic test clock, not radioactive activity')
    config=json.loads((ROOT/'examples/dual_sipm_channels.json').read_text());base=copy.deepcopy(config['channels']);config['channels']=[]
    config['provenance']='Opposed two-SiPM heads, unchanged illustrative cell parameters; no noise'
    for head in ('A','B'):
        for item in copy.deepcopy(base):
            item['channel_id']=head+'_'+item['channel_id']
            item['cells']['channel_path']='/World_PV[0]/'+head+'_'+item['cells']['channel_path'].split('/')[-1]
            config['channels'].append(item)
    cp=out/'channels.json';write_json(cp,config)
    response=respond(files['photons'],files['events'],files['geometry'],timeline,cp,out/'response')
    if any(c['totals']['before_window'] or c['totals']['after_window'] for c in response['channels']):raise ValueError('Clipped photon acquisition')
    heads={}
    for head in ('A','B'):
        cfg=json.loads((ROOT/'examples/head_features.json').read_text());cfg['detector_id']=head
        for item in cfg['channels']:
            item['channel_id']=head+'_'+item['channel_id']
            for k in ('readout','gate'):item[k]=str(ROOT/'examples'/item[k])
        hp=out/(head+'.json');write_json(hp,cfg)
        heads[head]=analyze_head(out/'response/dataset',hp,out/head)
    clock=json.loads((out/'A/singles.json').read_text())['response_head']['clock_id']
    cfg={'schema_version':1,'provenance':'Uncalibrated ideal pair integration check; no energy selection',
         'clock_id':clock,'half_window_ns':20,'detector_pairs':[['A','B']],
         'min_charge_pC':0,'max_charge_pC':None,'reject_truncated':True,'reject_saturated':True,'max_pairs':100000,
         'inputs':[{'detector_id':h,'singles':h+'/singles.csv','manifest':h+'/singles.json','time_offset_ns':0} for h in ('A','B')]}
    cc=out/'coincidence.json';write_json(cc,cfg);coinc=select(cc,out/'pairs')
    steps=rows(files['steps']);ev=rows(files['events'])
    if len(ev)!=events:raise ValueError('Invalid event count')
    if any(float(e['crystal_edep_keV'])>1022+1e-6 for e in ev):raise ValueError('Energy accounting exceeds source')
    # Truth is descriptive only; no requirement for full absorption or both-head detection.
    deposits={h:sum(float(s['edep_keV']) for s in steps if '/'+h+'_crystal[' in s['crystal_path']) for h in ('A','B')}
    report={'schema_version':1,'complete':True,'events':events,'primary_gammas':len(primary),
            'source':'Two simultaneous directed 511 keV primaries at origin, +Z/-Z; no positron transport, decay, acollinearity or isotropic acceptance',
            'geometry_sha256':digest(geometry.read_bytes()),'edep_keV_by_head':deposits,
            'arrivals':{c['channel_id']:c['totals']['arrivals'] for c in response['channels']},
            'head_singles':{h:r['n_valid_pairs'] for h,r in heads.items()},
            'n_coincidences':coinc['n_coincidences'],'n_ambiguous_pairs':coinc['n_ambiguous_pairs'],
            'limitations':'Noiseless integration check; uncalibrated 20 ns half-windows, no energy cut or DOI; counts are not sensitivity/CTR estimates'}
    write_json(out/'report.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('executable',type=Path)
    p.add_argument('--output-dir',required=True,type=Path);p.add_argument('--events',type=int,default=32)
    p.add_argument('--geometry',type=Path,help='Alternate GDML preserving this fixture channel/head mapping')
    a=p.parse_args();print(json.dumps(run(a.executable,a.output_dir,a.events,a.geometry),indent=2))
