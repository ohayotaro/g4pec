"""Small scintillation integration smoke check; no fitted performance assertions."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as d:
    output=Path(d)/'study'
    result=subprocess.run([sys.executable,str(ROOT/'studies/dual_sipm_response.py'),sys.argv[1],
                           '--output-dir',str(output),'--events','2'],
                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=150)
    assert result.returncode==0,result.stdout[-8000:]
    report=json.loads((output/'report.json').read_text())
    assert report['complete'] and len(report['cases'])==10
    for off,on in zip(report['cases'][::2],report['cases'][1::2]):
        assert off['transport_photons_sha256']==on['transport_photons_sha256']
        assert off['arrivals']==on['arrivals']
        assert all(n>0 for n in off['arrivals'].values())
    for manifest in output.glob('*/*_head/*_readout.json'):
        assert json.loads(manifest.read_text())['n_saturated_samples']==0
    print('Five positions, two noise modes: transport-to-head-feature smoke check passed')
