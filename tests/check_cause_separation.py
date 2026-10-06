"""Check causal-study random pairing and non-overlapping evaluation boundaries."""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'studies'))
from bgo_cause_separation import assigned_draws, DrawStream, evaluate
from acquisition import prepare_acquisition, simulate_acquisition
from sipm_cells import CellConfig, Photon
import json


class CauseSeparationTests(unittest.TestCase):
    def test_pde_pairing_survives_reordered_photons(self):
        config = CellConfig.from_dict(json.loads((ROOT/'examples/single_channel_cells.json').read_text()))
        # Distinct cells remove recovery as a confounder. Short spacing interleaves events.
        arrivals = {0: [Photon(1, 0, 0, 0), Photon(2, 100, .1, 0)],
                    1: [Photon(1, 0, .2, 0), Photon(2, 100, .3, 0)]}
        draws = assigned_draws(arrivals, 1)
        expected = {key for key, value in draws.items() if value < config.pde}
        self.assertTrue(expected)
        orders = []
        for spacing in (1000, 10):
            timeline = {'schema_version': 1, 'provenance': 'test',
                        'transport_identity': {'dataset_id': 'test', 'run_id': 0},
                        'state_start_ns': 0, 'window_start_ns': 0, 'window_end_ns': 2000,
                        'event_offsets': [{'event_id': 0, 'offset_ns': 1}, {'event_id': 1, 'offset_ns': spacing+1}]}
            ordered, *_ = prepare_acquisition(config, arrivals, timeline, ('test', 0))
            order = [(e, track) for _,e,track,_,_ in ordered]
            orders.append(order)
            rng = DrawStream(draws[key] for key in order)
            result, _, _ = simulate_acquisition(config, arrivals, rng, timeline, ('test', 0))
            self.assertEqual({(e,h.track_id) for e,r in result.items() for h in r.avalanches}, expected)
            self.assertEqual(rng.used, 4)
        self.assertNotEqual(*orders)

    def test_slots_holdoff_endpoint_and_suppressed_crossing(self):
        metrics, events = evaluate([{'time_ns': 100}, {'time_ns': 200}], [100,200], 100, [100,200])
        self.assertEqual([e['n_candidates'] for e in events], [1,1])
        self.assertEqual(metrics['blocked_events'], 0)  # Holdoff end is eligible.
        _, events = evaluate([{'time_ns': 199}], [100,200], 100, [199])
        self.assertEqual([e['n_candidates'] for e in events], [0,1])
        metrics, events = evaluate([{'time_ns': 100}], [100,200], 101, [100,200.5])
        self.assertTrue(events[1]['blocked_at_source'])
        self.assertEqual(metrics['raw_prompt_crossing_but_no_accepted_prompt'], 1)
        metrics, _ = evaluate([], [100,200], 101, [])
        self.assertEqual(metrics['no_raw_prompt_crossing_events'], 2)


if __name__ == '__main__':
    unittest.main()
