"""Independent response checks, including exact occupancy mean/variance benchmarks."""
import argparse
import copy
import csv
from dataclasses import replace
import json
import math
from pathlib import Path
import random
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import digitize as ideal
import digitize_cells
from sipm_cells import CellConfig, Grid, Photon, simulate_event


STATISTICS = []


def config(**changes):
    settings = dict(schema_version=1, model="cell_recovery_constant_pde", provenance="Synthetic test",
                    channel_path="/World_PV[0]/sipm[0]", grid=Grid(2, 2, 1, 1, -1, -1),
                    pde=1., gain_electrons=1e6, dead_time_ns=2., recovery_time_ns=10.)
    return CellConfig(**{**settings, **changes})


def photon(track, time, x=-0.5, y=-0.5):
    return Photon(track, time, x, y)


def rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


class CellResponseTests(unittest.TestCase):
    def test_first_photon_and_reset(self):
        for _ in range(2):
            result = simulate_event(config(), [photon(1, 0)], random.Random(42))
            self.assertEqual(len(result.avalanches), 1)
            self.assertEqual(result.avalanches[0].recovery_fraction, 1)
            self.assertAlmostEqual(result.avalanches[0].charge_pC, 0.1602176634, places=14)
        self.assertEqual(simulate_event(config(), [], random.Random(42)).avalanches, [])

    def test_grid_edges(self):
        grid = config().grid
        self.assertEqual(grid.cell_id(-1, -1), 0)
        self.assertEqual(grid.cell_id(0, 0), 3)
        self.assertEqual(grid.cell_id(math.nextafter(0, -1), -0.5), 0)
        for x, y in ((1, 0), (0, 1), (math.nextafter(-1, -2), 0), (0, float("nan"))):
            with self.assertRaises(ValueError):
                grid.cell_id(x, y)
        sample = CellConfig.from_dict(json.loads((ROOT / "examples/single_channel_cells.json").read_text()))
        self.assertEqual(sample.grid.cell_id(0, 0), 58 * 116 + 58)
        with self.assertRaises(ValueError):
            sample.grid.cell_id(2.9, 0)
        digitize_cells.validate_geometry(sample, (ROOT / "examples/single_detector.gdml").read_bytes())

    def test_recovery_dead_time_and_independent_cells(self):
        hits = [photon(5, 12), photon(3, 1), photon(2, 0, 0.5), photon(4, 2), photon(1, 0)]
        result = simulate_event(config(), hits, random.Random(42))
        self.assertEqual([a.track_id for a in result.avalanches], [1, 2, 5])
        self.assertEqual(result.n_unavailable, 2)
        self.assertEqual(result.avalanches[1].recovery_fraction, 1)
        self.assertAlmostEqual(result.avalanches[-1].recovery_fraction, 1 - math.exp(-1), places=14)
        self.assertAlmostEqual(result.avalanches[-1].charge_pC,
                               0.1602176634 * (1 - math.exp(-1)), places=14)

    def test_pde_rejection_does_not_reset_recovery(self):
        class Trials:
            values = iter([0.1, 0.9, 0.1])
            def random(self):
                return next(self.values)
        result = simulate_event(config(pde=0.5), [photon(1, 0), photon(2, 12), photon(3, 22)], Trials())
        self.assertEqual([a.track_id for a in result.avalanches], [1, 3])
        self.assertEqual(result.n_pde_rejected, 1)
        self.assertAlmostEqual(result.avalanches[-1].recovery_fraction, 1 - math.exp(-2), places=14)

    def test_simultaneous_saturation_and_pde_endpoints(self):
        hits = [photon(i, 0) for i in range(1, 101)]
        one = simulate_event(config(dead_time_ns=0), hits, random.Random(42))
        self.assertEqual(len(one.avalanches), 1)
        self.assertEqual(one.n_unavailable, 99)
        zero = simulate_event(config(pde=0), hits, random.Random(42))
        self.assertEqual(zero.avalanches, [])
        self.assertEqual(zero.n_pde_rejected, 100)
        fully_recovered = simulate_event(config(), [photon(1, 0), photon(2, 500)], random.Random(42))
        self.assertEqual([a.recovery_fraction for a in fully_recovered.avalanches], [1, 1])

    def test_ties_and_duplicate_tracks(self):
        hits = [photon(7, 0), photon(2, 0), photon(5, 15)]
        result = simulate_event(config(), hits, random.Random(42))
        self.assertEqual([a.track_id for a in result.avalanches], [2, 5])
        self.assertEqual(result, simulate_event(config(), list(reversed(hits)), random.Random(42)))
        with self.assertRaises(ValueError):
            simulate_event(config(), [photon(1, 0), photon(1, 10)], random.Random(42))

    def test_invalid_configuration(self):
        for updates in ({"pde": -0.1}, {"pde": 1.1}, {"pde": True}, {"gain_electrons": 0},
                        {"recovery_time_ns": 0}, {"dead_time_ns": -1}, {"gain_electrons": float("inf")},
                        {"schema_version": True}, {"model": "typo"}, {"provenance": ""}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                config(**updates)
        values = config().to_dict()
        values["recovry_time_ns"] = 20
        with self.assertRaises(ValueError):
            CellConfig.from_dict(values)
        with self.assertRaises(ValueError):
            Grid(True, 2, 1, 1, -1, -1)

    def test_occupancy_mean(self):
        # This oracle is the exact fixed-photon multinomial occupancy result,
        # independent of the response implementation's sequential cell history.
        trials, cells = 2000, 16
        for index, (m, pde) in enumerate((m, p) for m in (4, 16, 64) for p in (0.3, 1.)):
            cfg = config(grid=Grid(4, 4, 0.5, 0.5, -1, -1), pde=pde)
            source, response_rng = random.Random(1000 + index), random.Random(2000 + index)
            counts = []
            for _ in range(trials):
                chosen = [source.randrange(cells) for _ in range(m)]
                hits = [photon(i + 1, 0, -0.75 + (cell % 4) * 0.5,
                               -0.75 + (cell // 4) * 0.5) for i, cell in enumerate(chosen)]
                result = simulate_event(cfg, hits, response_rng)
                counts.append(len(result.avalanches))
                self.assertLessEqual(counts[-1], cells)
                self.assertTrue(all(a.recovery_fraction == 1 for a in result.avalanches))
            empty = (1 - pde / cells) ** m
            both_empty = (1 - 2 * pde / cells) ** m
            expected = cells * (1 - empty)
            variance = cells * empty * (1 - empty) + cells * (cells - 1) * (both_empty - empty**2)
            standard_error = math.sqrt(variance / trials)
            observed = sum(counts) / trials
            tolerance = 6 * standard_error + 1 / trials
            self.assertLessEqual(abs(observed - expected), tolerance, (m, pde, observed, expected))
            STATISTICS.append(dict(cells=cells, photons_per_event=m, pde=pde, events=trials,
                                   source_seed=1000 + index, response_seed=2000 + index,
                                   expected_mean=expected, observed_mean=observed,
                                   mean_standard_error=standard_error, acceptance_tolerance=tolerance,
                                   z_score=(observed - expected) / standard_error))


class FileResponseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="g4pec-cells-")
        self.addCleanup(self.temporary.cleanup)
        self.tmp = Path(self.temporary.name)
        self.cfg = config()
        self.config_path = self.tmp / "config.json"
        self.geometry_path = self.tmp / "geometry.gdml"
        tree = ET.parse(ROOT / "examples/single_detector.gdml")
        box = tree.find("./solids/box[@name='sensorBox']")
        box.set("x", "2")
        box.set("y", "2")
        tree.write(self.geometry_path)
        self.photons, self.events = self.tmp / "photons.csv", self.tmp / "events.csv"
        self.hit_rows = [dict(event_id=0, channel_path=self.cfg.channel_path, track_id=1, time_ns=0,
                              photon_energy_eV=2.5, local_x_mm=-0.5, local_y_mm=-0.5)]
        self.event_rows = [dict(event_id=0, n_arrivals=1, n_active_channels=1),
                           dict(event_id=1, n_arrivals=0, n_active_channels=0)]

    def write_inputs(self):
        self.config_path.write_text(json.dumps(self.cfg.to_dict()))
        for path, values in ((self.photons, self.hit_rows), (self.events, self.event_rows)):
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=values[0].keys())
                writer.writeheader()
                writer.writerows(values)

    def run_response(self, prefix="response"):
        return digitize_cells.digitize(self.photons, self.events, self.tmp / prefix,
                                       self.config_path, self.geometry_path, seed=42)

    def test_accounting_manifest_and_overwrite(self):
        self.write_inputs()
        manifest = self.run_response()
        self.assertEqual(manifest["totals"], dict(events=2, arrivals=1, avalanches=1,
                                                 pde_rejected=0, unavailable=0))
        self.assertEqual(manifest["parameters"], self.cfg.to_dict())
        self.assertEqual(len(manifest["inputs"]["geometry"]["sha256"]), 64)
        self.assertEqual([int(r["n_detected"]) for r in rows(self.tmp / "response_events.csv")], [1, 0])
        avalanche = rows(self.tmp / "response_avalanches.csv")[0]
        self.assertEqual((avalanche["cause"], avalanche["cell_id"], avalanche["track_id"]), ("photon", "0", "1"))
        before = (self.tmp / "response_avalanches.csv").read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_response()
        self.assertEqual((self.tmp / "response_avalanches.csv").read_bytes(), before)

    def test_ideal_limit_and_reordered_replay(self):
        self.cfg = config(grid=Grid(20, 20, 0.1, 0.1, -1, -1), pde=0.37)
        self.hit_rows = [dict(event_id=0, channel_path=self.cfg.channel_path, track_id=i + 1, time_ns=i,
                              photon_energy_eV=2.5, local_x_mm=-0.95 + (i % 20) * 0.1,
                              local_y_mm=-0.95 + (i // 20) * 0.1) for i in range(400)]
        self.event_rows[0]["n_arrivals"] = 400
        self.write_inputs()
        self.run_response()
        ideal.digitize(self.photons, self.events, self.tmp / "ideal", pde=0.37, seed=42)
        linear = rows(self.tmp / "ideal_signals.csv")[0]
        detailed = rows(self.tmp / "response_signals.csv")[0]
        self.assertEqual(linear["n_detected"], detailed["n_detected"])
        self.assertEqual(linear["first_time_ns"], detailed["first_time_ns"])
        self.assertAlmostEqual(float(linear["charge_pC"]), float(detailed["charge_pC"]), places=12)
        random.Random(123).shuffle(self.hit_rows)
        self.event_rows.reverse()
        self.write_inputs()
        self.run_response("reordered")
        for suffix in ("_signals.csv", "_avalanches.csv", "_events.csv"):
            self.assertEqual((self.tmp / ("response" + suffix)).read_bytes(),
                             (self.tmp / ("reordered" + suffix)).read_bytes())

    def test_invalid_arrivals_leave_no_output(self):
        original = copy.deepcopy(self.hit_rows)
        for updates in ({"event_id": 4}, {"channel_path": "/wrong[0]"}, {"time_ns": "nan"},
                        {"time_ns": -1}, {"photon_energy_eV": 0}, {"local_x_mm": 1}):
            self.hit_rows = [{**original[0], **updates}]
            self.write_inputs()
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.run_response("invalid/response")
            self.assertFalse((self.tmp / "invalid").exists())
        self.hit_rows = original * 2
        self.event_rows[0]["n_arrivals"] = 2
        self.write_inputs()
        with self.assertRaises(ValueError):
            self.run_response("invalid/response")
        self.assertFalse((self.tmp / "invalid").exists())

    def test_geometry_and_accounting_mismatch(self):
        self.cfg = replace(self.cfg, grid=Grid(2, 2, 0.5, 0.5, -0.5, -0.5))
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, "footprint"):
            self.run_response("invalid/response")
        self.cfg = config()
        self.event_rows[0]["n_arrivals"] = 2
        self.write_inputs()
        with self.assertRaisesRegex(ValueError, "arrival counts"):
            self.run_response("invalid/response")
        self.assertFalse((self.tmp / "invalid").exists())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="New JSON file for analytical comparison results")
    args = parser.parse_args()
    if args.report and args.report.exists():
        parser.error("Report already exists; choose a new path")
    result = unittest.main(argv=[sys.argv[0]], exit=False).result
    if result.wasSuccessful() and args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x") as stream:
            json.dump(dict(model="cell_recovery_constant_pde", tests_run=result.testsRun,
                           acceptance_sigma=6, occupancy_cases=STATISTICS), stream, indent=2)
            stream.write("\n")
    sys.exit(0 if result.wasSuccessful() else 1)
