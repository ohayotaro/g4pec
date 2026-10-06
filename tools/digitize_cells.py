#!/usr/bin/env python3
"""Replay one-channel pre-PDE arrivals through an independent cell response."""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import random
import xml.etree.ElementTree as ET

from sipm_cells import CellConfig, Photon, simulate_event
from acquisition import simulate_acquisition
from sipm_noise import NoiseConfig, simulate_noise


def validate_geometry(config, data, select_channel=False):
    """Validate one explicitly placed, numerically sized GDML box sensor.

    Placements may be nested/rotated: arrivals already use sensor-local axes.
    This reads only the response footprint, not optical properties or transforms.
    """
    root = ET.fromstring(data)
    structure = root.find("structure")
    if structure is None:
        raise ValueError("GDML structure is missing")
    volumes = {v.get("name"): v for v in structure.findall("volume")}
    if len(volumes) != len(structure.findall("volume")):
        raise ValueError("Duplicate GDML logical-volume names")
    setups = root.findall("setup")
    setup = root.find("setup[@name='Default']")
    if setup is None:
        if len(setups) != 1:
            raise ValueError("GDML needs a Default setup or exactly one setup")
        setup = setups[0]
    world = setup.find("world")
    if world is None:
        raise ValueError("GDML world reference is missing")
    sensors = []

    def visit(name, path, ancestors):
        if name in ancestors or name not in volumes:
            raise ValueError("Unsupported cyclic, external or assembly GDML hierarchy")
        volume = volumes[name]
        if any(a.get("auxtype") == "Readout" and a.get("auxvalue") == "SiPM"
               for a in volume.findall("auxiliary")):
            sensors.append((path, volume))
        if any(volume.find(tag) is not None for tag in ("replicavol", "paramvol", "divisionvol")):
            raise ValueError("Cell response requires explicit GDML placements")
        siblings = set()
        for placement in volume.findall("physvol"):
            child = placement.find("volumeref")
            placement_name = placement.get("name")
            if child is None or not placement_name or any(c in placement_name for c in "/[]\r\n"):
                raise ValueError("Cell response requires named, internal GDML placements")
            component = f"{placement_name}[{int(placement.get('copynumber', '0'))}]"
            if component in siblings:
                raise ValueError("Ambiguous GDML placement path")
            siblings.add(component)
            visit(child.get("ref"), f"{path}/{component}", ancestors | {name})

    world_name = world.get("ref")
    visit(world_name, f"/{world_name}_PV[0]", set())
    selected = [s for s in sensors if s[0] == config.channel_path]
    if len(selected) != 1 or (not select_channel and len(sensors) != 1):
        raise ValueError("Cell response requires exactly one GDML SiPM matching channel_path")
    solid_ref = selected[0][1].find("solidref")
    solids = root.find("solids")
    if solid_ref is None or solids is None:
        raise ValueError("Sensor solid is missing")
    matches = [solid for solid in solids if solid.get("name") == solid_ref.get("ref")]
    if len(matches) != 1 or matches[0].tag != "box":
        raise ValueError("Cell response currently supports a box sensor only")
    box = matches[0]
    units = {"nm": 1e-6, "um": 1e-3, "mm": 1., "cm": 10., "m": 1000.}
    unit = box.get("lunit", "mm")
    if unit not in units:
        raise ValueError("Supported sensor box units are nm, um, mm, cm and m")
    try:
        width, height = (float(box.get(axis, "nan")) * units[unit] for axis in ("x", "y"))
    except ValueError as error:
        raise ValueError("Sensor box dimensions must be numeric literals") from error
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError("Sensor box dimensions must be finite and positive")
    expected = (-width / 2, width / 2, -height / 2, height / 2)
    actual = (config.grid.x_edges[0], config.grid.x_edges[-1],
              config.grid.y_edges[0], config.grid.y_edges[-1])
    if not all(math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-9) for a, b in zip(actual, expected)):
        raise ValueError("Cell grid must cover the full GDML sensor-local XY box footprint")
    result = {"channel_path": config.channel_path, "width_mm": width, "height_mm": height}
    if select_channel:
        ids = [a.get('auxvalue') for a in selected[0][1].findall('auxiliary') if a.get('auxtype') == 'DetectorID']
        if len(ids) != 1 or not ids[0]:
            raise ValueError('Each selected sensor requires one DetectorID')
        result.update(detector_id=ids[0], geometry_channels=[s[0] for s in sensors])
    return result


