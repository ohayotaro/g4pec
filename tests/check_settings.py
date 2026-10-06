import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from validate_settings import validate_settings


class SettingsTests(unittest.TestCase):
    def test_user_settings_and_inactive_fields(self):
        report=validate_settings(cells=ROOT/'examples/single_channel_cells.json',
                                 geometry=ROOT/'examples/single_detector.gdml',
                                 readout=ROOT/'examples/single_channel_readout.json',gate=ROOT/'examples/bgo_fixed_gate.json')
        self.assertTrue(report['valid'])
        self.assertEqual(report['inactive_readout_fields'],['pre_samples','post_samples'])
        with tempfile.TemporaryDirectory() as d:
            config=Path(d)/'custom.json'
            values=json.loads((ROOT/'examples/single_channel_readout.json').read_text())
            values['threshold_mV']=5
            config.write_text(json.dumps(values))
            self.assertEqual(validate_settings(readout=config)['settings']['readout']['threshold_mV'],5)
            values['release_mV']=6;config.write_text(json.dumps(values))
            with self.assertRaises(ValueError):validate_settings(readout=config)

    def test_cross_file_identity_and_sample_budget(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);events=d/'events.csv';timeline=d/'timeline.json'
            events.write_text('event_id,n_arrivals,n_active_channels,dataset_id,run_id\n0,0,0,test,0\n')
            t={'schema_version':1,'provenance':'test','transport_identity':{'dataset_id':'test','run_id':0},
               'state_start_ns':0,'window_start_ns':0,'window_end_ns':100,
               'event_offsets':[{'event_id':0,'offset_ns':0}]}
            timeline.write_text(json.dumps(t))
            args=dict(cells=ROOT/'examples/single_channel_cells.json',readout=ROOT/'examples/single_channel_readout.json',
                      timeline=timeline,events=events)
            self.assertEqual(validate_settings(**args)['waveform_samples'],100)
            t['window_end_ns']=1e9;timeline.write_text(json.dumps(t))
            with self.assertRaises(ValueError):validate_settings(**args)
            t['window_end_ns']=100;t['transport_identity']['dataset_id']='other';timeline.write_text(json.dumps(t))
            with self.assertRaises(ValueError):validate_settings(**args)


if __name__=='__main__':unittest.main()
