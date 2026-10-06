"""Two-SiPM feature definitions, ambiguity, endpoints and truth-free replay."""
import copy
import csv
import json
from pathlib import Path
import random
import shutil
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from head_features import features,run
from sipm_dataset import export_dataset,digest
from coincidences import select


def candidate(i,t,q=1,**extra):
    return dict(single_id=i,time_ns=t,charge_pC=q,channel_path='/test',truncated=False,n_saturated=0,**extra)


class HeadFeatureTests(unittest.TestCase):
    def test_analytic_charge_time_and_window_endpoints(self):
        pairs,unmatched=features([candidate(1,100,3)],[candidate(1,95),candidate(2,105)],5,100)
        self.assertEqual(len(pairs),1);p=pairs[0]
        self.assertEqual((p['sum_charge_pC'],p['charge_asymmetry'],p['delta_ns'],p['time_ns']),(4,.5,-5,97.5))
        self.assertTrue(p['valid']);self.assertEqual(unmatched[0]['single_id'],2)

    def test_ambiguity_no_double_count_hiding_and_unmatched(self):
        pairs,unmatched=features([candidate(1,100),candidate(2,101),candidate(3,300)],
                                 [candidate(1,100),candidate(2,102)],5,100)
        self.assertEqual(len(pairs),4)
        self.assertTrue(all(p['ambiguous'] and not p['valid'] and p['left_matches']==p['right_matches']==2 for p in pairs))
        self.assertEqual([(r['side'],r['single_id']) for r in unmatched],[('left',3)])
        with self.assertRaises(ValueError):features([candidate(1,100)],[candidate(1,100),candidate(2,101)],5,1)

    def test_quality_zero_and_negative_charge(self):
        for left in [candidate(1,100,0),candidate(1,100,-1)]:
            p,_=features([left],[candidate(1,100,0)],5,10)
            self.assertIsNone(p[0]['charge_asymmetry']);self.assertFalse(p[0]['valid'])
        for key,value in [('truncated',True),('n_saturated',1)]:
            left=candidate(1,100);left[key]=value
            p,_=features([left],[candidate(1,100)],5,10)
            self.assertFalse(p[0]['valid']);self.assertFalse(p[0]['ambiguous'])
        with self.assertRaises(ValueError):features([candidate(1,float('nan'))],[],5,10)
        with self.assertRaises(ValueError):features([candidate(1,100),candidate(1,200)],[],5,10)

    def test_truth_and_order_independence(self):
        left=[candidate(1,100),candidate(2,200)];right=[candidate(1,103),candidate(2,204)]
        original=features(left,right,5,10)
        for side in (left,right):
            for c in side:c['event_id']=random.randrange(1000);c['crystal_truth']='arbitrary'
            side.reverse()
        self.assertEqual(features(left,right,5,10),original)

    def fixture(self,root,multi=False):
        source=root/'source';source.mkdir()
        identity={'dataset_id':'synthetic','run_id':0}
        timeline={'state_start_ns':0,'window_start_ns':0,'window_end_ns':1000,'transport_identity':identity}
        channels=[]
        for name,t in [('left',100),('right',103)]+([('bleft',98),('bright',101)] if multi else []):
            hp=source/(name+'.csv');hp.write_text(f'avalanche_id,time_ns,charge_pC,observed,event_id\n1,{t},0.16,True,99\n')
            response={'schema_version':1,'time_basis':'acquisition_relative_ns','transport_identity':identity,
                      'acquisition':timeline,'parameters':{'channel_path':'/test/'+name},
                      'inputs':{'geometry':{'sha256':digest(b'synthetic geometry')}},
                      'totals':{'avalanches':1},'warmup_counts':{'detected':0},
                      'output_hashes':{'history_sha256':digest(hp.read_bytes())}}
            rp=source/(name+'.json');rp.write_text(json.dumps(response))
            channels.append({'channel_id':name,'detector_id':'B' if name.startswith('b') else 'head','response':rp.name,'history':hp.name})
        cp=source/'export.json';cp.write_text(json.dumps({'schema_version':1,'provenance':'test','channels':channels}))
        export_dataset(cp,root/'dataset',True)
        config={'schema_version':1,'provenance':'test','detector_id':'head','half_window_ns':5,'max_pairs':100,
                'channels':[{'channel_id':name,'time_offset_ns':offset,
                             'readout':str(ROOT/'examples/single_channel_readout.json'),'gate':None}
                            for name,offset in [('left',0),('right',-3)]]}
        path=root/'head_config.json';path.write_text(json.dumps(config))
        return path,config

    def test_dataset_pipeline_offsets_and_truth_removal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cp,_=self.fixture(root)
            report=run(root/'dataset',cp,root/'first')
            self.assertEqual((report['n_pairs'],report['n_valid_pairs'],report['n_unmatched']),(1,1,0))
            shutil.rmtree(root/'source');(root/'dataset/truth.json').unlink()
            run(root/'dataset',cp,root/'second')
            self.assertEqual((root/'first/features.csv').read_bytes(),(root/'second/features.csv').read_bytes())
            import csv
            with (root/'first/features.csv').open() as f:r=next(csv.DictReader(f))
            self.assertAlmostEqual(float(r['delta_ns']),0,places=10)
            self.assertAlmostEqual(float(r['charge_asymmetry']),0,places=10)
            with self.assertRaises(FileExistsError):run(root/'dataset',cp,root/'first')

    def test_wrong_head_and_failed_readout_leave_no_output(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cp,c=self.fixture(root)
            bad=copy.deepcopy(c);bad['detector_id']='other';cp.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):run(root/'dataset',cp,root/'bad')
            self.assertFalse((root/'bad').exists())
            bad=copy.deepcopy(c);bad['channels'][1]['readout']='missing.json';cp.write_text(json.dumps(bad))
            with self.assertRaises(OSError):run(root/'dataset',cp,root/'bad')
            self.assertFalse((root/'bad').exists())

    def test_two_head_coincidences_and_provenance_guards(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cp,c=self.fixture(root,multi=True)
            for detector,folder,names in [('head','a',('left','right')),('B','b',('bleft','bright'))]:
                cfg=copy.deepcopy(c);cfg['detector_id']=detector
                for item,name in zip(cfg['channels'],names):item['channel_id']=name
                cp.write_text(json.dumps(cfg));report=run(root/'dataset',cp,root/folder)
                with (root/folder/'singles.csv').open() as f:rows=list(csv.DictReader(f))
                with (root/folder/'features.csv').open() as f:fs=list(csv.DictReader(f))
                self.assertEqual(len(rows),report['n_valid_pairs'])
                self.assertEqual([r['single_id'] for r in rows],[r['feature_id'] for r in fs if r['valid']=='True'])
                self.assertEqual(rows[0]['charge_pC'],fs[0]['sum_charge_pC'])
                self.assertEqual(rows[0]['left_single_id'],fs[0]['left_single_id'])
            # Coincidence replay needs only head outputs: no truth, GDML or dataset.
            shutil.rmtree(root/'source');shutil.rmtree(root/'dataset')
            clock=json.loads((root/'a/singles.json').read_text())['response_head']['clock_id']
            config={'schema_version':1,'provenance':'synthetic four channel contract test','clock_id':clock,
                    'half_window_ns':2,'detector_pairs':[['head','B']],'min_charge_pC':0,'max_charge_pC':None,
                    'reject_truncated':True,'reject_saturated':True,'max_pairs':100,
                    'inputs':[{'detector_id':detector,'singles':folder+'/singles.csv','manifest':folder+'/singles.json',
                               'time_offset_ns':0} for detector,folder in [('head','a'),('B','b')]]}
            cc=root/'coincidence.json';cc.write_text(json.dumps(config))
            report=select(cc,root/'pairs');self.assertEqual(report['n_coincidences'],1)
            with (root/'pairs_coincidences.csv').open() as f:pair=next(csv.DictReader(f))
            self.assertAlmostEqual(float(pair['delta_ns']),-2)
            # Reverse the sign to exercise the exclusive upper endpoint.
            config['inputs'][1]['time_offset_ns']=4;cc.write_text(json.dumps(config))
            self.assertEqual(select(cc,root/'upper')['n_coincidences'],0)
            config['inputs'][1]['time_offset_ns']=0;cc.write_text(json.dumps(config))
            mp=root/'b/singles.json';original=json.loads(mp.read_text())
            for field,value in [('clock_id','wrong'),('dataset_id','wrong'),('geometry_sha256','wrong'),
                                ('detector_id','head'),('channel_ids',['left','right'])]:
                bad=copy.deepcopy(original);bad['response_head'][field]=value;mp.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):select(cc,root/'bad')
                self.assertFalse((root/'bad_coincidences.csv').exists())
            bad=copy.deepcopy(original);bad['output_hashes']={};mp.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):select(cc,root/'bad')
            mp.write_text(json.dumps(original))
            with (root/'b/singles.csv').open('a') as f:f.write('\n')
            with self.assertRaises(ValueError):select(cc,root/'bad')


if __name__=='__main__':unittest.main()
