# Single-channel cell response

`tools/digitize_cells.py` replays the same pre-PDE arrival files as the ideal
digitizer, adding finite cells, dead time, charge recovery and saturation. It is
an independently implemented Python backend with no G4SiPM dependency. Optical
transport and the single-channel GDML example are unchanged.

## Run and parameters

Requires Python 3.9+ and no third-party Python packages. Use the geometry snapshot
that accompanied the photon run and a new output prefix:

```sh
python3 tools/digitize_cells.py output/single_channel_run0_photons.csv \
  output/single_channel_run0_events.csv output/single_channel_cells \
  --config examples/single_channel_cells.json \
  --geometry output/single_channel_run0_geometry.gdml --seed 42
```

The versioned JSON is strict: unknown/missing keys, invalid numeric values and
duplicate keys are rejected. `provenance` records the origin of the parameter set.
The sample values below are illustrative engineering assumptions, not calibrated
parameters for a commercial sensor.

| Parameter | Example | Meaning |
| --- | --- | --- |
| `schema_version`, `model` | `1`, `cell_recovery_constant_pde` | Configuration and model selection |
| `channel_path` | `/World_PV[0]/sipm[0]` | Exact GDML placement path |
| `grid.cells_x`, `grid.cells_y` | 116, 116 | 13,456 cells in one readout channel |
| `grid.pitch_x_mm`, `grid.pitch_y_mm` | 0.05, 0.05 | 50 micrometre cell pitch |
| `grid.origin_x_mm`, `grid.origin_y_mm` | -2.9, -2.9 | Lower corner in sensor-local XY |
| `pde` | 0.3 | Effective constant detection probability at the collector plane for an available cell |
| `gain_electrons` | 1,000,000 | Electrons per fully charged avalanche |
| `dead_time_ns` | 0.001 | Non-firing hold-off after a successful avalanche |
| `recovery_time_ns` | 30 | Positive exponential recharge constant after hold-off |
| `--seed` | 42 | Independent Python response RNG seed, integer in [0, 2^64) |

Cell IDs use `iy * cells_x + ix`. Cells are rectangles with lower-inclusive and
upper-exclusive edges. An internal edge belongs to the cell on its positive side.
Decimal parameter values construct the edges before conversion to floating point,
so the example's central edge is exactly zero. No tolerance snaps photon positions
to cells: coordinates numerically outside the configured grid are errors.

The loader verifies exactly one reachable tagged SiPM placement, its channel path,
and agreement of the grid bounds with its sensor-local XY box footprint (1e-9 mm
absolute / 1e-12 relative tolerance). Rotated and nested explicit placements are
supported because the transport output already uses local coordinates. This
footprint check supports box sensors with numeric literal dimensions and units
nm, um, mm, cm or m. GDML dimension expressions, external geometry files, assemblies,
replicas and parameterised placements require a future geometry-metadata interface.
They are not silently approximated. This response prototype supports at most one
million cells; per-event cell state is sparse.

## Model version 1

In the default independent-event mode, every event starts fully charged, including events whose first photon arrives at
time zero. This default mode has no state shared between events. The optional
[acquisition mode](acquisition.md) instead interleaves arrivals on a declared
common clock and shares cell state across events. Process arrivals sorted
by event ID, arrival time and truth track ID; duplicate track IDs within an event
are rejected. This yields identical response CSVs when input rows are reordered.
Same-time photon attribution follows track ID, which is a reproducible simulation
tie-break rather than a physical preference.

An unused cell has recovery fraction r = 1. If it last fired at time t_last, set
delta = t - t_last. At delta <= dead_time it is unavailable. Otherwise:

```text
r = 1 - exp(-(delta - dead_time_ns) / recovery_time_ns)
Q_pC = r * gain_electrons * 1.602176634e-7
```

The exponential is evaluated with `expm1` for accuracy near zero. The model treats
dead time as a hold-off preceding recharge. An available cell undergoes one
constant-PDE Bernoulli selection. On success it emits one avalanche of charge Q
and updates t_last; failed trials and dead-time arrivals do not update the cell.
Independent cells can fire simultaneously. A cell can fire repeatedly during a
long event, but at most once at any one timestamp, including when dead_time = 0.

