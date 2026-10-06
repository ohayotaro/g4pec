"""Analytic waveform integrals, ADC behavior and truth-independent readout tests."""
from dataclasses import replace
import csv
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from readout import ReadoutConfig, extract_singles, readout, shape
from digitize_cells import digitize
from make_timeline import make_timeline


class ReadoutTests(unittest.TestCase):
    def setUp(self):
        self.config = ReadoutConfig.from_dict(json.loads((ROOT/'examples/single_channel_readout.json').read_text()))

    def area(self, samples):
        return math.fsum((s['analog_mV']-self.config.baseline_mV)*(s['bin_end_ns']-s['bin_start_ns'])
                         for s in samples)/self.config.transimpedance_ohm

    def fraction(self, age):
        if age <= 0: return 0
        r, f = self.config.rise_time_ns, self.config.fall_time_ns
        return (f*(-math.expm1(-age/f))-r*(-math.expm1(-age/r)))/(f-r)

    def test_analytic_area_fractional_bins_and_warmup(self):
        for t, start, end in ((.3, 0, 30.7), (0, 10, 40.2), (2, 0, 1000)):
            with self.subTest(t=t, start=start):
                samples = shape([(t, .16)], start, end, self.config)
                expected = .16*(self.fraction(end-t)-self.fraction(start-t))
                self.assertAlmostEqual(self.area(samples), expected, places=12)
                for s in samples:
                    delta = .16*(self.fraction(s['bin_end_ns']-t)-self.fraction(s['bin_start_ns']-t))
                    self.assertAlmostEqual(s['analog_mV']-20, delta*1000/(s['bin_end_ns']-s['bin_start_ns']), places=10)

    def test_linear_superposition_and_same_time(self):
        a, b = [(3.2, .16)], [(3.2, .1), (7.3, .08)]
        combined = shape(a+b, 0, 200, self.config)
        first, second = shape(a, 0, 200, self.config), shape(b, 0, 200, self.config)
        for c, x, y in zip(combined, first, second):
            self.assertAlmostEqual(c['analog_mV'], x['analog_mV']+y['analog_mV']-20, places=10)

    def test_adc_clipping_and_quantization(self):
        c = replace(self.config, adc_bits=8, adc_lsb_mV=1)
        samples = shape([(0, 100)], 0, 100, c)
        self.assertTrue(any(s['saturated'] for s in samples))
        self.assertTrue(all(0 <= s['adc_code'] <= 255 for s in samples))
        for s in samples:
            if not s['saturated']:
                self.assertLessEqual(abs(s['analog_mV']-s['digitized_mV']), .5+1e-10)
        self.assertTrue(any(s['n_saturated'] > 0 for s in extract_singles(samples, c)))

    def test_adc_only_threshold_time_and_gate_union(self):
        c = replace(self.config, adc_lsb_mV=1, baseline_mV=0, threshold_mV=2, release_mV=1,
                    pre_samples=1, post_samples=1, transimpedance_ohm=1)
        samples = [{'sample_id': i, 'bin_start_ns': i, 'bin_end_ns': i+1, 'time_ns': i+.5,
                    'adc_code': v, 'saturated': False} for i,v in enumerate((0,0,4,0,4,0,0,0))]
        singles = extract_singles(samples, c)
        self.assertEqual(len(singles), 1)
        self.assertEqual(singles[0]['time_ns'], 2.)
        self.assertEqual(singles[0]['n_crossings'], 2)
        self.assertEqual(singles[0]['charge_pC'], 8.)
        self.assertEqual((singles[0]['gate_start_ns'], singles[0]['gate_end_ns']), (1,7))

    def test_empty_and_truncated_acquisition(self):
        self.assertEqual(extract_singles(shape([], 0, 100, self.config), self.config), [])
        singles = extract_singles(shape([(0, 2)], 10, 20, self.config), self.config)
        self.assertEqual(len(singles), 1)
        self.assertTrue(singles[0]['truncated'])
        self.assertEqual(singles[0]['time_ns'], 10.5)

    def test_invalid_config_and_limits(self):
        for changes in ({'rise_time_ns': 0}, {'fall_time_ns': 2}, {'adc_bits': True},
                        {'release_mV': 3}, {'threshold_mV': 1e20}, {'max_samples': 0}):
            with self.assertRaises(ValueError): replace(self.config, **changes)
        for pulses, start, end in (([(100,1)],0,100), ([(0,-1)],0,10), ([],1,1)):
            with self.assertRaises(ValueError): shape(pulses,start,end,self.config)
        with self.assertRaises(ValueError): shape([], 0, 100, replace(self.config, max_samples=10))

    def test_noiseless_history_export_and_full_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            events, photons, cells, timeline, config = [d/n for n in ('events.csv','photons.csv','cells.json','timeline.json','readout.json')]
            events.write_text('event_id,n_arrivals,n_active_channels,dataset_id,run_id\n0,2,1,test,0\n')
            channel = '/World_PV[0]/sipm[0]'
            photons.write_text('event_id,channel_path,track_id,time_ns,photon_energy_eV,local_x_mm,local_y_mm,dataset_id,run_id\n'
                              +f'0,{channel},1,0,3,0,0,test,0\n0,{channel},2,80,3,1,0,test,0\n')
            parameters = json.loads((ROOT/'examples/single_channel_cells.json').read_text()); parameters['pde'] = 1
            cells.write_text(json.dumps(parameters)); config.write_text(json.dumps(self.config.__dict__))
            make_timeline(events, timeline, 12, 300, window_start_ns=10)
            digitize(photons, events, d/'response', cells, ROOT/'examples/single_detector.gdml', 42, timeline)
            history, manifest = d/'response_history.csv', d/'response_response.json'
            result = readout(history, manifest, config, d/'a')
            self.assertEqual(result['pulse_history_count'], 2)
            self.assertGreater(result['n_singles'], 0)
            with (d/'a_waveform.csv').open() as f: first = next(csv.DictReader(f))
            self.assertGreater(float(first['analog_mV']), self.config.baseline_mV)  # Pre-window pulse tail.
            with self.assertRaises(FileExistsError): readout(history, manifest, config, d/'a')
            # Remove all truth attribution columns; update binding, preserving only physical input.
            with history.open() as f: data = list(csv.DictReader(f))
            import hashlib
            with history.open('w', newline='') as f:
                fields = ('avalanche_id','time_ns','charge_pC','observed')
                writer = csv.DictWriter(f, fields, extrasaction='ignore'); writer.writeheader(); writer.writerows(reversed(data))
            response = json.loads(manifest.read_text()); response['output_hashes']['history_sha256'] = hashlib.sha256(history.read_bytes()).hexdigest()
            manifest.write_text(json.dumps(response))
            readout(history, manifest, config, d/'b')
            for suffix in ('waveform','singles'):
                self.assertEqual((d/f'a_{suffix}.csv').read_bytes(), (d/f'b_{suffix}.csv').read_bytes())
            history.write_text(history.read_text().replace('0.1602176634','0.2'))
            with self.assertRaises(ValueError): readout(history, manifest, config, d/'bad')
            self.assertEqual(list(d.glob('bad*')), [])


if __name__ == '__main__':
    unittest.main()