def csv_rows(data, required, name):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    header = reader.fieldnames
    if not header or len(set(header)) != len(header) or not set(required).issubset(header):
        raise ValueError(f"Invalid {name} CSV header; required: {', '.join(required)}")
    for row in reader:
        if None in row or any(row.get(key) is None or row[key] == "" for key in required):
            raise ValueError(f"Malformed {name} CSV row {reader.line_num}")
        yield row


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Nonfinite JSON constant: {value}")


def digitize(photons, events, prefix, config_path, geometry_path, seed=12345, timeline_path=None, noise_path=None,
             select_channel=False):
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError("Seed must be an integer in [0, 2**64)")
    base = Path(prefix)
    paths = [Path(str(base) + suffix) for suffix in
             ("_signals.csv", "_avalanches.csv", "_events.csv", "_response.json")]
    if noise_path is not None:
        if timeline_path is None:
            raise ValueError("Noise requires an explicit acquisition timeline")
    if timeline_path is not None:
        paths.extend(Path(str(base) + suffix) for suffix in ("_history.csv", "_channel.csv"))
    if any(path.exists() or path.is_symlink() for path in paths):
        raise FileExistsError("Response output already exists")
    inputs = {"photons": Path(photons), "events": Path(events),
              "config": Path(config_path), "geometry": Path(geometry_path)}
    if timeline_path is not None:
        inputs["timeline"] = Path(timeline_path)
    if noise_path is not None:
        inputs["noise"] = Path(noise_path)
    data = {key: path.read_bytes() for key, path in inputs.items()}
    config = CellConfig.from_dict(json.loads(data["config"], object_pairs_hook=unique_json,
                                            parse_constant=reject_constant))
    footprint = validate_geometry(config, data["geometry"], select_channel)
    expected, arrivals = {}, {}
    active_counts, channel_sets, counts, photon_keys = {}, {}, {}, set()
    identity = None
    identity_mode = None

    def check_identity(row):
        nonlocal identity, identity_mode
        present = ("dataset_id" in row, "run_id" in row)
        if present[0] != present[1]:
            raise ValueError("Incomplete transport identity")
        if identity_mode is None:
            identity_mode = present[0]
        if identity_mode != present[0]:
            raise ValueError("Cannot mix legacy and identified transport rows")
        if present[0]:
            candidate = (row["dataset_id"], row["run_id"])
            if not candidate[0] or candidate[1] is None or int(candidate[1]) < 0:
                raise ValueError("Invalid transport identity")
            if identity is not None and candidate != identity:
                raise ValueError("Transport rows reference different datasets or runs")
            identity = candidate

    for row in csv_rows(data["events"], ("event_id", "n_arrivals", "n_active_channels"), "events"):
        check_identity(row)
        event, count, active = (int(row[k]) for k in ("event_id", "n_arrivals", "n_active_channels"))
        if event < 0 or count < 0 or event in expected or active < 0 or active > count or (not select_channel and active != int(count > 0)):
            raise ValueError("Invalid or duplicate single-channel event accounting")
        expected[event], arrivals[event] = count, []
        active_counts[event], channel_sets[event], counts[event] = active, set(), 0
    required = ("event_id", "channel_path", "track_id", "time_ns", "photon_energy_eV",
                "local_x_mm", "local_y_mm")
    for row in csv_rows(data["photons"], required, "photons"):
        check_identity(row)
        event = int(row["event_id"])
        allowed = footprint['geometry_channels'] if select_channel else [config.channel_path]
        if event not in expected or row["channel_path"] not in allowed:
            raise ValueError("Photon references an unknown event or channel")
        energy = float(row["photon_energy_eV"])
        if not math.isfinite(energy) or energy <= 0:
            raise ValueError("Photon energy must be finite and positive")
        photon = Photon(int(row['track_id']), float(row['time_ns']), float(row['local_x_mm']), float(row['local_y_mm']))
        key = (event, photon.track_id)
        if key in photon_keys:
            raise ValueError('Duplicate collected photon across channels')
        photon_keys.add(key)
        counts[event] += 1; channel_sets[event].add(row['channel_path'])
        if row['channel_path'] == config.channel_path:
            arrivals[event].append(photon)
    if any(counts[e] != expected[e] for e in expected):
        raise ValueError('Photon and event files disagree on arrival counts')
    if any(len(channel_sets[e]) != active_counts[e] for e in expected):
        raise ValueError('Photon and event files disagree on active-channel counts')
    transport_count = sum(expected.values())
    if select_channel:
        expected = {e:len(arrivals[e]) for e in expected}
    if any(len(arrivals[e]) != expected[e] for e in expected):
        raise ValueError("Photon and event files disagree on arrival counts")

    rng = random.Random(seed)
    timeline = None
    history, noise_details = [], None
    excluded, warmup = {}, {}
    if timeline_path is not None:
        timeline = json.loads(data["timeline"], object_pairs_hook=unique_json, parse_constant=reject_constant)
        if noise_path is None:
            responses, excluded, warmup = simulate_acquisition(config, arrivals, rng, timeline, identity, history)
        else:
            noise = NoiseConfig.from_dict(json.loads(data["noise"], object_pairs_hook=unique_json, parse_constant=reject_constant))
            responses, excluded, warmup, history, noise_details = simulate_noise(
                config, arrivals, rng, timeline, identity, noise, seed)
    signals, avalanches, event_rows = [], [], []
    for event in sorted(expected):
        result = responses[event] if timeline is not None else simulate_event(config, arrivals[event], rng)
        count = len(result.avalanches)
        charge = math.fsum(a.charge_pC for a in result.avalanches)
        if not math.isfinite(charge):
            raise ValueError("Event charge overflows the output representation")
        if count:
            signals.append((event, config.channel_path, count,
                            result.avalanches[0].time_ns, charge))
        event_rows.append((event, count, expected[event], result.n_pde_rejected,
                           result.n_unavailable, charge) +
                          ((excluded[event]["before_window"], excluded[event]["after_window"])
                           if timeline is not None else ()))
        for a in result.avalanches:
            avalanches.append((event, config.channel_path, a.time_ns, a.charge_pC,
                               a.cell_id, a.cell_id % config.grid.cells_x,
                               a.cell_id // config.grid.cells_x, a.track_id, "photon", a.recovery_fraction))

    if timeline is not None:
        avalanches.sort(key=lambda row: (row[2], row[0], row[7]))
    if noise_details is not None:
        avalanches = [(h["event_id"], config.channel_path, h["time_ns"], h["charge_pC"],
                       h["cell_id"], h["cell_id"] % config.grid.cells_x, h["cell_id"] // config.grid.cells_x,
                       h["track_id"], h["cause"], h["recovery_fraction"], h["avalanche_id"],
                       h["parent_avalanche_id"], h["root_event_id"], h["root_track_id"])
                      for h in history if h["observed"]]
    manifest = {
        "schema_version": 1, "model": config.model, "model_version": 1,
        "parameters": config.to_dict(), "seed": seed,
        "transport_identity": ({"dataset_id": identity[0], "run_id": int(identity[1])}
                               if identity else None),
        "random_engine": "python.random.Random (MT19937)",
        "python_version": platform.python_version(),
        "time_basis": "independent_event_ns", "initial_state": "fully_charged",
        "pde_reference_plane": "ideal_collector_arrival",
        "pde_recovery_dependence": "constant_when_available",
        "ordering": ["event_id", "time_ns", "track_id"],
        "cell_id_convention": "iy * cells_x + ix; lower-inclusive, upper-exclusive",
        "geometry_footprint": footprint,
        "inputs": {key: {"path": str(path.resolve()), "sha256": hashlib.sha256(data[key]).hexdigest()}
                   for key, path in inputs.items()},
        "totals": {"events": len(expected), "arrivals": sum(expected.values()),
                   "avalanches": len(avalanches), "pde_rejected": sum(r[3] for r in event_rows),
                   "unavailable": sum(r[4] for r in event_rows)},
    }
    if select_channel:
        manifest['channel_selection'] = {'channel_path':config.channel_path, 'transport_arrivals':transport_count,
                                         'accounting':'Full inputs validated; output counts are channel-local'}
    if timeline is not None:
        manifest.update({
            "time_basis": "acquisition_relative_ns",
            "initial_state": "fully_charged_at_state_start_ns",
            "ordering": ["acquisition_time_ns", "event_id", "track_id"],
            "acquisition": timeline, "warmup_counts": warmup,
            "time_conversion": "offset_ns + Geant4 time_ns (including any primary time)",
            "window_convention": "[start, end); warmup [state_start, start)",
            "signal_grouping": "source-event truth attribution, not reconstructed singles",
        })
        manifest["totals"].update({k: sum(x[k] for x in excluded.values())
                                   for k in ("before_window", "after_window")})
    if noise_details is not None:
        manifest.update({"noise": noise_details,
                         "signal_grouping": "photon-trigger-only event diagnostics; all causes in channel/history",
                         "ordering": ["time_ns", "cause_priority", "insertion_sequence"]})
        manifest["totals"]["photon_avalanches"] = sum(r[1] for r in event_rows)
        manifest["totals"]["observed_by_cause"] = {
            cause: sum(h["cause"] == cause and h["observed"] for h in history)
            for cause in ("photon", "dark", "crosstalk", "afterpulse")}
    # No outputs are opened until the complete inputs and model run are valid.
    base.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for path, header, rows in (
            (paths[0], ("event_id", "channel_path", "n_detected", "first_time_ns", "charge_pC"), signals),
            (paths[1], ("event_id", "channel_path", "time_ns", "charge_pC", "cell_id", "cell_x", "cell_y",
                        "track_id", "cause", "recovery_fraction") +
             (("avalanche_id", "parent_avalanche_id", "root_event_id", "root_track_id") if noise_details is not None else ()), avalanches),
            (paths[2], ("event_id", "n_detected", "n_arrivals", "n_pde_rejected", "n_unavailable", "charge_pC") +
             (("n_before_window", "n_after_window") if timeline is not None else ()), event_rows),
        ):
            with path.open("x", newline="", encoding="utf-8") as stream:
                created.append(path)
                writer = csv.writer(stream)
                writer.writerow(header)
                writer.writerows(rows)
        if timeline is not None:
            history_keys = ("avalanche_id", "parent_avalanche_id", "event_id", "track_id", "root_event_id",
                            "root_track_id", "cause", "cell_id", "time_ns", "charge_pC", "recovery_fraction", "observed")
            charge = math.fsum(row[3] for row in avalanches)
            if not math.isfinite(charge):
                raise ValueError("Channel charge overflow")
            for path, header, output_rows in (
                (paths[4], history_keys, ([h[k] for k in history_keys] for h in history)),
                (paths[5], ("channel_path", "window_start_ns", "window_end_ns", "n_avalanches", "charge_pC"),
                 [(config.channel_path, timeline["window_start_ns"], timeline["window_end_ns"], len(avalanches), charge)]),
            ):
                with path.open("x", newline="", encoding="utf-8") as stream:
                    created.append(path)
                    writer = csv.writer(stream)
                    writer.writerow(header)
                    writer.writerows(output_rows)
        if timeline is not None:
            manifest["output_hashes"] = {"history_sha256": hashlib.sha256(paths[4].read_bytes()).hexdigest()}
        with paths[3].open("x", encoding="utf-8") as stream:
            created.append(paths[3])
            json.dump(manifest, stream, indent=2, allow_nan=False)
            stream.write("\n")
    except Exception:
        for path in created:
            path.unlink()
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("photons")
    parser.add_argument("events")
    parser.add_argument("output_prefix")
    parser.add_argument("--config", required=True, help="Versioned response parameter JSON")
    parser.add_argument("--geometry", required=True, help="GDML snapshot used for these arrivals")
    parser.add_argument("--timeline", type=Path, help="Explicit event-origin offsets and acquisition window JSON")
    parser.add_argument("--noise", type=Path, help="Noise configuration JSON; requires --timeline")
    parser.add_argument("--seed", type=int, default=12345)
    args = parser.parse_args()
    try:
        result = digitize(args.photons, args.events, args.output_prefix, args.config, args.geometry, args.seed, args.timeline, args.noise)
    except (ValueError, OSError, ET.ParseError, OverflowError) as error:
        parser.exit(1, f"Cell digitization failed: {error}\n")
    print(json.dumps(result["totals"], sort_keys=True))


if __name__ == "__main__":
    main()
