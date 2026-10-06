#!/usr/bin/env python3
"""Create an explicit, synthetic equally spaced event-origin schedule for one run."""
import argparse
import hashlib
import json
from pathlib import Path

from digitize_cells import csv_rows
from sipm_cells import number


def make_timeline(events_path, output_path, spacing_ns, window_end_ns,
                  window_start_ns=0, first_offset_ns=0, provenance="Synthetic periodic source"):
    spacing = number(spacing_ns, "spacing_ns", strictly_positive=True)
    lower = number(window_start_ns, "window_start_ns", minimum=0)
    upper = number(window_end_ns, "window_end_ns", minimum=0)
    offset = number(first_offset_ns, "first_offset_ns", minimum=0)
    if lower >= upper or not isinstance(provenance, str) or not provenance.strip():
        raise ValueError("Require a nonempty provenance and a nonempty window")
    data = Path(events_path).read_bytes()
    identity, events = None, set()
    for row in csv_rows(data, ("dataset_id", "run_id", "event_id"), "events"):
        candidate = (row["dataset_id"], int(row["run_id"]))
        event = int(row["event_id"])
        if candidate[1] < 0 or event < 0 or event in events or (identity and identity != candidate):
            raise ValueError("Require unique events from one identified dataset/run")
        identity = candidate
        events.add(event)
    if identity is None:
        raise ValueError("Cannot infer transport identity from an empty event file")
    offsets = [number(offset+i*spacing, "event offset", minimum=0) for i in range(len(events))]
    if any(a >= b for a, b in zip(offsets, offsets[1:])):
        raise ValueError("Offsets lose spacing at this floating-point scale")
    result = {"schema_version": 1,
              "provenance": f"{provenance}; equally spaced event origins; events SHA256={hashlib.sha256(data).hexdigest()}",
              "transport_identity": {"dataset_id": identity[0], "run_id": identity[1]},
              "state_start_ns": 0, "window_start_ns": lower, "window_end_ns": upper,
              "event_offsets": [{"event_id": e, "offset_ns": t} for e, t in zip(sorted(events), offsets)]}
    with Path(output_path).open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("events", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--spacing-ns", required=True, type=float)
    p.add_argument("--window-end-ns", required=True, type=float)
    p.add_argument("--window-start-ns", default=0, type=float)
    p.add_argument("--first-offset-ns", default=0, type=float)
    p.add_argument("--provenance", default="Synthetic periodic source")
    a = p.parse_args()
    try:
        make_timeline(a.events, a.output, a.spacing_ns, a.window_end_ns,
                      a.window_start_ns, a.first_offset_ns, a.provenance)
    except (ValueError, OSError, OverflowError) as error:
        p.exit(1, f"Timeline creation failed: {error}\n")


if __name__ == "__main__":
    main()
