#!/usr/bin/env python3
"""Independent ideal SiPM response: constant PDE and fixed avalanche gain.

Input is a pre-PDE, unit-weight photon arrival stream from an ideal collector.
Each Geant4 event is an independent acquisition; there is no cross-event clock.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import random


def digitize(photons, events, prefix, pde=0.3, gain=1e6, seed=12345):
    if not math.isfinite(pde) or not 0 <= pde <= 1:
        raise ValueError("PDE must be finite and between 0 and 1")
    if not math.isfinite(gain) or gain <= 0:
        raise ValueError("Gain must be finite and positive")
    counts = {}
    with Path(events).open(newline="") as stream:
        for row in csv.DictReader(stream):
            event = int(row["event_id"])
            if event in counts:
                raise ValueError("Duplicate event ID")
            counts[event] = {"expected": int(row["n_arrivals"]), "actual": 0, "detected": 0}
    rng = random.Random(seed)
    signals = {}
    # Kept in memory for this small, event-based MVP.
    avalanches = []
    with Path(photons).open(newline="") as stream:
        for row in csv.DictReader(stream):
            event = int(row["event_id"])
            if event not in counts:
                raise ValueError("Photon references an unknown event")
            counts[event]["actual"] += 1
            time = float(row["time_ns"])
            if not math.isfinite(time) or time < 0:
                raise ValueError("Invalid arrival time")
            if rng.random() >= pde:
                continue
            counts[event]["detected"] += 1
            key = (event, row["channel_path"])
            signal = signals.setdefault(key, {"count": 0, "time": time})
            signal["count"] += 1
            signal["time"] = min(signal["time"], time)
            avalanches.append((event, row["channel_path"], time, gain * 1.602176634e-7))
    if any(c["expected"] != c["actual"] for c in counts.values()):
        raise ValueError("Photon and event files disagree on arrival counts")
    base = Path(prefix)
    outputs = [Path(str(base) + suffix) for suffix in
               ("_signals.csv", "_avalanches.csv", "_events.csv", "_response.json")]
    for path in outputs:
        if path.exists():
            raise FileExistsError(path)
    base.parent.mkdir(parents=True, exist_ok=True)
    with outputs[0].open("x", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["event_id", "channel_path", "n_detected", "first_time_ns", "charge_pC"])
        for (event, channel), signal in sorted(signals.items()):
            writer.writerow([event, channel, signal["count"], signal["time"],
                             signal["count"] * gain * 1.602176634e-7])
    with outputs[1].open("x", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["event_id", "channel_path", "time_ns", "charge_pC"])
        writer.writerows(sorted(avalanches, key=lambda a: (a[0], a[2], a[1])))
    with outputs[2].open("x", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["event_id", "n_detected"])
        writer.writerows((event, c["detected"]) for event, c in sorted(counts.items()))
    with outputs[3].open("x") as stream:
        json.dump({"schema_version": 1, "model": "ideal_constant_pde_fixed_gain",
                   "pde": pde, "gain_electrons": gain, "seed": seed,
                   "photons": str(Path(photons).resolve()),
                   "events": str(Path(events).resolve()),
                   "time_basis": "independent_event_ns"}, stream, indent=2)
        stream.write("\n")
    return signals


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("photons")
    parser.add_argument("events")
    parser.add_argument("output_prefix")
    parser.add_argument("--pde", type=float, default=0.3)
    parser.add_argument("--gain", type=float, default=1e6)
    parser.add_argument("--seed", type=int, default=12345)
    args = parser.parse_args()
    digitize(args.photons, args.events, args.output_prefix, args.pde, args.gain, args.seed)
