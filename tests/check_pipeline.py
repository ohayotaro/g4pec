"""End-to-end optical transport and independently replayable readout checks."""
import csv
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

exe, root = Path(sys.argv[1]), Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("digitize", root / "tools/digitize.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


with tempfile.TemporaryDirectory(prefix="g4pec-test-") as directory:
    tmp = Path(directory)

    def simulate(name, geometry, macro):
        result = subprocess.run([str(exe), str(geometry), str(macro), str(tmp / name)],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=90)
        if result.returncode or "GeomVol1002" in result.stdout or "COMMAND NOT FOUND" in result.stdout:
            raise AssertionError(result.stdout[-12000:])
        return tmp / (name + "_run0_photons.csv"), tmp / (name + "_run0_events.csv")

    def truth_check(name, photons, events):
        base = tmp / (name + "_run0")
        manifest = json.loads(Path(str(base) + "_manifest.json").read_text())
        placements = {r["placement_path"]: r for r in rows(Path(str(base) + "_placements.csv"))}
        tracks = rows(Path(str(base) + "_tracks.csv"))
        steps = rows(Path(str(base) + "_steps.csv"))
        event_map = {r["event_id"]: r for r in rows(events)}
        track_map = {(r["event_id"], r["track_id"]): r for r in tracks}
        assert len(track_map) == len(tracks), "Suspended tracks must not duplicate truth identities"
        for r in tracks + steps + rows(photons) + list(event_map.values()):
            assert r["dataset_id"] == manifest["dataset_id"]
            assert int(r["run_id"]) == manifest["run_id"] == 0
            assert r["event_id"] in event_map
        for r in tracks:
            if int(r["parent_id"]):
                assert (r["event_id"], r["parent_id"]) in track_map
        for h in rows(photons):
            track = track_map[h["event_id"], h["track_id"]]
            assert h["parent_id"] == track["parent_id"]
            assert placements[h["channel_path"]]["role"] == "sensor"
        counts = {e: 0 for e in event_map}
        deposits = {e: [] for e in event_map}
        for r in steps:
            assert (r["event_id"], r["track_id"]) in track_map
            placement = placements[r["crystal_path"]]
            assert placement["role"] == "crystal"
            assert float(r["edep_keV"]) >= 0
            assert float(r["post_time_ns"]) >= float(r["pre_time_ns"])
            counts[r["event_id"]] += 1
            deposits[r["event_id"]].append(float(r["edep_keV"]))
            for endpoint in ("pre", "post"):
                for axis in "xyz":
                    world = float(placement[f"t{axis}_mm"]) + sum(
                        float(placement[f"r{axis}{j}"]) * float(r[f"{endpoint}_local_{j}_mm"])
                        for j in "xyz")
                    assert math.isclose(world, float(r[f"{endpoint}_world_{axis}_mm"]), abs_tol=1e-8)
        for e, r in event_map.items():
            assert int(r["n_crystal_steps"]) == counts[e]
            assert math.isclose(float(r["crystal_edep_keV"]), math.fsum(deposits[e]), abs_tol=1e-8)
        return manifest, placements, tracks, steps

    geometry = root / "examples/single_detector.gdml"
    tree = ET.parse(geometry)
    world = tree.find("./structure/volume[@name='World']")
    sensors = [p for p in world.findall("physvol") if p.get("name") == "sipm"]
    assert len(sensors) == 1, "The minimum example must have exactly one SiPM channel"
    photons, events = simulate("optical", geometry, root / "examples/optical.mac")
    hits, event_rows = rows(photons), rows(events)
    assert len(hits) == 100 and len(event_rows) == 100
    assert all(h["channel_path"].endswith("/sipm[0]") for h in hits)
    assert all(abs(float(h["local_x_mm"])) < 1e-9 for h in hits)
    assert all(abs(float(h["local_y_mm"])) < 1e-9 for h in hits)
    assert all(float(h["time_ns"]) > 0 for h in hits)
    assert all(int(r["n_arrivals"]) == 1 for r in event_rows)
    optical_manifest, _, _, optical_steps = truth_check("optical", photons, events)
    assert optical_steps == []
    replay_photons, replay_events = photons, events
    cell_config = json.loads((root / "examples/single_channel_cells.json").read_text())
    cell_config["pde"] = 1
    cell_config_path = tmp / "cells_pde1.json"
    cell_config_path.write_text(json.dumps(cell_config))

    def cell_replay(name, geometry, photons, events, configuration=cell_config_path):
        prefix = tmp / name
        result = subprocess.run(
            [sys.executable, str(root / "tools/digitize_cells.py"), str(photons), str(events), str(prefix),
             "--config", str(configuration), "--geometry", str(geometry), "--seed", "42"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        assert result.returncode == 0, result.stdout
        return prefix

    prefix = cell_replay("optical_cells", geometry, photons, events)
    cell_hits = rows(Path(str(prefix) + "_avalanches.csv"))
    assert len(cell_hits) == 100
    assert all(int(h["cell_id"]) == 58 * 116 + 58 for h in cell_hits)
    assert all(float(h["recovery_fraction"]) == 1 for h in cell_hits)
    # Analytical time of flight: 0.01 mm through constant-index (1.46) glass.
    assert all(math.isclose(float(h["time_ns"]), 0.01 * 1.46 / 299.792458,
                            rel_tol=1e-8) for h in hits)

    optical_text = (root / "examples/optical.mac").read_text()
    for name, position, direction in [
        ("rear", "0 0 5.21", "0 0 -1"),
        ("side", "3 0 5.15", "-1 0 0"),
    ]:
        macro = tmp / f"{name}.mac"
        macro.write_text(optical_text.replace("0 0 5.09", position)
                         .replace("/gps/direction 0 0 1", f"/gps/direction {direction}")
                         .replace("/gps/polarization 1 0 0", "/gps/polarization 0 1 0"))
        photons, events = simulate(name, geometry, macro)
        assert rows(photons) == [], f"{name} illumination must not generate arrivals"
        assert len(rows(events)) == 100
        assert all(int(r["n_arrivals"]) == 0 for r in rows(events))

    # Turn the entire detector by 180 degrees around Y, then translate by +7 mm X.
    rotated_tree = ET.parse(geometry)
    rotated_world = rotated_tree.find("./structure/volume[@name='World']")
    for index, placement in enumerate(rotated_world.findall("physvol")):
        position = placement.find("position")
        position.set("x", str(7 - float(position.get("x"))))
        position.set("z", str(-float(position.get("z"))))
        ET.SubElement(placement, "rotation", name=f"turn{index}", unit="deg", x="0", y="180", z="0")
    rotated_geometry = tmp / "rotated.gdml"
    rotated_tree.write(rotated_geometry)
    rotated_macro = tmp / "rotated.mac"
    rotated_macro.write_text(optical_text.replace("0 0 5.09", "5.75 0 -5.09")
                            .replace("/gps/direction 0 0 1", "/gps/direction 0 0 -1"))
    photons, events = simulate("rotated", rotated_geometry, rotated_macro)
    assert len(rows(photons)) == 100
    for hit in rows(photons):
        assert math.isclose(float(hit["local_x_mm"]), 1.25, abs_tol=1e-8)
        assert math.isclose(float(hit["local_z_mm"]), -0.05, abs_tol=1e-8)
        assert math.isclose(float(hit["local_dz"]), 1, abs_tol=1e-8)
    _, placements, _, _ = truth_check("rotated", photons, events)
    sensor = placements["/World_PV[0]/sipm[0]"]
    assert math.isclose(float(sensor["tx_mm"]), 7, abs_tol=1e-8)
    assert math.isclose(float(sensor["rxx"]), -1, abs_tol=1e-8)
    prefix = cell_replay("rotated_cells", rotated_geometry, photons, events)
    cell_hits = rows(Path(str(prefix) + "_avalanches.csv"))
    assert len(cell_hits) == 100
    assert all(int(h["cell_id"]) == 58 * 116 + 83 for h in cell_hits)

    # Invalid readout definitions fail at initialization, before producing output.
    for name in ("missing_entrance", "double_pde"):
        invalid = ET.parse(geometry)
        if name == "missing_entrance":
            structure = invalid.find("structure")
            structure.remove(structure.find("bordersurface"))
            expected = "no incoming collector border"
        else:
            invalid.find("./define/matrix[@name='collectorEfficiency']").set(
                "values", "2*eV 0.3 4*eV 0.3")
            expected = "EFFICIENCY=1"
        path = tmp / f"{name}.gdml"
        invalid.write(path)
        result = subprocess.run([str(exe), str(path), str(root / "examples/optical.mac"), str(tmp / name)],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
        assert result.returncode != 0 and expected in result.stdout, result.stdout[-4000:]
        assert not (tmp / f"{name}_run0_photons.csv").exists()

    for pde in (0, 1):
        prefix = tmp / f"pde{pde}"
        signals = module.digitize(replay_photons, replay_events, prefix, pde=pde)
        assert sum(s["count"] for s in signals.values()) == 100 * pde
        assert len(rows(Path(str(prefix) + "_events.csv"))) == 100
        for signal in rows(Path(str(prefix) + "_signals.csv")):
            assert math.isclose(float(signal["charge_pC"]), 0.1602176634)
    for name in ("seed_a", "seed_b"):
        module.digitize(replay_photons, replay_events, tmp / name, seed=42)
    assert (tmp / "seed_a_signals.csv").read_bytes() == (tmp / "seed_b_signals.csv").read_bytes()
    try:
        module.digitize(replay_photons, replay_events, tmp / "pde1")
        raise AssertionError("Output overwrite was not rejected")
    except FileExistsError:
        pass

    # Channel IDs are defined in GDML, not hard-coded in the application.
    tree = ET.parse(geometry)
    world = tree.find("./structure/volume[@name='World']")
    sensors = [p for p in world.findall("physvol") if p.get("name") == "sipm"]
    sensors[0].set("copynumber", "27")
    single = tmp / "single_channel.gdml"
    tree.write(single)
    photons, events = simulate("changed", single, root / "examples/optical.mac")
    assert len(rows(photons)) == 100
    assert all(h["channel_path"].endswith("/sipm[27]") for h in rows(photons))

    photons, events = simulate("gamma", geometry, root / "examples/gamma.mac")
    gamma_manifest, placements, tracks, steps = truth_check("gamma", photons, events)
    assert gamma_manifest["dataset_id"] != optical_manifest["dataset_id"]
    assert steps and any(float(r["edep_keV"]) > 0 for r in steps)
    assert {p["detector_id"] for p in placements.values() if p["role"] in ("sensor", "crystal")} == {"detector0"}
    primaries = [t for t in tracks if t["parent_id"] == "0"]
    assert len(primaries) == 100
    assert all(t["particle"] == "gamma" and math.isclose(float(t["kinetic_energy_keV"]), 511) for t in primaries)
    event_rows, hits = rows(events), rows(photons)
    assert all(0 <= float(e["crystal_edep_keV"]) <= 511 + 1e-7 for e in event_rows)
    assert len(event_rows) == 100
    assert sum(int(r["scintillation_photons"]) for r in event_rows) > 0
    assert len(hits) > 0
    assert sum(int(r["n_arrivals"]) for r in event_rows) == len(hits)
    assert {h["channel_path"] for h in hits} == {"/World_PV[0]/sipm[0]"}
    assert all(math.isfinite(float(h["time_ns"])) for h in hits)
    prefix = cell_replay("gamma_cells", geometry, photons, events,
                         root / "examples/single_channel_cells.json")
    cell_events = rows(Path(str(prefix) + "_events.csv"))
    cell_hits = rows(Path(str(prefix) + "_avalanches.csv"))
    assert len(cell_events) == 100 and len(cell_hits) > 0
    assert sum(int(e["n_arrivals"]) for e in cell_events) == len(hits)
    assert sum(int(e["n_detected"]) for e in cell_events) == len(cell_hits)
    for e in cell_events:
        assert int(e["n_arrivals"]) == sum(int(e[k]) for k in
                                            ("n_detected", "n_pde_rejected", "n_unavailable"))
    assert all(0 < float(h["recovery_fraction"]) <= 1 for h in cell_hits)
    assert all(0 < float(h["charge_pC"]) <= 0.1602176634 for h in cell_hits)
    response = json.loads(Path(str(prefix) + "_response.json").read_text())
    assert response["transport_identity"] == {k: gamma_manifest[k] for k in ("dataset_id", "run_id")}
    # Replay real transport on a declared shared clock, through both public CLIs.
    timeline = tmp / "timeline.json"
    subprocess.run([sys.executable, str(root / "tools/make_timeline.py"), str(events), str(timeline),
                    "--spacing-ns", "12", "--window-end-ns", "1000000"], check=True, timeout=30)
    continuous = tmp / "continuous"
    subprocess.run([sys.executable, str(root / "tools/digitize_cells.py"), str(photons), str(events),
                    str(continuous), "--config", str(cell_config_path), "--geometry", str(geometry),
                    "--timeline", str(timeline), "--seed", "42"], check=True, timeout=30,
                   stdout=subprocess.PIPE, text=True)
    continuous_hits = rows(Path(str(continuous) + "_avalanches.csv"))
    lookup = {(h["event_id"], h["track_id"]): float(h["time_ns"]) for h in hits}
    times = [float(h["time_ns"]) for h in continuous_hits]
    assert times == sorted(times) and continuous_hits
    for h in continuous_hits:
        assert math.isclose(float(h["time_ns"]), 12*int(h["event_id"]) + lookup[h["event_id"], h["track_id"]], abs_tol=1e-9)
    assert any(float(h["recovery_fraction"]) < 1 for h in continuous_hits)
    # Rotate/translate the gamma source as well: verify nonempty crystal-step transforms.
    gamma_macro = tmp / "rotated_gamma.mac"
    gamma_text = (root / "examples/gamma.mac").read_text()
    gamma_macro.write_text(gamma_text.replace("0 0 -10", "7 0 10")
                          .replace("/gps/direction 0 0 1", "/gps/direction 0 0 -1")
                          .replace("/run/beamOn 100", "/run/beamOn 10"))
    rp, re = simulate("rotated_gamma", rotated_geometry, gamma_macro)
    _, _, _, rotated_steps = truth_check("rotated_gamma", rp, re)
    assert rotated_steps
    # A nested 90-degree placement exercises composition and non-self-inverse rotation.
    nested = ET.parse(geometry)
    nested_world = nested.find("./structure/volume[@name='World']")
    ET.SubElement(nested.find("solids"), "box", name="envelopeBox", x="40", y="40", z="40", lunit="mm")
    envelope = ET.SubElement(nested.find("structure"), "volume", name="Envelope")
    ET.SubElement(envelope, "materialref", ref=nested_world.find("materialref").get("ref"))
    ET.SubElement(envelope, "solidref", ref="envelopeBox")
    for placement in list(nested_world.findall("physvol")):
        nested_world.remove(placement)
        envelope.append(placement)
    parent = ET.SubElement(nested_world, "physvol", name="envelope")
    ET.SubElement(parent, "volumeref", ref="Envelope")
    ET.SubElement(parent, "position", name="envelopePosition", x="7", y="0", z="0", unit="mm")
    ET.SubElement(parent, "rotation", name="envelopeRotation", x="0", y="90", z="0", unit="deg")
    structure = nested.find("structure")
    structure.remove(envelope)
    structure.insert(list(structure).index(nested_world), envelope)
    nested_path = tmp / "nested.gdml"
    nested.write(nested_path)
    nested_macro = tmp / "nested.mac"
    nested_macro.write_text(gamma_text.replace("0 0 -10", "17 0 0")
                           .replace("/gps/direction 0 0 1", "/gps/direction -1 0 0")
                           .replace("/run/beamOn 100", "/run/beamOn 10"))
    np, ne = simulate("nested", nested_path, nested_macro)
    _, nested_placements, _, nested_steps = truth_check("nested", np, ne)
    assert nested_steps
    crystal = next(p for p in nested_placements.values() if p["role"] == "crystal")
    assert "/envelope[0]/" in crystal["placement_path"]
    assert math.isclose(float(crystal["rxz"]), -1, abs_tol=1e-8)

    multi_macro = tmp / "multi.mac"
    multi_macro.write_text(optical_text.replace("/run/beamOn 100", "/run/beamOn 2\n/run/beamOn 2"))
    simulate("multi", geometry, multi_macro)
    first = json.loads((tmp / "multi_run0_manifest.json").read_text())
    second = json.loads((tmp / "multi_run1_manifest.json").read_text())
    assert first["dataset_id"] == second["dataset_id"]
    assert (first["run_id"], second["run_id"]) == (0, 1)
    mixed = subprocess.run(
        [sys.executable, str(root / "tools/digitize_cells.py"),
         str(tmp / "multi_run1_photons.csv"), str(tmp / "multi_run0_events.csv"), str(tmp / "mixed"),
         "--config", str(cell_config_path), "--geometry", str(geometry)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
    assert mixed.returncode != 0 and "different datasets or runs" in mixed.stdout
    assert not (tmp / "mixed_signals.csv").exists()
    print(f"PASS: front/side/rear, transformed GDML, flight time, invalid surfaces, "
          f"PDE endpoints, replay, charge, overwrite, cell-response replay; "
          f"100 gamma events produced {len(hits)} sensor arrivals")
