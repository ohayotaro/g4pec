"""Noiseless limit, Poisson dark attempts, two-cell XT and exponential AP oracles."""
import csv
from dataclasses import replace
import json
import math
from pathlib import Path
import random
import statistics
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from acquisition import simulate_acquisition
from digitize_cells import digitize
from sipm_cells import CellConfig, Grid, Photon
from sipm_noise import NoiseConfig, neighbors, simulate_noise


class NoiseTests(unittest.TestCase):
    def setUp(self):
        self.config = CellConfig.from_dict(json.loads((ROOT / 'examples/single_channel_cells.json').read_text()))
        self.config = replace(self.config, pde=1)
        self.noise = NoiseConfig(1, "Test oracle", 0, 0, 0, 5, 10000)
        self.timeline = {"schema_version": 1, "provenance": "test", "state_start_ns": 0,
                         "window_start_ns": 0, "window_end_ns": 100,
                         "transport_identity": {"dataset_id": "test", "run_id": 0},
                         "event_offsets": [{"event_id": 0, "offset_ns": 0}]}
        self.arrivals = {0: [Photon(1, 0, 0, 0)]}

    def run_noise(self, seed=42):
        return simulate_noise(self.config, self.arrivals, random.Random(seed), self.timeline,
                              ("test", "0"), self.noise, seed)

    def test_zero_noise_matches_reference(self):
        self.config = replace(self.config, pde=.3)
        self.arrivals[0] = [Photon(i+1, i, 0, 0) for i in range(80)]
        expected = simulate_acquisition(self.config, self.arrivals, random.Random(42), self.timeline, ("test", "0"))
        actual = self.run_noise()
        self.assertEqual(actual[:3], expected)
        self.assertTrue(all(h['cause'] == 'photon' for h in actual[3]))

    def test_poisson_dark_attempts_and_no_pde(self):
        self.arrivals = {0: []}
        self.config = replace(self.config, pde=0, grid=Grid(1, 1, 1, 1, -.5, -.5), dead_time_ns=5)
        self.noise = replace(self.noise, dark_rate_hz=2e8)
        counts, accepted = [], 0
        for seed in range(1000):
            *_, history, details = self.run_noise(seed)
            counts.append(details['counts_including_warmup']['dark']['attempts'])
            accepted += len(history)
            self.assertTrue(all(h['event_id'] is None and h['track_id'] is None and h['root_event_id'] is None for h in history))
            self.assertTrue(all(h['recovery_fraction'] > 0 for h in history))
        self.assertLess(abs(statistics.mean(counts)-20), 6*math.sqrt(20/1000))
        self.assertLess(abs(statistics.variance(counts)-20), 6*math.sqrt((20+2*20**2)/999))
        self.assertGreater(accepted, 0)
        self.assertLess(accepted, sum(counts))
        print(f"Poisson attempts: mean={statistics.mean(counts):.6f}, variance={statistics.variance(counts):.6f}; expected=20")

    def test_two_cell_crosstalk_binomial(self):
        self.config = replace(self.config, grid=Grid(2, 1, 1, 1, 0, 0))
        self.noise = replace(self.noise, crosstalk_probability=.4)
        second = 0
        for seed in range(2000):
            history = self.run_noise(seed)[3]
            self.assertIn(len(history), (1, 2))
            if len(history) == 2:
                second += 1
                h = history[1]
                self.assertEqual((h['cell_id'], h['time_ns'], h['parent_avalanche_id']), (1, 0, 1))
                self.assertIsNone(h['event_id'])
                self.assertEqual(h['root_event_id'], 0)
        self.assertLess(abs(second-800), 6*math.sqrt(2000*.4*.6))
        print(f"Two-cell XT: second cell={second}/2000; expected=800/2000")

    def test_afterpulse_delay_and_recovered_charge(self):
        self.config = replace(self.config, grid=Grid(1, 1, 1, 1, -.5, -.5), dead_time_ns=2, recovery_time_ns=10)
        self.noise = replace(self.noise, afterpulse_probability=.4)
        self.timeline['window_end_ns'] = 20
        first, early = 0, 0
        for seed in range(2000):
            history = self.run_noise(seed)[3]
            lookup = {h['avalanche_id']: h for h in history}
            for h in history[1:]:
                parent = lookup[h['parent_avalanche_id']]
                delta = h['time_ns'] - parent['time_ns']
                self.assertGreater(delta, 2)
                self.assertAlmostEqual(h['recovery_fraction'], 1-math.exp(-(delta-2)/10))
                self.assertEqual(h['cell_id'], parent['cell_id'])
                if h['parent_avalanche_id'] == 1:
                    first += 1
                    early += h['time_ns'] <= 8
        for count, end in ((first, 20), (early, 8)):
            probability = .4*(math.exp(-2/5)-math.exp(-end/5))
            self.assertLess(abs(count-2000*probability), 6*math.sqrt(2000*probability*(1-probability)))
        print(f"AP root children: detected={first}/2000, by 8 ns={early}/2000")

    def test_warmup_parent_history_and_clipping(self):
        self.noise = replace(self.noise, afterpulse_probability=.9, afterpulse_time_ns=30)
        self.timeline['window_start_ns'] = 5
        found = False
        for seed in range(30):
            *_, history, details = self.run_noise(seed)
            ids = {h['avalanche_id'] for h in history}
            self.assertTrue(all(h['parent_avalanche_id'] in ids for h in history[1:]))
            self.assertFalse(history[0]['observed'])
            self.assertTrue(all(h['time_ns'] < 100 for h in history))
            if any(h['observed'] and h['parent_avalanche_id'] == 1 for h in history):
                found = True
        self.assertTrue(found)

    def test_validation_budget_and_neighbors(self):
        for changes in ({'dark_rate_hz': -1}, {'afterpulse_time_ns': 0},
                        {'crosstalk_probability': .6, 'afterpulse_probability': .4}, {'max_candidates': True}):
            with self.assertRaises(ValueError):
                replace(self.noise, **changes)
        self.noise = replace(self.noise, max_candidates=1)
        self.arrivals[0].append(Photon(2, 1, 0, 0))
        with self.assertRaises(ValueError):
            self.run_noise()
        self.assertEqual(neighbors(0, Grid(2, 2, 1, 1, 0, 0)), [1, 2])
        self.assertEqual(neighbors(0, Grid(1, 1, 1, 1, 0, 0)), [])

    def test_output_accounting_and_replay(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            events, photons, config, timeline, noise = [directory / n for n in ('events.csv', 'photons.csv', 'config.json', 'timeline.json', 'noise.json')]
            events.write_text('event_id,n_arrivals,n_active_channels,dataset_id,run_id\n0,1,1,test,0\n')
            photons.write_text('event_id,channel_path,track_id,time_ns,photon_energy_eV,local_x_mm,local_y_mm,dataset_id,run_id\n'
                              f'0,{self.config.channel_path},1,0,3,0,0,test,0\n')
            config.write_text(json.dumps(self.config.to_dict()))
            timeline.write_text(json.dumps(self.timeline))
            params = json.loads((ROOT / 'examples/single_channel_noise.json').read_text()); params['dark_rate_hz'] = 1e9
            noise.write_text(json.dumps(params))
            def run(prefix):
                return digitize(photons, events, directory/prefix, config, ROOT/'examples/single_detector.gdml', 42, timeline, noise)
            manifest = run('a'); run('b')
            for suffix in ('avalanches', 'history', 'channel', 'events', 'signals'):
                self.assertEqual((directory/f'a_{suffix}.csv').read_bytes(), (directory/f'b_{suffix}.csv').read_bytes())
            with (directory/'a_avalanches.csv').open() as f: av = list(csv.DictReader(f))
            with (directory/'a_channel.csv').open() as f: channel = next(csv.DictReader(f))
            self.assertEqual(len(av), manifest['totals']['avalanches'])
            self.assertEqual(sum(manifest['totals']['observed_by_cause'].values()), len(av))
            self.assertAlmostEqual(float(channel['charge_pC']), math.fsum(float(h['charge_pC']) for h in av))
            self.assertTrue(all(h['event_id'] == '' for h in av if h['cause'] != 'photon'))
            self.assertEqual(manifest['totals']['photon_avalanches'], 1)
            with self.assertRaises(FileExistsError): run('a')
            params['max_candidates'] = 1; noise.write_text(json.dumps(params))
            with self.assertRaises(ValueError): run('bad')
            self.assertEqual(list(directory.glob('bad*')), [])


if __name__ == '__main__':
    unittest.main()
