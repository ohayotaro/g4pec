# Explicit acquisition timeline and stateful cell response

The one-crystal/one-channel example now supports a declared common clock across
Geant4 events. The baseline is a noiseless acquisition-response mode, with optional
[noise modeling](noise-response.md). Neither response mode implements DOI reconstruction,
a coincidence algorithm or a correlated gamma source. A separate
[waveform/readout stage](waveform-readout.md) extracts threshold candidates.
The existing independent-event mode remains the default without `--timeline`.

## Run

After generating a normal transport run, create a synthetic periodic schedule and
replay its photons:

```sh
python3 tools/make_timeline.py output/single_channel_run0_events.csv \
  output/single_channel_timeline.json --spacing-ns 12 --window-end-ns 10000
python3 tools/digitize_cells.py output/single_channel_run0_photons.csv \
  output/single_channel_run0_events.csv output/single_channel_acquisition \
  --config examples/single_channel_cells.json \
  --geometry output/single_channel_run0_geometry.gdml \
  --timeline output/single_channel_timeline.json --seed 42
```

Use new output paths. The generator assigns equally spaced offsets to sorted event
IDs, including zero-hit events. `--first-offset-ns` and `--window-start-ns` default
to zero. `--spacing-ns` must be positive; `--window-end-ns` is required. Its provenance
records the synthetic source assumption and the event-file hash. This schedule is
an explicit engineering fixture, not a radioactive-decay time distribution.

## Timeline schema 1

The timeline requires exactly these keys:

```json
{
  "schema_version": 1,
  "provenance": "Explicit two-event test schedule",
  "transport_identity": {"dataset_id": "COPY_FROM_TRANSPORT_MANIFEST", "run_id": 0},
  "state_start_ns": 0,
  "window_start_ns": 10,
  "window_end_ns": 100,
  "event_offsets": [
    {"event_id": 0, "offset_ns": 0},
    {"event_id": 1, "offset_ns": 12}
  ]
}
```

This example applies only to a matching two-event run; the helper generates a
complete schedule from an actual event file. A schedule must cover every event
exactly once and match the input dataset/run identity. Acquisition mode requires
identified transport data; legacy CSVs remain usable in independent-event mode.
One input run and one channel are supported. Arbitrary nonnegative offsets,
including simultaneous events, can be supplied directly in JSON.

The common clock is relative to a user-declared acquisition origin, in ns:

```text
acquisition arrival time = event offset + Geant4 event-relative arrival time
```

An offset places the Geant4 event's time-zero origin on the acquisition clock.
Any GPS primary time is already included in Geant4 arrival times and is not added
again. For a primary set to 7 ns and an event offset of 12 ns, the primary starts
at 19 ns, before adding transport delay. Offsets are not wall-clock timestamps.
Use a nearby clock origin to preserve float resolution; nonfinite results and
additions that completely lose a positive event-relative time are rejected.
Arbitrarily small time separations at enormous offsets are not supported reliably.

## State, ordering and windows

Require `0 <= state_start_ns <= window_start_ns < window_end_ns` and every event
offset at or after `state_start_ns`. Cells initialize fully charged once at state
start. Earlier history is explicitly absent; this is not an equilibrium noise
initialization or a model of events originating before state start.

All input arrivals are mapped and validated, then interleaved in order of common
arrival time, event ID and track ID. Successful avalanches update shared cell state
across event boundaries. Same-time attribution uses deterministic truth IDs solely
as a reproducible tie-break. The physical recovery/PDE rules remain those in the
[cell response contract](cell-response.md).

- `[state_start_ns, window_start_ns)`: simulate supplied arrivals to warm up state,
  including PDE sampling and recovery, but omit their avalanches from observed output.
- `[window_start_ns, window_end_ns)`: simulate and record observed avalanches.
- `window_end_ns` and later: validate and count excluded arrivals; do not simulate
  them or consume response RNG draws.

Exactly one random draw is used per simulated arrival, including unavailable cells.
There is no reset at event boundaries or the observation-window start. A fresh CLI
invocation initializes again: state/RNG checkpointing between chunks or consecutive
invocations is not implemented. All inputs and results are currently held in memory.

## Output

The avalanche CSV is globally time ordered. `time_ns` and signal `first_time_ns`
use the acquisition-relative clock; the response manifest declares this mode,
time conversion, ordering, full schedule, input hashes and initialization.

`event_id`/`track_id` remain source truth attribution. `_signals.csv` still groups
observed avalanches by source event/channel and **does not represent reconstructed
singles or hardware triggers**. Overlapping events share cell state even though
this diagnostic summary separates their truth contributions. Future readout/analysis
must build singles from acquisition signals without these truth labels.

Each event row adds `n_before_window` and `n_after_window`, with the identity:

```text
n_arrivals = n_detected + n_pde_rejected + n_unavailable
             + n_before_window + n_after_window
```

The three response outcomes count only arrivals inside the observation window.
Before-window arrivals additionally have their simulated outcomes in manifest
`warmup_counts`; they must not be counted twice in the total-arrival identity.
Empty windows and zero-hit input events retain their accounting rows.

Both acquisition modes also export full successful-avalanche `_history.csv`
and integrated all-cause `_channel.csv` for downstream waveform generation.
The response manifest records a SHA-256 binding for the history file.

## Validation and remaining work

Seven deterministic tests cover analytical cross-event recovery, nonzero primary
time, overlapping event arrival order, exact dead-time endpoints, simultaneous
cross-event saturation, independent cells, warmup, half-open windows, empty output,
identity/parameter errors, duplicate tracks, float overflow/loss, deterministic
reordering, overwrite protection and accounting. The existing event-local cell
suite verifies that extracting the shared state implementation preserved that mode.
The optical pipeline also replays actual gamma-derived photons through the timeline
generator and acquisition CLI, checking shifted times and global ordering.

Optional dark/XT/AP noise is now implemented; its additional outputs and attribution
rules are documented in the noise contract. Waveforms and ADC-based readout candidates are now implemented separately; DOI
and coincidences remain unimplemented. Next come readout validation and detector/source extensions needed
for DOI and coincidence analysis. Continuous-time input/state support by itself
does not create correlated annihilation photons or additional detector channels.
