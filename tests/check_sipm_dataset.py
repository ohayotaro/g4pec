"""Portable response contract independent of crystal geometry and optional truth."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from sipm_dataset import export_dataset, load_channel, canonical, digest
from analyze_sipm import analyze
from readout import readout
from coincidences import select


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.source=self.root/'source'; self.source.mkdir()
        self.output=self.root/'dataset'; self.config=self.source/'export.json'
        self.adc=ROOT/'examples/single_channel_readout.json'
        identity={'dataset_id':'synthetic-transport','run_id':0}
        self.schedule={'state_start_ns':0,'window_start_ns':50,'window_end_ns':1000,
                       'schema_version':1,'transport_identity':identity,'provenance':'Synthetic fixture',
                       'event_offsets':[{'event_id':0,'offset_ns':100}]}
        channels=[]
        for cid,detector,offset in [('a','A',0),('b','B',3),('empty','A',0)]:
            channel='/head_'+detector+'/sipm_'+cid
            hp=self.source/(cid+'_history.csv')
            rows=[] if cid=='empty' else [f'1,10,0.16,False,0,1,photon',f'2,{100+offset},0.16,True,0,2,photon']
            hp.write_text('avalanche_id,time_ns,charge_pC,observed,event_id,track_id,cause\n'+'\n'.join(rows)+('\n' if rows else ''))
            cells=json.loads((ROOT/'examples/single_channel_cells.json').read_text()); cells['channel_path']=channel
            r={'schema_version':1,'model':'synthetic_response_fixture','time_basis':'acquisition_relative_ns',
               'transport_identity':identity,'acquisition':self.schedule, 'parameters':cells,
               'inputs':{'geometry':{'sha256':digest(b'synthetic geometry')}},
               'totals':{'avalanches':int(bool(rows))},'warmup_counts':{'detected':int(bool(rows))},
               'output_hashes':{'history_sha256':digest(hp.read_bytes())}}
            (self.source/(cid+'_response.json')).write_text(json.dumps(r))
            channels.append({'channel_id':cid,'detector_id':detector,'history':hp.name,'response':cid+'_response.json'})
        self.cfg={'schema_version':1,'provenance':'Synthetic contract test, no physical detector claim','channels':channels}
        self.config.write_text(json.dumps(self.cfg))

    def test_portable_replay_matches_legacy_and_survives_truth_removal(self):
        original=readout(self.source/'a_history.csv',self.source/'a_response.json',self.adc,self.root/'legacy')
        m=export_dataset(self.config,self.output,True)
        self.assertEqual(len(m['channels']),3)
        # Move the dataset and remove all original inputs, geometry and optional truth.
        moved=self.root/'moved'; self.output.rename(moved); shutil.rmtree(self.source)
        (moved/'truth.json').unlink()
        result=analyze(moved,'a',self.root/'new',self.adc)
        self.assertEqual(result['n_singles'],original['n_singles'])
        for suffix in ('_singles.csv','_waveform.csv'):
            self.assertEqual((self.root/('new'+suffix)).read_bytes(),(self.root/('legacy'+suffix)).read_bytes())
        self.assertEqual(result['response_dataset']['geometry_sha256'],m['geometry_sha256'])
        _, _, files=load_channel(moved,'a')
        self.assertEqual(files['history'].read_text().splitlines()[0],'avalanche_id,time_ns,charge_pC,observed')
        self.assertNotIn('transport_identity',json.loads(files['response'].read_text()))

    def test_inactive_channels_and_many_channels_per_detector(self):
        m=export_dataset(self.config,self.output)
        self.assertEqual([c['detector_id'] for c in m['channels']],['A','B','A'])
        r=analyze(self.output,'empty',self.root/'empty',self.adc)
        self.assertEqual((r['n_singles'],r['pulse_history_count']),(0,0))
        self.assertFalse((self.output/'truth.json').exists())

    def test_geometry_variants_keep_same_contract_but_distinct_identity(self):
        first=export_dataset(self.config,self.output)
        for cid in ('a','b','empty'):
            p=self.source/(cid+'_response.json'); r=json.loads(p.read_text())
            r['inputs']['geometry']['sha256']=digest(b'U slit rather than segmented crystal')
            p.write_text(json.dumps(r))
        second=export_dataset(self.config,self.root/'other')
        self.assertEqual(first.keys(),second.keys())
        self.assertNotEqual(first['geometry_sha256'],second['geometry_sha256'])
        self.assertEqual(first['channels'][0].keys(),second['channels'][0].keys())
        self.assertEqual(analyze(self.output,'a',self.root/'one',self.adc)['n_singles'],
                         analyze(self.root/'other','a',self.root/'two',self.adc)['n_singles'])

    def test_reject_mixed_geometry_schedule_and_bad_history(self):
        p=self.source/'b_response.json'; original=p.read_text()
        for change in ('geometry','schedule','hash'):
            r=json.loads(original)
            if change=='geometry': r['inputs']['geometry']['sha256']=digest(b'other')
            elif change=='schedule': r['acquisition']['event_offsets'][0]['offset_ns']=101
            else: r['output_hashes']['history_sha256']='wrong'
            p.write_text(json.dumps(r))
            with self.assertRaises(ValueError): export_dataset(self.config,self.output)
            self.assertFalse(self.output.exists())
        p.write_text(original)
        self.cfg['channels'][1]['channel_id']='a'; self.config.write_text(json.dumps(self.cfg))
        with self.assertRaises(ValueError): export_dataset(self.config,self.output)

    def test_hash_context_and_overwrite_protection(self):
        export_dataset(self.config,self.output)
        with self.assertRaises(FileExistsError): export_dataset(self.config,self.output)
        with self.assertRaises(ValueError): load_channel(self.output,'unknown')
        p=self.output/'manifest.json'; m=json.loads(p.read_text())
        m['channels'][0]['detector_id']='wrong'; p.write_text(json.dumps(m))
        with self.assertRaises(ValueError): load_channel(self.output,'a')
        m['channels'][0]['detector_id']='A'; p.write_text(json.dumps(m))
        hp=self.output/m['channels'][0]['history']['path']; hp.write_text(hp.read_text()+'\n')
        with self.assertRaises(ValueError): load_channel(self.output,'a')

    def test_post_analysis_to_coincidences_and_wrong_geometry_guard(self):
        m=export_dataset(self.config,self.output)
        for cid in ('a','b'): analyze(self.output,cid,self.root/cid,self.adc)
        config=json.loads((ROOT/'examples/coincidence/config.json').read_text())
        config['clock_id']=m['clock']['clock_id']; config['min_charge_pC']=0
        for item in config['inputs']:
            cid=item['detector_id'].lower(); item.update(singles=cid+'_singles.csv',manifest=cid+'_readout.json',time_offset_ns=0)
        p=self.root/'coincidence.json'; p.write_text(json.dumps(config))
        self.assertEqual(select(p,self.root/'pairs')['n_coincidences'],1)
        rp=self.root/'b_readout.json'; r=json.loads(rp.read_text())
        r['response_dataset']['geometry_sha256']=digest(b'wrong geometry'); rp.write_text(json.dumps(r))
        with self.assertRaises(ValueError): select(p,self.root/'bad')


if __name__=='__main__': unittest.main()
