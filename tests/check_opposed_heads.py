"""Physical gamma-pair pipeline smoke test; no calibrated performance threshold."""
import csv
import json
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'studies'))
from opposed_heads import run

with tempfile.TemporaryDirectory() as d:
    out=Path(d)/'study';report=run(sys.argv[1],out,8)
    assert report['complete'] and report['primary_gammas']==16
    assert set(report['arrivals'])=={'A_left','A_right','B_left','B_right'}
    with (out/'transport_run0_placements.csv').open() as f:
        sensors=[r for r in csv.DictReader(f) if r['role']=='sensor']
    assert len(sensors)==4
    for r in sensors:
        assert abs(float(r['tx_mm'])-6.15)<1e-9
        assert abs(float(r['ty_mm']))==3
        assert float(r['tz_mm'])==(15 if r['detector_id']=='A' else -15)
        # Local Z is the sensor normal: its world direction must be +/-X.
        assert abs(abs(float(r['rxz']))-1)<1e-9
        assert abs(float(r['ryz']))<1e-9 and abs(float(r['rzz']))<1e-9
    registry=json.loads((out/'response/dataset/manifest.json').read_text())
    assert len(registry['channels'])==4
    for head in ('A','B'):
        m=json.loads((out/head/'singles.json').read_text())
        assert m['response_head']['detector_id']==head
        assert m['n_singles']==report['head_singles'][head]
    with (out/'pairs_coincidences.csv').open() as f:
        pairs=list(csv.DictReader(f))
    assert len(pairs)==report['n_coincidences']
    for p in pairs:
        assert p['detector_a']=='A' and p['detector_b']=='B'
        assert -20<=float(p['delta_ns'])<20
        for head,side in [('A','a'),('B','b')]:
            with (out/head/'singles.csv').open() as f:
                singles={r['single_id']:r for r in csv.DictReader(f)}
            assert float(p['time_'+side+'_ns'])==float(singles[p['single_id_'+side]]['time_ns'])
    print('Ideal gamma pair: transport, four SiPMs, two heads and coincidences passed')
