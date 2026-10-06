"""Explicit event-origin offsets and one continuous, single-channel response window."""
import math

from sipm_cells import CellState, EventResponse, Photon, keys, number


def prepare_acquisition(config, arrivals, timeline, identity):
    keys(timeline, ("schema_version", "provenance", "transport_identity", "state_start_ns",
                    "window_start_ns", "window_end_ns", "event_offsets"), "timeline")
    if type(timeline["schema_version"]) is not int or timeline["schema_version"] != 1:
        raise ValueError("Unsupported timeline schema")
    if not isinstance(timeline["provenance"], str) or not timeline["provenance"].strip():
        raise ValueError("Timeline provenance is required")
    keys(timeline["transport_identity"], ("dataset_id", "run_id"), "transport_identity")
    declared = timeline["transport_identity"]
    if (identity is None or type(declared["run_id"]) is not int or
            declared != {"dataset_id": identity[0], "run_id": int(identity[1])}):
        raise ValueError("Timeline must match identified transport dataset and run")
    start, lower, upper = (number(timeline[k], k, minimum=0) for k in
                           ("state_start_ns", "window_start_ns", "window_end_ns"))
    if not start <= lower < upper:
        raise ValueError("Require state_start_ns <= window_start_ns < window_end_ns")
    if not isinstance(timeline["event_offsets"], list):
        raise ValueError("event_offsets must be a list")
    offsets = {}
    for item in timeline["event_offsets"]:
        keys(item, ("event_id", "offset_ns"), "event offset")
        event = item["event_id"]
        if type(event) is not int or event < 0 or event in offsets:
            raise ValueError("Invalid or duplicate timeline event")
        offsets[event] = number(item["offset_ns"], "offset_ns", minimum=start)
    if set(offsets) != set(arrivals):
        raise ValueError("Timeline must cover every input event exactly once, including empty events")
    ordered = []
    for event, photons in arrivals.items():
        if len({p.track_id for p in photons}) != len(photons):
            raise ValueError("Duplicate photon track ID within an event")
        for photon in photons:
            absolute = offsets[event] + photon.time_ns
            if not math.isfinite(absolute) or (photon.time_ns > 0 and absolute == offsets[event]):
                raise ValueError("Acquisition time overflows or loses the event-relative time")
            cell = config.grid.cell_id(photon.x_mm, photon.y_mm)
            ordered.append((absolute, event, photon.track_id, cell, photon))
    ordered.sort(key=lambda item: item[:3])
    return ordered, start, lower, upper


def simulate_acquisition(config, arrivals, rng, timeline, identity, history=None):
    ordered, start, lower, upper = prepare_acquisition(config, arrivals, timeline, identity)
    state = CellState(config, rng)
    responses = {e: EventResponse([]) for e in arrivals}
    excluded = {e: {"before_window": 0, "after_window": 0} for e in arrivals}
    warmup = {"detected": 0, "pde_rejected": 0, "unavailable": 0}
    for absolute, event, _, cell, photon in ordered:
        if absolute >= upper:
            excluded[event]["after_window"] += 1
            continue
        shifted = Photon(photon.track_id, absolute, photon.x_mm, photon.y_mm)
        avalanche, reason = state.process(shifted, cell)
        if avalanche is not None and history is not None:
            history.append({"avalanche_id": len(history)+1, "parent_avalanche_id": None,
                            "event_id": event, "track_id": photon.track_id,
                            "root_event_id": event, "root_track_id": photon.track_id,
                            "cause": "photon", "cell_id": cell, "time_ns": absolute,
                            "charge_pC": avalanche.charge_pC, "recovery_fraction": avalanche.recovery_fraction,
                            "observed": absolute >= lower})
        if absolute < lower:
            excluded[event]["before_window"] += 1
            warmup[reason] += 1
            continue
        response = responses[event]
        if avalanche is not None:
            response.avalanches.append(avalanche)
        elif reason == "unavailable":
            response.n_unavailable += 1
        else:
            response.n_pde_rejected += 1
    return responses, excluded, warmup