This version deliberately holds PDE constant once a cell is available, while
charge depends on recovery. It does not describe recovery-dependent triggering,
wavelength/angle dependence, gain variation, spatial dead areas. Waveforms are provided by a separate
[readout stage](waveform-readout.md), not the cell model.
Optional acquisition noise is implemented separately; see [the noise contract](noise-response.md).
The effective PDE includes unresolved fill-factor effects: no additional
fill-factor or Fresnel correction is applied. Optical window/interface transport
belongs upstream. The grid is a response partition, not Geant4 microcell geometry.
For broader models of recovery effects see [Modeling the response of a recovering
SiPM](https://arxiv.org/abs/1511.06528). The implementation here is a declared
simplification, not a reproduction or validation of that paper's model.

The RNG draws once for every arrival, including arrivals at unavailable cells.
Unavailable cells take precedence in the exclusive rejection accounting. This
preserves a straightforward random stream and makes the constant-PDE ideal limit
directly comparable when the input is already in canonical order. The older ideal
digitizer samples in input row order, so its seed alone does not guarantee identical
accepted track sets on an unsorted input.

## Output and accounting

The three CSV suffixes preserve the ideal digitizer's existing leading columns:

| File | Content |
| --- | --- |
| `_signals.csv` | Sparse event/channel avalanche count, first time and summed recovered charge in pC |
| `_avalanches.csv` | Event, channel, time and charge; additionally cell ID/x/y, originating track ID, cause (`photon`) and recovery fraction |
| `_events.csv` | Every input event, including zero-hit events; detected count, arrivals, PDE rejections, unavailable-cell rejections and charge |
| `_response.json` | Model/configuration versions, all parameters and provenance, seed/RNG/Python version, initialization and ordering conventions, geometry footprint, input paths/SHA-256 hashes and totals |

`n_detected` counts successful avalanches, not normalized charge. All input arrivals
are accounted for as `n_detected + n_pde_rejected + n_unavailable`. Missing signal
rows mean zero output. Without `--noise` there is only the photon cause. The optional acquisition-noise
mode adds causes, ancestry and channel/history outputs with distinct accounting.

The loader checks finite coordinates/times/positive energies, event and channel
membership, event counts and duplicate identities. Input validation and simulation
finish before any output file is created. Existing outputs are protected, and files
created by a failed output write are removed. Inputs, sorted arrivals and results
are held in memory; this backend targets small event-based studies.

## Validation

`tests/check_cell_response.py` runs independently of Geant4. Its checks cover the
first photon and event reset, boundaries, independent cells, same-time suppression,
dead-time endpoints, exact two-pulse recovery, non-reset on rejected photons, full
recovery, PDE zero/one, invalid input/configuration, overwrite protection and input
row reordering. In the all-cells-unused limit, counts and charge agree with the
existing ideal digitizer for the same ordered photons and seed.

The saturation benchmark uses N = 16 cells and M = 4, 16 or 64 simultaneous photons,
each independently and uniformly assigned to a cell, with p = 0.3 or 1. For fixed M,
the exact occupancy expectation is:

```text
q = (1 - p/N)^M
E[K] = N (1 - q)
Var[K] = N q (1 - q) + N (N - 1) ((1 - 2p/N)^M - q^2)
```

This follows by summing occupied-cell indicators; the covariance term accounts
for the fixed number of incident photons. It is not the Poisson approximation
`N (1 - exp(-M p/N))`. Each of the six conditions uses 2,000 events with separate,
fixed source and response seeds. The acceptance tolerance on the sample mean is
predeclared as six standard errors plus 1/2,000 cell. The comparison report includes
conditions, seeds, predicted/observed means, standard errors and z-scores:

```sh
python3 tests/check_cell_response.py --report output/cell_response_validation.json
```

Use a new report path for subsequent runs. CTest also runs these checks as
`cell_response`. The optical pipeline test replays actual direct, rotated and
gamma-induced arrival streams through the cell CLI. These are implementation and
model-limit checks; device-specific parameter fitting remains the user's task.
