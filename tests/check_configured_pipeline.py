"""Configured single/two-head execution, portable replay and model coverage guards."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from run_pipeline import run
from sipm_dataset import write_json

with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    for name in ('single_head','opposed'):
        source=ROOT/'examples/pipeline'/f'{name}.json';out=root/name
        result=run(source,out,executable=sys.argv[1]);assert result['complete']
        assert len(result['head_singles'])==(1 if name=='single_head' else 2)
        if name=='single_head':assert result['n_coincidences'] is None
        # All analysis inputs can be relocated with no transport, truth or source settings.
        replay_cfg=json.loads(source.read_text());replay_cfg['transport']=None;replay_cfg['response']=None
        for i,h in enumerate(replay_cfg['analysis']['heads']):
            saved=out/'analysis'/f'head_{i:04d}'
            shutil.copytree(saved,root/f'{name}_settings_{i}',ignore=shutil.ignore_patterns('result'))
            h['config']=f'{name}_settings_{i}/config.json'
        cp=root/f'{name}_replay.json';write_json(cp,replay_cfg)
        dataset=root/f'{name}_dataset';shutil.copytree(out/'response/dataset',dataset)
        (dataset/'truth.json').unlink()
        shutil.rmtree(out/'response');(out/'input.gdml').unlink();(out/'source.mac').unlink()
        replay=root/f'{name}_replay';rerun=run(cp,replay,dataset=dataset)
        assert result['head_singles']==rerun['head_singles']
        assert result['n_coincidences']==rerun['n_coincidences']
        for original in (out/'analysis').rglob('*.csv'):
            assert original.read_bytes()==(replay/'analysis'/original.relative_to(out/'analysis')).read_bytes()
        try:run(cp,replay,dataset=dataset)
        except FileExistsError:pass
        else:raise AssertionError('Output overwrite allowed')
        bad=copy.deepcopy(replay_cfg);bad['analysis']['heads'][0]['model']='unknown'
        bp=root/'bad.json';write_json(bp,bad)
        try:run(bp,root/'bad_model',dataset=dataset)
        except ValueError:pass
        else:raise AssertionError('Unknown model accepted')
        assert not (root/'bad_model').exists()
        if name=='opposed':
            bad=copy.deepcopy(replay_cfg);bad['analysis']['heads'].pop();bad['analysis']['coincidence']=None
            write_json(bp,bad)
            try:run(bp,root/'missing_head',dataset=dataset)
            except ValueError as e:assert 'cover every' in str(e)
            else:raise AssertionError('Missing head accepted')
            assert (root/'missing_head/failure.json').exists()
            assert not (root/'missing_head/analysis').exists()
    # A three-channel head cannot silently select just two channels.
    manifest_path=root/'opposed_dataset/manifest.json';m=json.loads(manifest_path.read_text())
    for c in m['channels']:
        if c['channel_id']=='B_left':c['detector_id']='A'
    write_json(manifest_path,m)
    try:run(root/'opposed_replay.json',root/'third_channel',dataset=root/'opposed_dataset')
    except ValueError:pass
    else:raise AssertionError('Partial head coverage accepted')
    print('Single/two heads, relocated truth-free replay, exact CSV agreement and model guards passed')
