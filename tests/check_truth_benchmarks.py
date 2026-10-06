"""Known-source coordinates, crystal energy balance and optical ancestry benchmarks."""
import argparse
import csv
import json
import math
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

POSITION_TOL_MM = 1e-8
ENERGY_TOL_KEV = 1e-5


def rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def close(a, b, tolerance):
    assert math.isclose(a, b, rel_tol=0, abs_tol=tolerance), (a, b, tolerance)


def run(exe, root, output):
    # GDML rotations describe frame rotations: y=90 maps local (x,y,z) to (-z,y,x).
    original = root / "examples/single_detector.gdml"
    tree = ET.parse(original)
    for i, placement in enumerate(tree.findall("./structure/volume[@name='World']/physvol")):
        p = placement.find("position")
        x, y, z = (float(p.get(k)) for k in "xyz")
        p.set("x", str(7-z)); p.set("y", str(-3+y)); p.set("z", str(2+x))
        ET.SubElement(placement, "rotation", name=f"truthRotation{i}", x="0", y="90", z="0", unit="deg")
    transformed = output / "transformed.gdml"
    tree.write(transformed)
    summaries = []
    for rotated in (False, True):
        for depth in (-3., 0., 3.):
            name = f"electron_{'rotated' if rotated else 'base'}_{depth:g}"
            # Deliberately off-axis, preventing X/Y swaps from passing trivially.
            local = (0.6, -0.4, depth)
            world = (7-depth, -3.4, 2.6) if rotated else local
            direction = (-1, 0, 0) if rotated else (0, 0, 1)
            summaries.append(check_case(exe, output, name, transformed if rotated else original,
                                        "e-", 10., local, world, direction, 12, rotated))
    summaries.append(check_case(exe, output, "gamma", original, "gamma", 511.,
                                (0.6, -0.4, 0.), (0.6, -0.4, 0.), (0, 0, 1), 64, False))
    report = {"position_tolerance_mm": POSITION_TOL_MM, "energy_tolerance_keV": ENERGY_TOL_KEV,
              "source_seeds": [12345, 67890], "cases": summaries}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def check_case(exe, output, name, geometry, particle, energy, local, world, direction, count, rotated):
    macro = output / f"{name}.mac"
    macro.write_text("\n".join([
        "/control/verbose 0", "/run/verbose 0", "/event/verbose 0", "/tracking/verbose 0",
        "/random/setSeeds 12345 67890", "/run/initialize", f"/gps/particle {particle}",
        f"/gps/energy {energy} keV", "/gps/pos/type Point",
        f"/gps/pos/centre {' '.join(map(str, world))} mm",
        f"/gps/direction {' '.join(map(str, direction))}", "/gps/time 7 ns", f"/run/beamOn {count}", ""]))
    prefix = output / name
    result = subprocess.run([str(exe), str(geometry), str(macro), str(prefix)],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
    (output / f"{name}.log").write_text(result.stdout)
    assert result.returncode == 0 and "GeomVol1002" not in result.stdout, result.stdout[-8000:]
    base = str(prefix) + "_run0"
    tracks = rows(Path(base + "_tracks.csv"))
    steps = rows(Path(base + "_steps.csv"))
    photons = rows(Path(base + "_photons.csv"))
    events = rows(Path(base + "_events.csv"))
    manifest = json.loads(Path(base + "_manifest.json").read_text())
    placements = rows(Path(base + "_placements.csv"))
    crystal = next(p for p in placements if p["role"] == "crystal")
    channel = next(p for p in placements if p["role"] == "sensor")
    assert len(events) == count
    assert len([p for p in placements if p["role"] == "crystal"]) == 1
    assert len([p for p in placements if p["role"] == "sensor"]) == 1
    by_track = {(t["event_id"], t["track_id"]): t for t in tracks}
    assert len(by_track) == len(tracks)
    by_event = {e["event_id"]: [] for e in events}
    steps_by_track = {}
    for s in steps:
        by_event[s["event_id"]].append(s)
        steps_by_track.setdefault((s["event_id"], s["track_id"]), []).append(s)
        assert s["crystal_path"] == crystal["placement_path"]
        # Independent source transform oracle, not just round-tripping exported metadata.
        for endpoint in ("pre", "post"):
            x, y, z = (float(s[f"{endpoint}_local_{k}_mm"]) for k in "xyz")
            expected = (7-z, -3+y, 2+x) if rotated else (x, y, z)
            for axis, value in zip("xyz", expected):
                close(float(s[f"{endpoint}_world_{axis}_mm"]), value, POSITION_TOL_MM)
    max_residual, contained, escaped = 0., 0, 0
    for event in events:
        eid = event["event_id"]
        primaries = [t for t in tracks if t["event_id"] == eid and t["parent_id"] == "0"]
        assert len(primaries) == 1
        primary = primaries[0]
        assert primary["particle"] == particle
        close(float(primary["kinetic_energy_keV"]), energy, ENERGY_TOL_KEV)
        close(float(primary["time_ns"]), 7., 1e-10)
        first = min(steps_by_track[eid, primary["track_id"]], key=lambda s: int(s["step_number"]))
        assert first["step_number"] == "1" and first["entering_crystal"] == "0"
        for axis, v, w in zip("xyz", local, world):
            close(float(primary[f"vertex_{axis}_mm"]), w, POSITION_TOL_MM)
            close(float(first[f"pre_local_{axis}_mm"]), v, POSITION_TOL_MM)
        close(float(first["pre_time_ns"]), 7., 1e-10)
        es = by_event[eid]
        deposited = math.fsum(float(s["edep_keV"]) for s in es)
        incoming = math.fsum(float(s["pre_kinetic_energy_keV"]) for s in es if s["entering_crystal"] == "1")
        outgoing = math.fsum(float(s["post_kinetic_energy_keV"]) for s in es if s["leaving_crystal"] == "1")
        # All primaries start in the crystal. Secondary birth energies are transfers,
        # not new source energy; re-entry is included with its signed boundary flux.
        residual = energy + incoming - outgoing - deposited
        close(residual, 0, ENERGY_TOL_KEV)
        close(float(event["crystal_edep_keV"]), deposited, ENERGY_TOL_KEV)
        assert len(es) == int(event["n_crystal_steps"])
        max_residual = max(max_residual, abs(residual))
        if outgoing <= ENERGY_TOL_KEV:
            contained += 1
            close(deposited, energy, ENERGY_TOL_KEV)
        else:
            escaped += 1
    assert contained > 0, "Fixture must exercise full-energy containment"
    if particle == "gamma":
        assert escaped > 0, "Gamma fixture must exercise escape accounting"
    assert photons, "Fixture must exercise detected-light ancestry"
    max_chain = 0
    creator_counts = {}
    for h in photons:
        assert h["dataset_id"] == manifest["dataset_id"] and h["run_id"] == "0"
        assert h["channel_path"] == channel["placement_path"]
        t = by_track[h["event_id"], h["track_id"]]
        assert t["particle"] == "opticalphoton" and t["creator_process"] in ("Scintillation", "Cerenkov")
        creator = t["creator_process"]
        creator_counts[creator] = creator_counts.get(creator, 0) + 1
        assert t["parent_id"] == h["parent_id"]
        close(float(t["kinetic_energy_keV"])*1000, float(h["photon_energy_eV"]), 1e-9)
        assert float(h["time_ns"]) >= float(t["time_ns"])
        parent_steps = steps_by_track[h["event_id"], t["parent_id"]]
        # Scintillation birth lies on a depositing parent step (not necessarily its endpoint).
        vertex = [float(t[f"vertex_{a}_mm"]) for a in "xyz"]
        def on_deposit(s):
            if (creator == "Scintillation" and float(s["edep_keV"]) <= 0) or float(t["time_ns"]) < float(s["pre_time_ns"]):
                return False
            a = [float(s[f"pre_world_{k}_mm"]) for k in "xyz"]
            b = [float(s[f"post_world_{k}_mm"]) for k in "xyz"]
            delta = [v-u for u, v in zip(a, b)]
            length2 = sum(d*d for d in delta)
            fraction = sum((v-u)*d for v, u, d in zip(vertex, a, delta))/length2 if length2 else 0
            fraction = max(0, min(1, fraction))
            return math.dist(vertex, [u+fraction*d for u, d in zip(a, delta)]) <= POSITION_TOL_MM
        assert any(on_deposit(s) for s in parent_steps), "Photon birth has no matching depositing parent step"
        seen = set()
        while True:
            assert t["track_id"] not in seen, "Cyclic ancestry"
            seen.add(t["track_id"])
            if t["parent_id"] == "0":
                assert t["particle"] == particle
                break
            t = by_track[h["event_id"], t["parent_id"]]
        max_chain = max(max_chain, len(seen))
    return {"name": name, "particle": particle, "energy_keV": energy, "source_local_mm": local,
            "events": count, "contained_events": contained, "escape_events": escaped,
            "max_energy_residual_keV": max_residual, "arrivals_with_verified_ancestry": len(photons),
            "max_ancestry_tracks": max_chain, "arrival_creator_counts": creator_counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        run(args.executable.resolve(), args.root.resolve(), args.output_dir.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="g4pec-truth-") as d:
            run(args.executable.resolve(), args.root.resolve(), Path(d))


if __name__ == "__main__":
    main()
