"""Deterministic acquisition clock, cross-event recovery and window checks."""
import copy
import csv
import json
import math
from pathlib import Path
import random
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from acquisition import simulate_acquisition
from digitize_cells import digitize
from make_timeline import make_timeline
from sipm_cells import CellConfig, Photon, simulate_event


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.params = json.loads((ROOT / "examples/single_channel_cells.json").read_text())
        self.params.update(pde=1, dead_time_ns=2, recovery_time_ns=10)
        self.config = CellConfig.from_dict(self.params)
        self.identity = ("test-dataset", "0")

    def timeline(self, offsets, lower=0, upper=100):
        return {"schema_version": 1, "provenance": "Deterministic test source",
                "transport_identity": {"dataset_id": self.identity[0], "run_id": 0},
                "state_start_ns": 0, "window_start_ns": lower, "window_end_ns": upper,
                "event_offsets": [{"event_id": e, "offset_ns": t} for e, t in offsets.items()]}

    def run_response(self, arrivals, timeline):
        return simulate_acquisition(self.config, arrivals, random.Random(42), timeline, self.identity)

    def photon(self, time=0, track=1, x=0):
        return Photon(track, time, x, 0)

    def test_cross_event_recovery_and_primary_time(self):
        arrivals = {0: [self.photon(7)], 1: [self.photon(7)]}
        responses, _, _ = self.run_response(arrivals, self.timeline({0: 0, 1: 12}))
        a, b = responses[0].avalanches[0], responses[1].avalanches[0]
        self.assertEqual((a.time_ns, b.time_ns), (7, 19))
        self.assertAlmostEqual(b.recovery_fraction, 1-math.exp(-1))
        self.assertEqual(simulate_event(self.config, arrivals[1], random.Random(42)).avalanches[0].recovery_fraction, 1)

    def test_interleaving_overlapping_events(self):
        arrivals = {0: [self.photon(20)], 1: [self.photon()], 2: [self.photon()]}
        r, _, _ = self.run_response(arrivals, self.timeline({0: 0, 1: 10, 2: 22}))
        self.assertEqual(r[1].avalanches[0].recovery_fraction, 1)
        self.assertAlmostEqual(r[0].avalanches[0].recovery_fraction, 1-math.exp(-.8))
        self.assertEqual(r[2].n_unavailable, 1)  # Exactly dead-time boundary.

    def test_simultaneous_across_events_and_independent_cells(self):
        arrivals = {2: [self.photon()], 1: [self.photon()], 0: [self.photon(x=1)]}
        r, _, _ = self.run_response(arrivals, self.timeline({2: 0, 0: 0, 1: 0}))
        self.assertEqual([len(r[e].avalanches) for e in (0, 1, 2)], [1, 1, 0])
        self.assertEqual(r[2].n_unavailable, 1)

    def test_warmup_and_half_open_window(self):
        arrivals = {e: [self.photon()] for e in range(4)}
        r, excluded, warmup = self.run_response(arrivals, self.timeline({0: 0, 1: 12, 2: 20, 3: 21}, 12, 20))
        self.assertEqual(warmup["detected"], 1)
        self.assertAlmostEqual(r[1].avalanches[0].recovery_fraction, 1-math.exp(-1))
        self.assertEqual(excluded[0]["before_window"], 1)
        self.assertEqual(excluded[2]["after_window"], 1)
        self.assertEqual(excluded[3]["after_window"], 1)
        self.assertEqual(sum(len(x.avalanches) for x in r.values()), 1)

    def test_empty_window_and_zero_hit_event(self):
        r, excluded, _ = self.run_response({0: [], 1: [self.photon()]}, self.timeline({0: 0, 1: 20}, 1, 10))
        self.assertEqual(sum(len(x.avalanches) for x in r.values()), 0)
        self.assertEqual(excluded[1]["after_window"], 1)

    def test_invalid_timeline_and_duplicate_tracks(self):
        valid = self.timeline({0: 0})
        invalid = []
        for key, value in (("window_end_ns", 0), ("window_start_ns", -1),
                           ("state_start_ns", 1), ("provenance", ""), ("schema_version", True),
                           ("event_offsets", []), ("event_offsets", [{"event_id": 0, "offset_ns": float('nan')}])):
            t = copy.deepcopy(valid); t[key] = value; invalid.append(t)
        t = copy.deepcopy(valid); t["transport_identity"]["run_id"] = 1; invalid.append(t)
        t = copy.deepcopy(valid); t["event_offsets"] *= 2; invalid.append(t)
        for timeline in invalid:
            with self.subTest(timeline=timeline), self.assertRaises(ValueError):
                self.run_response({0: [self.photon()]}, timeline)
        with self.assertRaises(ValueError):
            self.run_response({0: [self.photon(), self.photon()]}, valid)
        with self.assertRaises(ValueError):
            self.run_response({0: [self.photon(1)]}, self.timeline({0: 1e30}, 0, 1e31))

    def test_cli_files_replay_identity_and_accounting(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            events, photons, config, timeline = [directory / n for n in ("events.csv", "photons.csv", "config.json", "timeline.json")]
            events.write_text("event_id,n_arrivals,n_active_channels,dataset_id,run_id\n0,1,1,test-dataset,0\n1,1,1,test-dataset,0\n2,0,0,test-dataset,0\n")
            head = "event_id,channel_path,track_id,time_ns,photon_energy_eV,local_x_mm,local_y_mm,dataset_id,run_id\n"
            data = [f"{e},{self.config.channel_path},1,7,3,0,0,test-dataset,0\n" for e in (0, 1)]
            photons.write_text(head + ''.join(data))
            config.write_text(json.dumps(self.params))
            make_timeline(events, timeline, 12, 50, window_start_ns=10)
            a = digitize(photons, events, directory / "a", config, ROOT / "examples/single_detector.gdml", 42, timeline)
            self.assertEqual(a["totals"]["before_window"], 1)
            self.assertEqual(a["totals"]["avalanches"], 1)
            self.assertEqual(a["warmup_counts"]["detected"], 1)
            with (directory / "a_events.csv").open() as stream:
                for row in csv.DictReader(stream):
                    self.assertEqual(int(row["n_arrivals"]), sum(int(row[k]) for k in
                        ("n_detected", "n_pde_rejected", "n_unavailable", "n_before_window", "n_after_window")))
            photons.write_text(head + ''.join(reversed(data)))
            digitize(photons, events, directory / "b", config, ROOT / "examples/single_detector.gdml", 42, timeline)
            for suffix in ("events", "signals", "avalanches"):
                self.assertEqual((directory / f"a_{suffix}.csv").read_bytes(), (directory / f"b_{suffix}.csv").read_bytes())
            with self.assertRaises(FileExistsError):
                make_timeline(events, timeline, 12, 50)
            with self.assertRaises(FileExistsError):
                digitize(photons, events, directory / "a", config, ROOT / "examples/single_detector.gdml", 42, timeline)
            bad = json.loads(timeline.read_text()); bad["transport_identity"]["dataset_id"] = "other"
            timeline.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                digitize(photons, events, directory / "bad", config, ROOT / "examples/single_detector.gdml", 42, timeline)
            self.assertEqual(list(directory.glob("bad*")), [])


if __name__ == "__main__":
    unittest.main()
