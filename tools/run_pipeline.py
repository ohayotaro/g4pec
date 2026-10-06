#!/usr/bin/env python3
"""Configured transport/SiPM/head/coincidence pipeline and response-only replay."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
from sipm_cells import keys, number
from sipm_dataset import parse, label, digest, write_json, load_channel
from digitize_channels import run as respond
from head_features import run as head_features
from coincidences import select, validate_config
from make_timeline import make_timeline


def prepare(config_path):
    path=Path(config_path).resolve();raw=path.read_bytes();cfg=parse(raw)
    keys(cfg,('schema_version','provenance','transport','response','analysis'),'pipeline')
    if type(cfg['schema_version']) is not int or cfg['schema_version']!=1:raise ValueError('Unsupported pipeline schema')
    label(cfg['provenance'])
    analysis=cfg['analysis'];keys(analysis,('heads','coincidence'),'analysis')
    if not isinstance(analysis['heads'],list) or not analysis['heads']:raise ValueError('Require head models')
    prepared=[];seen=set()
    for h in analysis['heads']:
        keys(h,('model','config','time_offset_ns'),'head model')
        if h['model']!='two_sipm_candidate_features_v1':raise ValueError('Unsupported head model')
        number(h['time_offset_ns'],'head time offset')
        hp=path.parent/label(h['config']);hc=parse(hp.read_bytes());det=label(hc['detector_id'])
        if det in seen:raise ValueError('Duplicate head')
        seen.add(det)
        if not isinstance(hc['channels'],list) or len(hc['channels'])!=2:raise ValueError('Two-SiPM model requires exactly two channels')
        files=[]
        for item in hc['channels']:
            entry={}
            for key in ('readout','gate'):
                entry[key]=None if item[key] is None else (hp.parent/label(item[key])).read_bytes()
            files.append(entry)
        prepared.append((h,hc,files,hp.read_bytes()))
    coin=analysis['coincidence']
    if coin is not None:
        candidate=copy.deepcopy(coin)
        if 'inputs' in candidate or 'clock_id' in candidate:raise ValueError('Pipeline binds inputs and clock automatically')
        candidate.update(clock_id='preflight',inputs=[{'detector_id':hc['detector_id'],'singles':f'{i}.csv','manifest':f'{i}.json','time_offset_ns':h['time_offset_ns']} for i,(h,hc,_,_) in enumerate(prepared)])
        validate_config(candidate)
    return path,raw,cfg,prepared


def analyze(dataset,prepared,coin,out):
    # Require complete explicit coverage; never silently drop a third SiPM or a head.
    manifest=parse((Path(dataset)/'manifest.json').read_bytes());expected={}
    for c in manifest['channels']:
        load_channel(dataset,c['channel_id'])
        expected.setdefault(c['detector_id'],set()).add(c['channel_id'])
    specified={hc['detector_id']:{c['channel_id'] for c in hc['channels']} for _,hc,_,_ in prepared}
    if specified!=expected:raise ValueError('Head models must cover every dataset channel exactly, with matching DetectorID')
    out.mkdir(parents=True,exist_ok=False);inputs=[];reports={}
    for i,(h,hc,files,raw) in enumerate(prepared):
        folder=out/f'head_{i:04d}';folder.mkdir();hc=copy.deepcopy(hc)
        (folder/'original_config.json').write_bytes(raw)
        for j,(item,entry) in enumerate(zip(hc['channels'],files)):
            for key,data in entry.items():
                if data is not None:
                    name=f'{j}_{key}.json';(folder/name).write_bytes(data);item[key]=name
        cp=folder/'config.json';write_json(cp,hc)
        reports[hc['detector_id']]=head_features(dataset,cp,folder/'result')
        inputs.append({'detector_id':hc['detector_id'],'singles':f'head_{i:04d}/result/singles.csv',
                       'manifest':f'head_{i:04d}/result/singles.json','time_offset_ns':h['time_offset_ns']})
    result={'schema_version':1,'dataset_id':manifest['dataset_id'],
            'dataset_manifest_sha256':digest((Path(dataset)/'manifest.json').read_bytes()),
            'head_singles':{h:r['n_valid_pairs'] for h,r in reports.items()},'n_coincidences':None}
    if coin is not None:
        config=copy.deepcopy(coin);config.update(clock_id=manifest['clock']['clock_id'],inputs=inputs)
        cp=out/'coincidence.json';write_json(cp,config)
        result['n_coincidences']=select(cp,out/'pairs')['n_coincidences']
    write_json(out/'analysis.json',result);return result


def run(config_path,output,executable=None,dataset=None):
    path,raw,cfg,prepared=prepare(config_path);out=Path(output).resolve()
    if out.exists() or out.is_symlink():raise FileExistsError('Pipeline output exists')
    transport=None
    if dataset is None:
        if executable is None:raise ValueError('Full run requires executable')
        t=cfg['transport'];keys(t,('geometry','macro','run_id','timeline'),'transport')
        if type(t['run_id']) is not int or t['run_id']<0:raise ValueError('Invalid run_id')
        tl=t['timeline'];keys(tl,('spacing_ns','window_start_ns','window_end_ns','first_offset_ns','provenance'),'timeline')
        transport={name:(path.parent/label(t[name])).read_bytes() for name in ('geometry','macro')}
        transport['response']=(path.parent/label(cfg['response'])).read_bytes()
    out.mkdir(parents=True,exist_ok=False)
    try:
        (out/'pipeline.json').write_bytes(raw)
        if dataset is None:
            for key,name in [('geometry','input.gdml'),('macro','source.mac'),('response','channels.json')]:
                (out/name).write_bytes(transport[key])
            result=subprocess.run([str(Path(executable).resolve()),str(out/'input.gdml'),str(out/'source.mac'),str(out/'transport')],
                                  cwd=path.parent,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=300)
            (out/'transport.log').write_text(result.stdout)
            if result.returncode or any(s in result.stdout for s in ('GeomVol1002','COMMAND NOT FOUND','***** Illegal')):
                raise ValueError('Transport failed; inspect transport.log')
            prefix=out/f"transport_run{t['run_id']}";events=Path(str(prefix)+'_events.csv')
            make_timeline(events,out/'timeline.json',**tl)
            respond(Path(str(prefix)+'_photons.csv'),events,Path(str(prefix)+'_geometry.gdml'),
                    out/'timeline.json',out/'channels.json',out/'response')
            dataset=out/'response/dataset'
        result=analyze(Path(dataset).resolve(),prepared,cfg['analysis']['coincidence'],out/'analysis')
        result.update(complete=True,mode='transport' if transport is not None else 'replay',config_sha256=digest(raw))
        if transport is not None:result['input_hashes']={k:digest(v) for k,v in transport.items()}
        write_json(out/'run.json',result);return result
    except Exception as error:
        write_json(out/'failure.json',{'complete':False,'error':str(error)})
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('config',type=Path);p.add_argument('output',type=Path)
    group=p.add_mutually_exclusive_group(required=True);group.add_argument('--executable',type=Path);group.add_argument('--dataset',type=Path)
    a=p.parse_args()
    try:print(json.dumps(run(a.config,a.output,a.executable,a.dataset),indent=2))
    except (ValueError,OSError,KeyError,TypeError,subprocess.SubprocessError) as e:p.exit(1,f'Pipeline failed: {e}\n')
