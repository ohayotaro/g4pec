"""GDML variation preserves response/analysis contracts, irrespective of detection yield."""
import csv
import json
from pathlib import Path
import sys
import tempfile
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'studies'))
from opposed_heads import run


def header(path):
    with path.open() as f:return next(csv.reader(f))


with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);signatures=[];hashes=[]
    for variant in ('baseline','dimensions','slit','optical_material','nonemitting_material'):
        tree=ET.parse(ROOT/'examples/opposed_heads.gdml');xml=tree.getroot()
        if variant=='dimensions':
            xml.find("./solids/box[@name='crystalBox']").set('z','8')
        if variant=='slit':
            solids=xml.find('solids')
            ET.SubElement(solids,'box',name='contractSlit',x='10',y='0.2',z='6',lunit='mm')
            cut=ET.SubElement(solids,'subtraction',name='contractCrystal')
            ET.SubElement(cut,'first',ref='crystalBox');ET.SubElement(cut,'second',ref='contractSlit')
            ET.SubElement(cut,'position',name='contractSlitPos',x='-1',y='2',z='0',unit='mm')
            for name in ('CrystalA','CrystalB'):
                xml.find(f"./structure/volume[@name='{name}']/solidref").set('ref','contractCrystal')
        if variant=='optical_material':
            # Artificial optical variant, not a calibrated named scintillator.
            xml.find("./define/matrix[@name='crystalIndex']").set('values','2*eV 1.8 4*eV 1.8')
            xml.find("./define/matrix[@name='yield']").set('values','4000/MeV')
        if variant=='nonemitting_material':
            # Deterministic zero-response contract case, not a performance comparison.
            xml.find("./define/matrix[@name='yield']").set('values','0/MeV')
            for name in ('crystalIndex','couplingIndex'):
                xml.find(f"./define/matrix[@name='{name}']").set('values','2*eV 1 4*eV 1')
        geometry=root/(variant+'.gdml');tree.write(geometry,encoding='utf-8',xml_declaration=True)
        out=root/variant;report=run(sys.argv[1],out,8,geometry)
        assert report['complete'] and report['primary_gammas']==16
        assert (out/'input.gdml').read_bytes()==geometry.read_bytes()
        manifest=json.loads((out/'response/dataset/manifest.json').read_text())
        channels=manifest['channels']
        assert {c['channel_id'] for c in channels}=={'A_left','A_right','B_left','B_right'}
        assert {c['detector_id'] for c in channels}=={'A','B'}
        signatures.append((manifest['schema_version'],manifest['artifact_type'],
                           sorted((c['channel_id'],c['detector_id'],c['channel_path']) for c in channels),
                           header(out/'A/features.csv'),header(out/'A/singles.csv'),
                           header(out/'B/singles.csv'),header(out/'pairs_coincidences.csv')))
        hashes.append(report['geometry_sha256'])
        for head in ('A','B'):
            m=json.loads((out/head/'singles.json').read_text())
            assert m['response_head']['dataset_id']==manifest['dataset_id']
            assert m['response_head']['geometry_sha256']==manifest['geometry_sha256']
            assert m['response_head']['clock_id']==manifest['clock']['clock_id']
        if variant=='nonemitting_material':
            assert all(n==0 for n in report['arrivals'].values())
            assert report['head_singles']=={'A':0,'B':0} and report['n_coincidences']==0
        print(variant, 'contract passed; descriptive counts:',report['head_singles'],report['n_coincidences'])
    assert all(s==signatures[0] for s in signatures)
    assert len(set(hashes))==len(hashes)
