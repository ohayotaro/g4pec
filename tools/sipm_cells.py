"""Independent event-local SiPM cells: constant available-cell PDE and RC recovery."""
from bisect import bisect_right
from dataclasses import asdict, dataclass
from decimal import Decimal
from functools import cached_property
import math


MODEL = "cell_recovery_constant_pde"
ELECTRON_CHARGE_PC = 1.602176634e-7


def number(value, name, minimum=None, strictly_positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    value = float(value)
    if not math.isfinite(value) or (minimum is not None and value < minimum):
        raise ValueError(f"Invalid {name}")
    if strictly_positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def keys(mapping, expected, name):
    if not isinstance(mapping, dict) or set(mapping) != set(expected):
        raise ValueError(f"{name} requires exactly these keys: {', '.join(sorted(expected))}")


@dataclass(frozen=True)
class Grid:
    cells_x: int
    cells_y: int
    pitch_x_mm: float
    pitch_y_mm: float
    origin_x_mm: float
    origin_y_mm: float

    def __post_init__(self):
        for name in ("cells_x", "cells_y"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.cells_x * self.cells_y > 1_000_000:
            raise ValueError("This prototype supports at most 1,000,000 cells")
        for name in ("pitch_x_mm", "pitch_y_mm", "origin_x_mm", "origin_y_mm"):
            object.__setattr__(self, name, number(getattr(self, name), name,
                                               strictly_positive=name.startswith("pitch")))
        # Decimal construction preserves declared decimal boundaries such as
        # -2.9 + 58 * 0.05 = 0 before converting each edge to a binary float.
        for edges in (self.x_edges, self.y_edges):
            if not all(math.isfinite(x) for x in edges) or any(
                    a >= b for a, b in zip(edges, edges[1:])):
                raise ValueError("Cell edges must be finite and distinguishable")

    @staticmethod
    def edges(origin, pitch, count):
        lo, step = Decimal(str(origin)), Decimal(str(pitch))
        return tuple(float(lo + i * step) for i in range(count + 1))

    @cached_property
    def x_edges(self):
        return self.edges(self.origin_x_mm, self.pitch_x_mm, self.cells_x)

    @cached_property
    def y_edges(self):
        return self.edges(self.origin_y_mm, self.pitch_y_mm, self.cells_y)

    def cell_id(self, x_mm, y_mm):
        x = number(x_mm, "local_x_mm")
        y = number(y_mm, "local_y_mm")
        if not (self.x_edges[0] <= x < self.x_edges[-1] and
                self.y_edges[0] <= y < self.y_edges[-1]):
            raise ValueError(f"Photon position ({x}, {y}) is outside the cell grid")
        ix = bisect_right(self.x_edges, x) - 1
        iy = bisect_right(self.y_edges, y) - 1
        return iy * self.cells_x + ix


@dataclass(frozen=True)
class CellConfig:
    schema_version: int
    model: str
    provenance: str
    channel_path: str
    grid: Grid
    pde: float
    gain_electrons: float
    dead_time_ns: float
    recovery_time_ns: float

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1 or self.model != MODEL:
            raise ValueError("Unsupported cell-response schema or model")
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            raise ValueError("A nonempty parameter provenance is required")
        if not isinstance(self.channel_path, str) or not self.channel_path.startswith("/"):
            raise ValueError("An absolute channel placement path is required")
        if not isinstance(self.grid, Grid):
            raise ValueError("Invalid grid")
        for name in ("pde", "gain_electrons", "dead_time_ns", "recovery_time_ns"):
            object.__setattr__(self, name, number(getattr(self, name), name, minimum=0,
                                               strictly_positive=name in ("gain_electrons", "recovery_time_ns")))
        if self.pde > 1:
            raise ValueError("PDE must be in [0, 1]")
        charge = self.gain_electrons * ELECTRON_CHARGE_PC
        if not math.isfinite(charge) or charge <= 0:
            raise ValueError("Gain must give a finite positive charge in pC")

    @classmethod
    def from_dict(cls, values):
        keys(values, cls.__dataclass_fields__, "configuration")
        keys(values["grid"], Grid.__dataclass_fields__, "grid")
        return cls(**{**values, "grid": Grid(**values["grid"])})

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Photon:
    track_id: int
    time_ns: float
    x_mm: float
    y_mm: float

    def __post_init__(self):
        if type(self.track_id) is not int or self.track_id <= 0:
            raise ValueError("track_id must be a positive integer")
        for name in ("time_ns", "x_mm", "y_mm"):
            object.__setattr__(self, name, number(getattr(self, name), name,
                                               minimum=0 if name == "time_ns" else None))


@dataclass(frozen=True)
class Avalanche:
    track_id: int
    cell_id: int
    time_ns: float
    recovery_fraction: float
    charge_pC: float


@dataclass
class EventResponse:
    avalanches: list
    n_pde_rejected: int = 0
    n_unavailable: int = 0


def simulate_event(config, photons, rng):
    """Each call starts fully charged; equal times are ordered by truth track ID.

    Draw exactly one uniform number per arrival, including unavailable cells.
    Unavailable cells take precedence in the exclusive rejection accounting.
    A successful avalanche alone updates a cell's last-fire time.
    """
    ordered = sorted(photons, key=lambda p: (p.time_ns, p.track_id))
    if len({p.track_id for p in ordered}) != len(ordered):
        raise ValueError("Duplicate photon track ID within an event")
    cells = [config.grid.cell_id(p.x_mm, p.y_mm) for p in ordered]
    state = CellState(config, rng)
    response = EventResponse([])
    for photon, cell in zip(ordered, cells):
        avalanche, reason = state.process(photon, cell)
        if avalanche is not None:
            response.avalanches.append(avalanche)
        elif reason == "unavailable":
            response.n_unavailable += 1
        else:
            response.n_pde_rejected += 1
    return response


class CellState:
    """One fully charged initialization; caller supplies globally ordered arrivals."""

    def __init__(self, config, rng):
        self.config, self.rng = config, rng
        self.last_fire = {}
        self.last_time = None

    def process(self, photon, cell=None, internal_trigger=False):
        if self.last_time is not None and photon.time_ns < self.last_time:
            raise ValueError("Stateful response requires nondecreasing arrival times")
        if cell is None:
            cell = self.config.grid.cell_id(photon.x_mm, photon.y_mm)
        self.last_time = photon.time_ns
        trial = 0.0 if internal_trigger else self.rng.random()
        previous = self.last_fire.get(cell)
        fraction = 1.0
        if previous is not None:
            elapsed = photon.time_ns - previous
            if elapsed <= self.config.dead_time_ns:
                return None, "unavailable"
            fraction = -math.expm1(-(elapsed - self.config.dead_time_ns) / self.config.recovery_time_ns)
            if fraction == 0:
                return None, "unavailable"
        if not internal_trigger and trial >= self.config.pde:
            return None, "pde_rejected"
        avalanche = Avalanche(photon.track_id, cell, photon.time_ns, fraction,
                              fraction * self.config.gain_electrons * ELECTRON_CHARGE_PC)
        self.last_fire[cell] = photon.time_ns
        return avalanche, "detected"
