"""Declared Poisson dark attempts and subcritical nearest-neighbor/AP branching."""
from dataclasses import asdict, dataclass
import hashlib
import heapq
import math
import random

from acquisition import prepare_acquisition
from sipm_cells import CellState, EventResponse, Photon, keys, number


@dataclass(frozen=True)
class NoiseConfig:
    schema_version: int
    provenance: str
    dark_rate_hz: float
    crosstalk_probability: float
    afterpulse_probability: float
    afterpulse_time_ns: float
    max_candidates: int

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Unsupported noise schema")
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            raise ValueError("Noise provenance is required")
        for name in ("dark_rate_hz", "crosstalk_probability", "afterpulse_probability", "afterpulse_time_ns"):
            object.__setattr__(self, name, number(getattr(self, name), name, minimum=0,
                                                  strictly_positive=name == "afterpulse_time_ns"))
        if self.crosstalk_probability + self.afterpulse_probability >= 1:
            raise ValueError("Require crosstalk_probability + afterpulse_probability < 1")
        if type(self.max_candidates) is not int or not 1 <= self.max_candidates <= 2_000_000:
            raise ValueError("max_candidates must be an integer in [1, 2000000]")

    @classmethod
    def from_dict(cls, data):
        keys(data, cls.__dataclass_fields__, "noise configuration")
        return cls(**data)


def neighbors(cell, grid):
    x, y = cell % grid.cells_x, cell // grid.cells_x
    return [iy*grid.cells_x+ix for ix, iy in ((x-1,y),(x+1,y),(x,y-1),(x,y+1))
            if 0 <= ix < grid.cells_x and 0 <= iy < grid.cells_y]


def simulate_noise(config, arrivals, photon_rng, timeline, identity, noise, seed):
    ordered, start, lower, upper = prepare_acquisition(config, arrivals, timeline, identity)
    noise_seed = int.from_bytes(hashlib.sha256(f"g4pec-noise-v1:{seed}".encode()).digest(), "big")
    rng = random.Random(noise_seed)
    state = CellState(config, photon_rng)
    responses = {e: EventResponse([]) for e in arrivals}
    excluded = {e: {"before_window": 0, "after_window": 0} for e in arrivals}
    warmup = {"detected": 0, "pde_rejected": 0, "unavailable": 0}
    counts = {cause: {"attempts": 0, "detected": 0, "unavailable": 0, "pde_rejected": 0}
              for cause in ("photon", "dark", "crosstalk", "afterpulse")}
    queue, history = [], []
    scheduled, clipped = 0, 0

    def push(t, cause, cell, event=None, track=None, parent=None, root_event=None, root_track=None):
        nonlocal scheduled, clipped
        if not math.isfinite(t):
            raise ValueError("Noise time overflow")
        if t >= upper:
            clipped += 1
            return
        scheduled += 1
        if scheduled > noise.max_candidates:
            raise ValueError("Noise candidate budget exceeded; no partial result is valid")
        priority = {"photon": 0, "dark": 1, "crosstalk": 2, "afterpulse": 3}[cause]
        heapq.heappush(queue, (t, priority, scheduled, cause, cell, event, track, parent, root_event, root_track))

    for t, e, track, cell, _ in ordered:
        if t >= upper:
            excluded[e]["after_window"] += 1
        else:
            push(t, "photon", cell, e, track, root_event=e, root_track=track)
    # Seed the entire independent Poisson stream before sampling correlated branches.
    if noise.dark_rate_hz:
        t = start
        while True:
            delay = rng.expovariate(1.0) / noise.dark_rate_hz * 1e9
            next_time = t + delay
            if not math.isfinite(next_time) or next_time >= upper:
                break
            if next_time <= t:
                raise ValueError("Dark time spacing is below clock precision")
            t = next_time
            push(t, "dark", rng.randrange(config.grid.cells_x * config.grid.cells_y))
    for_processing = 0
    while queue:
        t, _, _, cause, cell, event, track, parent, root_event, root_track = heapq.heappop(queue)
        for_processing += 1
        counts[cause]["attempts"] += 1
        # Position is unused because cell is explicit; synthetic track ID is internal only.
        avalanche, reason = state.process(Photon(track or 1, t, 0, 0), cell, internal_trigger=cause != "photon")
        counts[cause][reason] += 1
        observed = t >= lower
        if cause == "photon":
            if not observed:
                excluded[event]["before_window"] += 1
                warmup[reason] += 1
            elif avalanche is not None:
                responses[event].avalanches.append(avalanche)
            elif reason == "unavailable":
                responses[event].n_unavailable += 1
            else:
                responses[event].n_pde_rejected += 1
        if avalanche is None:
            continue
        aid = len(history) + 1
        history.append({"avalanche_id": aid, "parent_avalanche_id": parent,
                        "event_id": event, "track_id": track, "root_event_id": root_event,
                        "root_track_id": root_track, "cause": cause, "cell_id": cell,
                        "time_ns": t, "charge_pC": avalanche.charge_pC,
                        "recovery_fraction": avalanche.recovery_fraction, "observed": observed})
        fraction = avalanche.recovery_fraction
        adjacent = neighbors(cell, config.grid)
        if adjacent and noise.crosstalk_probability and rng.random() < noise.crosstalk_probability*fraction:
            push(t, "crosstalk", rng.choice(adjacent), parent=aid, root_event=root_event, root_track=root_track)
        if noise.afterpulse_probability and rng.random() < noise.afterpulse_probability*fraction:
            delayed = t + rng.expovariate(1.0)*noise.afterpulse_time_ns
            if delayed <= t:
                raise ValueError("Afterpulse delay is below clock precision")
            push(delayed, "afterpulse", cell, parent=aid, root_event=root_event, root_track=root_track)
    details = {"schema_version": 1, "model": "poisson_dark_neighbor_xt_exponential_ap_v1",
               "parameters": asdict(noise), "noise_seed": noise_seed,
               "counts_including_warmup": counts, "candidates_processed": for_processing,
               "correlated_candidates_after_window": clipped,
               "initial_traps": "empty_at_state_start", "branch_probability_scaling": "parent_recovery_fraction",
               "noise_pde": "not_applied", "tie_priority": ["photon", "dark", "crosstalk", "afterpulse"]}
    return responses, excluded, warmup, history, details
