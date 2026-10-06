import sys
from pathlib import Path
from dataclasses import replace
import json
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from readout import ReadoutConfig, shape
from fixed_gate import ADCTrace, GateConfig


class FixedGateTests(unittest.TestCase):
    def setUp(self):
        self.c=ReadoutConfig.from_dict(json.loads((ROOT/'examples/single_channel_readout.json').read_text()))
        self.c=replace(self.c,baseline_mV=0,adc_lsb_mV=1,threshold_mV=2,release_mV=1,transimpedance_ohm=1)

    def trace(self,values):
        return ADCTrace([dict(time_ns=i+.5,bin_start_ns=i,bin_end_ns=i+1,adc_code=v) for i,v in enumerate(values)],self.c)

    def test_partial_gate_area(self):
        t=self.trace([0,4,0,0,0])
        s=t.extract(GateConfig(1,'test',1,.25,2))[0]
        self.assertEqual(s['time_ns'],1)
        self.assertEqual((s['gate_start_ns'],s['gate_end_ns']),(.75,2))
        self.assertEqual(s['charge_pC'],4)

    def test_nonextending_holdoff_and_exact_boundary(self):
        t=self.trace([0,4,0,4,0,4,0,0])  # crossings at 1,3,5 ns
        s=t.extract(GateConfig(1,'test',1,0,4))
        self.assertEqual([x['time_ns'] for x in s],[1,5])
        self.assertEqual([x['charge_pC'] for x in s],[4,4])

    def test_no_level_retrigger_and_no_overlap(self):
        t=self.trace([0,4,4,4,4,0,4,0])
        s=t.extract(GateConfig(1,'test',1,1,2))
        self.assertEqual([x['time_ns'] for x in s],[1,6])
        self.assertLessEqual(s[0]['gate_end_ns'],s[1]['gate_start_ns'])

    def test_window_clipping_empty_and_invalid(self):
        self.assertEqual(self.trace([0,0]).extract(GateConfig(1,'test',1,0,1)),[])
        s=self.trace([4,0,0]).extract(GateConfig(1,'test',10,1,11))[0]
        self.assertTrue(s['truncated'])
        self.assertEqual(s['charge_pC'],4)
        with self.assertRaises(ValueError): GateConfig(1,'test',10,1,10)
        with self.assertRaises(ValueError): GateConfig(1,'test',float('nan'),0,10)

    def test_shaped_gate_charge_from_adc_only(self):
        config=replace(self.c,transimpedance_ohm=1000)
        samples=shape([(5.3,.16),(40.7,.16)],0,300,config)
        trace=ADCTrace(samples,config)
        gate=GateConfig(1,'test',60,4,64)
        singles=trace.extract(gate)
        self.assertTrue(singles)
        for s in singles:
            expected=sum(x['adc_code']*max(0,min(x['bin_end_ns'],s['gate_end_ns'])-max(x['bin_start_ns'],s['gate_start_ns'])) for x in samples)
            self.assertAlmostEqual(s['charge_pC'],expected/1000)


if __name__=='__main__': unittest.main()
