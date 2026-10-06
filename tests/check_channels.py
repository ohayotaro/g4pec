"""Geant4 two-collector transport -> independent response -> portable analysis."""
import argparse
import copy
import csv
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from digitize_channels import run
from digitize_cells import digitize
from make_timeline import make_timeline
from analyze_sipm import analyze
from sipm_dataset import load_channel


def rows(path):
    with path.open() as f: return list(csv.DictReader(f))


class ChannelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ARGS.output_dir:
            cls.root=ARGS.output_dir.resolve(); cls.root.mkdir(parents=True,exist_ok=False)
        else:
            cls.temp=tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
            cls.root=Path(cls.temp.name)
        cls.geometry=ROOT/'examples/validation/two_collectors.gdml'
        macro=cls.root/'source.mac'
        macro.write_text('\n'.join(['/random/setSeeds 12345 67890','/run/initialize',
            '/gps/particle opticalphoton','/gps/energy 2.5 eV','/gps/polarization 1 0 0',
            '/gps/pos/type Point','/gps/pos/centre 0 0 5.09 mm','/gps/direction 0 0 1',
            '/gps/source/add 1','/gps/particle opticalphoton','/gps/energy 2.5 eV',
            '/gps/polarization 1 0 0','/gps/pos/type Point','/gps/pos/centre 15 0 5.09 mm',
            '/gps/direction 0 0 1','/gps/source/multiplevertex true','/run/beamOn 32','']))
        result=subprocess.run([str(ARGS.executable.resolve()),str(cls.geometry),str(macro),str(cls.root/'transport')],
                              stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
        (cls.root/'transport.log').write_text(result.stdout)
        if result.returncode or 'GeomVol1002' in result.stdout or 'COMMAND NOT FOUND' in result.stdout:
            raise AssertionError(result.stdout[-8000:])
        cls.photons=cls.root/'transport_run0_photons.csv'; cls.events=cls.root/'transport_run0_events.csv'
        cls.timeline=cls.root/'timeline.json'
        make_timeline(cls.events,cls.timeline,12,2000,first_offset_ns=100)
        cls.config=json.loads((ROOT/'examples/validation/two_channels.json').read_text())

    def process(self,name,config=None,photons=None,events=None):
        cp=self.root/(name+'.json'); cp.write_text(json.dumps(config or self.config))
        return run(photons or self.photons,events or self.events,self.geometry,self.timeline,cp,self.root/name)

    def test_transport_recovery_and_portable_replay(self):
        hits=rows(self.photons); events=rows(self.events)
        self.assertEqual(len(hits),64)
        self.assertTrue(all(int(e['n_arrivals'])==2 and int(e['n_active_channels'])==2 for e in events))
        c=copy.deepcopy(self.config)
        for channel in c['channels']: channel['cells']['pde']=1
        result=self.process('recovery',c)
        self.assertEqual([r['totals']['arrivals'] for r in result['channels']],[32,32])
        for cid in ('left','right'):
            _,_,files=load_channel(self.root/'recovery/dataset',cid)
            history=rows(files['history'])
            full=1e6*1.602176634e-7
            self.assertAlmostEqual(float(history[0]['charge_pC']),full,places=12)
            self.assertAlmostEqual(float(history[1]['charge_pC'])/full,1-math.exp(-(12-.001)/30),places=10)
            out=analyze(self.root/'recovery/dataset',cid,self.root/('analysis_'+cid),ROOT/'examples/single_channel_readout.json')
            self.assertGreater(out['n_singles'],0)
            self.assertEqual(out['response_dataset']['detector_id'],'detector0')
        a=rows(load_channel(self.root/'recovery/dataset','left')[2]['history'])
        b=rows(load_channel(self.root/'recovery/dataset','right')[2]['history'])
        self.assertEqual(a,b)  # Identical illumination must not share cell depletion across SiPMs.
        cp=self.root/'legacy_cells.json'; cp.write_text(json.dumps(c['channels'][0]['cells']))
        with self.assertRaises(ValueError):
            digitize(self.photons,self.events,self.root/'legacy',cp,self.geometry)

    def test_noise_reproducibility_and_order_independence(self):
        c=copy.deepcopy(self.config)
        noise=json.loads((ROOT/'examples/single_channel_noise.json').read_text())
        for item in c['channels']: item['noise']=noise
        a=self.process('noise',c); c['channels'].reverse(); b=self.process('reordered',c)
        self.assertEqual(a['channels'],b['channels'])
        self.assertNotEqual(a['channels'][0]['seed'],a['channels'][1]['seed'])
        for cid in ('left','right'):
            h1=load_channel(self.root/'noise/dataset',cid)[2]['history'].read_bytes()
            h2=load_channel(self.root/'reordered/dataset',cid)[2]['history'].read_bytes()
            self.assertEqual(h1,h2)

    def test_empty_channel_kept_and_no_cross_feed(self):
        # Remove right arrivals in a separate deterministic input fixture and recount globally.
        photons=rows(self.photons); left=[r for r in photons if r['channel_path']==self.config['channels'][0]['cells']['channel_path']]
        hp=self.root/'left_only_photons.csv'; ep=self.root/'left_only_events.csv'
        events=rows(self.events)
        for e in events: e['n_arrivals']='1'; e['n_active_channels']='1'
        for p,data in ((hp,left),(ep,events)):
            with p.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=data[0].keys()); w.writeheader(); w.writerows(data)
        result=self.process('empty',photons=hp,events=ep)
        self.assertEqual(result['channels'][1]['totals']['arrivals'],0)
        r=analyze(self.root/'empty/dataset','right',self.root/'empty_analysis',ROOT/'examples/single_channel_readout.json')
        self.assertEqual((r['pulse_history_count'],r['n_singles']),(0,0))

    def test_accounting_and_configuration_fail_without_partial_output(self):
        c=copy.deepcopy(self.config); c['channels'].pop()
        with self.assertRaises(ValueError): self.process('missing',c)
        self.assertFalse((self.root/'missing').exists())
        ep=self.root/'bad_events.csv'; ep.write_text(self.events.read_text().replace(',2,2,',',3,2,'))
        with self.assertRaises(ValueError): self.process('bad_counts',events=ep)
        self.assertFalse((self.root/'bad_counts').exists())

    def test_non_box_crystal_keeps_channel_contract(self):
        # Change only the crystal solid, keeping the direct optical bench inputs/SiPMs.
        tree=ET.parse(self.geometry); root=tree.getroot(); solids=root.find('solids')
        ET.SubElement(solids,'box',name='testSlit',x='0.2',y='12',z='8',lunit='mm')
        cut=ET.SubElement(solids,'subtraction',name='testSlitCrystal')
        ET.SubElement(cut,'first',ref='crystalBox'); ET.SubElement(cut,'second',ref='testSlit')
        ET.SubElement(cut,'position',name='testSlitPos',x='0',y='0',z='1',unit='mm')
        root.find("structure/volume[@name='Crystal']/solidref").set('ref','testSlitCrystal')
        geometry=self.root/'slit_test.gdml'; tree.write(geometry,encoding='utf-8',xml_declaration=True)
        result=subprocess.run([str(ARGS.executable.resolve()),str(geometry),str(self.root/'source.mac'),str(self.root/'slit_transport')],
                              stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
        (self.root/'slit_transport.log').write_text(result.stdout)
        self.assertEqual(result.returncode,0,result.stdout[-4000:]); self.assertNotIn('GeomVol1002',result.stdout)
        timeline=self.root/'slit_timeline.json'
        events=self.root/'slit_transport_run0_events.csv'; photons=self.root/'slit_transport_run0_photons.csv'
        make_timeline(events,timeline,12,2000,first_offset_ns=100)
        cp=self.root/'slit_channels.json'; cp.write_text(json.dumps(self.config))
        result=run(photons,events,geometry,timeline,cp,self.root/'slit_response')
        self.assertEqual([c['totals']['arrivals'] for c in result['channels']],[32,32])
        m,entry,_=load_channel(self.root/'slit_response/dataset','left')
        self.assertEqual(m['artifact_type'],'sipm_response_dataset')
        self.assertEqual(entry['channel_path'],self.config['channels'][0]['cells']['channel_path'])


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('executable',type=Path); p.add_argument('--output-dir',type=Path)
    ARGS=p.parse_args(); unittest.main(argv=[sys.argv[0]])
