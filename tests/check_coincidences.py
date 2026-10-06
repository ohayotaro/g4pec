"""Coincidence boundaries, clock correction, multiplicity, truth independence and IO."""
import csv
import hashlib
import json
from pathlib import Path
import random
import shutil
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from coincidences import match_pairs, select, validate_config
from readout import readout


class CoincidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'fixture'
        shutil.copytree(ROOT/'examples/coincidence', self.path)
        self.config = json.loads((self.path/'config.json').read_text())

    def run_selection(self, name='result'):
        (self.path/'config.json').write_text(json.dumps(self.config))
        report = select(self.path/'config.json', self.path/name)
        with (self.path/(name+'_coincidences.csv')).open() as f:
            rows = list(csv.DictReader(f))
        return report, rows

    def test_boundaries_offsets_quality_and_all_pairs(self):
        report, rows = self.run_selection()
        self.assertEqual(report['n_coincidences'], 3)
        self.assertEqual(report['n_ambiguous_pairs'], 2)
        self.assertEqual([(r['single_id_a'],r['single_id_b']) for r in rows], [('1','1'),('1','2'),('3','4')])
        self.assertEqual([float(r['delta_ns']) for r in rows], [3,4,-5])
        self.assertEqual([int(r['matches_a']) for r in rows], [2,2,1])
        self.assertEqual(report['inputs']['A']['rejection_reasons_nonexclusive'], {'truncated':1})
        self.assertEqual(report['inputs']['B']['rejection_reasons_nonexclusive'], {'saturated':1})
        self.assertFalse(report['inputs']['A']['singles_hash_verified'])

    def test_truth_removal_does_not_change_selection(self):
        _, original = self.run_selection()
        for name in ('a_singles.csv','b_singles.csv'):
            p = self.path/name
            with p.open() as f:
                reader = csv.DictReader(f); fields = [k for k in reader.fieldnames if k != 'event_id']
                rows = [{k:r[k] for k in fields} for r in reader]
            with p.open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
        _, without_truth = self.run_selection('without_truth')
        self.assertEqual(original, without_truth)

    def test_randomized_search_matches_bruteforce(self):
        rng = random.Random(42)
        streams = {d: [{'single_id': i+1, 'channel_path': d, 'time_ns': rng.uniform(0,100), 'charge_pC':1}
                       for i in range(90)] for d in ('A','B','C')}
        pairs = [('A','B'),('C','A')]
        actual = match_pairs(streams, pairs, 3.5, 10000)
        expected = {(x,a['single_id'],y,b['single_id']) for x,y in pairs for a in streams[x] for b in streams[y]
                    if -3.5 <= b['time_ns']-a['time_ns'] < 3.5}
        self.assertEqual({(r['detector_a'],r['single_id_a'],r['detector_b'],r['single_id_b']) for r in actual}, expected)
        self.assertEqual(len(actual), len(expected))
        for s in streams.values(): rng.shuffle(s)
        self.assertEqual(actual, match_pairs(streams, list(reversed(pairs)), 3.5, 10000))

    def test_empty_input_streams_are_valid(self):
        # Empty physical responses must remain valid inputs, not efficiency failures.
        for name in ('a','b'):
            path=self.path/(name+'_singles.csv')
            path.write_text(path.read_text().splitlines()[0]+'\n')
            mp=self.path/(name+'_readout.json');m=json.loads(mp.read_text());m['n_singles']=0
            mp.write_text(json.dumps(m))
            report, rows=self.run_selection('empty_'+name)
            self.assertEqual((report['n_coincidences'],rows),(0,[]))

    def test_charge_endpoints_empty_and_output_protection(self):
        self.config.update(min_charge_pC=5,max_charge_pC=5)
        report, _ = self.run_selection(); self.assertEqual(report['n_coincidences'],3)
        before = (self.path/'result_coincidences.csv').read_bytes()
        with self.assertRaises(FileExistsError): self.run_selection()
        self.assertEqual((self.path/'result_coincidences.csv').read_bytes(), before)
        self.config.update(min_charge_pC=6,max_charge_pC=6)
        report, rows = self.run_selection('empty')
        self.assertEqual((report['n_coincidences'],rows), (0,[]))

    def test_invalid_config_pair_budget_and_input_integrity(self):
        for change in ({'half_window_ns':0}, {'half_window_ns':float('nan')},
                       {'detector_pairs':[['A','A']]}, {'detector_pairs':[['A','B'],['B','A']]},
                       {'reject_saturated':1}, {'max_charge_pC':0}):
            with self.assertRaises(ValueError): validate_config(dict(self.config, **change))
        self.config['max_pairs'] = 1
        with self.assertRaises(ValueError): self.run_selection()
        self.assertFalse((self.path/'result_coincidences.csv').exists())
        self.config['max_pairs'] = 10000
        p = self.path/'a_readout.json'; manifest = json.loads(p.read_text())
        manifest['output_hashes'] = {'singles_sha256':'wrong'}; p.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError): self.run_selection()
        manifest.pop('output_hashes'); manifest['n_singles'] = 6; p.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError): self.run_selection()

    def test_duplicate_ids_and_reused_streams(self):
        p = self.path/'a_singles.csv'; raw = p.read_text(); p.write_text(raw.replace('2,/synthetic/A','1,/synthetic/A'))
        with self.assertRaises(ValueError): self.run_selection()
        p.write_text(raw)
        self.config['inputs'][1]['singles'] = 'a_singles.csv'
        with self.assertRaises(ValueError): self.run_selection()

    def test_readout_to_coincidence_pipeline(self):
        # Two independently constructed electrical input streams on a declared test clock.
        # Keep production readout parameters unchanged; do not claim a correlated transport source.
        for detector, t in (('A',100),('B',113)):
            history = self.path/(detector+'_history.csv')
            history.write_text(f'avalanche_id,time_ns,charge_pC,observed\n1,{t},0.16,True\n')
            response = {'schema_version':1, 'time_basis':'acquisition_relative_ns',
                        'acquisition':{'state_start_ns':0,'window_start_ns':0,'window_end_ns':1000},
                        'parameters':{'channel_path':'/synthetic/'+detector}, 'totals':{'avalanches':1},
                        'warmup_counts':{'detected':0}}
            rp = self.path/(detector+'_response.json'); rp.write_text(json.dumps(response))
            prefix = self.path/('pipeline_'+detector)
            readout(history, rp, ROOT/'examples/single_channel_readout.json', prefix)
        self.config['min_charge_pC'] = 0
        for item in self.config['inputs']:
            item['singles'] = 'pipeline_'+item['detector_id']+'_singles.csv'
            item['manifest'] = 'pipeline_'+item['detector_id']+'_readout.json'
        report, rows = self.run_selection()
        self.assertEqual(report['n_coincidences'], 1)
        self.assertAlmostEqual(float(rows[0]['delta_ns']),3)
        self.assertTrue(all(r['singles_hash_verified'] for r in report['inputs'].values()))
        self.assertEqual(report['output_hashes']['coincidences_sha256'],hashlib.sha256((self.path/'result_coincidences.csv').read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
