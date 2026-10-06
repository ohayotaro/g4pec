#!/usr/bin/env python3
"""Known-position electron scintillation -> two SiPMs -> truth-free head features."""
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
from make_timeline import make_timeline
from sipm_dataset import digest,write_json
from bgo_response import rows,summary

POSITIONS=[('x_minus3',(-3,0,0)),('center',(0,0,0)),('x_plus3',(3,0,0)),
           ('z_minus3',(0,0,-3)),('z_plus3',(0,0,3))]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('executable',type=Path);p.add_argument('--output-dir',required=True,type=Path)
    p.add_argument('--events',type=int,default=16)
    a=p.parse_args()
    if not 2<=a.events<=64:p.error('Require 2..64 events per position')
    out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    geometry=ROOT/'examples/dual_sipm_head.gdml'
    macro=out/'source.mac'
    commands=['/control/verbose 0','/run/verbose 0','/event/verbose 0','/tracking/verbose 0',
              '/random/setSeeds 12345 67890','/run/initialize','/gps/particle e-',
              '/gps/energy 100 keV','/gps/pos/type Point','/gps/direction 0 0 1','/gps/time 7 ns']
    for _,pos in POSITIONS:
        commands.extend([f'/gps/pos/centre {pos[0]} {pos[1]} {pos[2]} mm',f'/run/beamOn {a.events}'])
    macro.write_text('\n'.join(commands)+'\n')
    r=subprocess.run([str(a.executable.resolve()),str(geometry),str(macro),str(out/'transport')],
                     stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
    (out/'transport.log').write_text(r.stdout)
    if r.returncode or 'GeomVol1002' in r.stdout or 'COMMAND NOT FOUND' in r.stdout:
        raise RuntimeError(r.stdout[-8000:])
    config=json.loads((ROOT/'examples/dual_sipm_channels.json').read_text())
    noise=json.loads((ROOT/'examples/single_channel_noise.json').read_text())
    report={'schema_version':1,'purpose':'Descriptive position response, not DOI resolution or calibrated energy',
            'events_per_position':a.events,'energy_keV':100,'source_particle':'e-',
            'first_offset_ns':1000,'spacing_ns':10000,'source_time_ns':7,
            'evaluation_prompt_roi_ns':[-1,100],'evaluation_roi_ns':[-1,3000],
            'geometry_sha256':digest(geometry.read_bytes()),'cases':[]}
    for index,(name,pos) in enumerate(POSITIONS):
        directory=out/name;directory.mkdir()
        prefix=out/f'transport_run{index}'
        events=Path(str(prefix)+'_events.csv');photons=Path(str(prefix)+'_photons.csv')
        ev=rows(events)
        if len(ev)!=a.events or any(abs(float(e['crystal_edep_keV'])-100)>1e-6 for e in ev):
            raise ValueError('Unexpected event count or incomplete energy deposition')
        timeline=directory/'timeline.json'
        make_timeline(events,timeline,10000,1000+a.events*10000,first_offset_ns=1000,
                      provenance='Isolated 100 keV electron source position study, not calibrated source activity')
        for mode in ('noiseless','noise'):
            settings=copy.deepcopy(config)
            if mode=='noise':
                for channel in settings['channels']:channel['noise']=noise
            cp=directory/(mode+'_channels.json');write_json(cp,settings)
            response=respond(photons,events,Path(str(prefix)+'_geometry.gdml'),timeline,cp,directory/mode)
            if any(c['totals']['before_window'] or c['totals']['after_window'] for c in response['channels']):
                raise ValueError('Acquisition clips source photons')
            head=analyze_head(directory/mode/'dataset',ROOT/'examples/head_features.json',directory/(mode+'_head'))
            pairs=rows(directory/(mode+'_head/features.csv'));unmatched=rows(directory/(mode+'_head/unmatched.csv'))
            evaluation=[]
            for e in range(a.events):
                t=1007+e*10000
                selected=[f for f in pairs if t-1<=float(f['time_ns'])<t+3000]
                prompt=[f for f in selected if float(f['time_ns'])<t+100 and f['valid']=='True']
                first=min(prompt,key=lambda f:float(f['time_ns'])) if prompt else None
                evaluation.append({'event_id':e,'n_pairs_in_roi':len(selected),'n_valid_prompt_pairs':len(prompt),
                                   'first_prompt_asymmetry':float(first['charge_asymmetry']) if first else None,
                                   'first_prompt_sum_pC':float(first['sum_charge_pC']) if first else None,
                                   'first_prompt_delta_ns':float(first['delta_ns']) if first else None,
                                   'unmatched_in_roi':sum(t-1<=float(f['time_ns'])<t+3000 for f in unmatched)})
            write_json(directory/(mode+'_evaluation.json'),evaluation)
            case={'position':name,'position_mm':pos,'mode':mode,'events':a.events,
                  'arrivals':{c['channel_id']:c['totals']['arrivals'] for c in response['channels']},
                  'transport_photons_sha256':digest(photons.read_bytes()),
                  'response_dataset_id':response['dataset_id'],
                  'n_pairs':head['n_pairs'],'n_valid_pairs':head['n_valid_pairs'],'n_ambiguous_pairs':head['n_ambiguous_pairs'],
                  'n_unmatched':head['n_unmatched'],'events_with_valid_prompt':sum(e['n_valid_prompt_pairs']>0 for e in evaluation),
                  'events_with_multiple_pairs':sum(e['n_pairs_in_roi']>1 for e in evaluation),
                  'conditional_prompt_asymmetry':summary(e['first_prompt_asymmetry'] for e in evaluation if e['first_prompt_asymmetry'] is not None),
                  'conditional_prompt_sum_pC':summary(e['first_prompt_sum_pC'] for e in evaluation if e['first_prompt_sum_pC'] is not None),
                  'conditional_prompt_delta_ns':summary(e['first_prompt_delta_ns'] for e in evaluation if e['first_prompt_delta_ns'] is not None)}
            report['cases'].append(case);write_json(out/'report.json',report)
            print(name,mode,'valid prompt',case['events_with_valid_prompt'],'/',a.events,
                  'asymmetry',case['conditional_prompt_asymmetry']['mean'],flush=True)
    report['complete']=True;write_json(out/'report.json',report)


if __name__=='__main__':main()
