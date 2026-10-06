# User settings guide

Acquisition/integration windows, thresholds and related parameters are external JSON
settings; changing them does not require code edits. Samples are for implementation
checks, not calibrated hardware. Choose values from measurement conditions or
literature and record sources, conditions and reasons in provenance. See the
[BGO window scan](bgo-window-scan.md) for literature and gate comparisons.

## Where settings live

| Target | File or fields | Meaning |
| --- | --- | --- |
| Crystal/optical transport | `examples/single_detector.gdml` | Materials, emission, shape, surfaces and optical boundaries |
| SiPM | `examples/single_channel_cells.json` | grid, pde, gain_electrons, dead_time_ns, recovery_time_ns |
| Noise | `examples/single_channel_noise.json` | Whole-channel dark_rate_hz, crosstalk/afterpulse probabilities and delay constant |
| Electronics/ADC | `examples/single_channel_readout.json` | Rise/decay constants, transimpedance, sampling interval, baseline, ADC resolution/bits |
| Trigger | Same readout JSON | threshold_mV and release_mV, both relative to configured baseline |
| Fixed gate | `examples/bgo_fixed_gate.json` | pretrigger_ns, integration_ns, holdoff_ns |
| Acquisition/event times | User timeline JSON | state_start_ns, window_start_ns, window_end_ns, event_offsets |

For a measured trigger time t, a fixed gate integrates
`[t - pretrigger_ns, t + integration_ns)`. holdoff_ns prevents retriggering from t;
crossings during holdoff do not extend it. To prevent duplicate integration,
`holdoff_ns >= pretrigger_ns + integration_ns` is required. Triggering uses a rising
threshold crossing with hysteresis; rearming requires falling to release. CFD and
pulse-shape triggering are not implemented.

Without `--gate-config`, legacy threshold/release windows are expanded by pre_samples
and post_samples, and overlapping windows are merged. Fixed-gate mode ignores those
two fields, but they remain required readout JSON fields.

The acquisition interval is `[window_start_ns, window_end_ns)`. The preceding
`[state_start_ns, window_start_ns)` warms up cell state and waveform tails. Photon
time is Geant4 time plus event offset_ns; do not add primary-particle time again.
max_samples and noise max_candidates are computational budgets, not physical parameters.

## Copy, edit and validate

Run from the repository root:

```sh
mkdir -p output/my_settings
cp examples/single_channel_cells.json output/my_settings/cells.json
cp examples/single_channel_noise.json output/my_settings/noise.json
cp examples/single_channel_readout.json output/my_settings/readout.json
cp examples/bgo_fixed_gate.json output/my_settings/gate.json
```

After editing the copies, validate them before simulation:

```sh
python3 tools/validate_settings.py \
  --cells output/my_settings/cells.json \
  --noise output/my_settings/noise.json \
  --readout output/my_settings/readout.json \
  --gate-config output/my_settings/gate.json \
  --geometry examples/single_detector.gdml
```

The command uses runtime validators and rejects unknown keys, invalid ranges and
inconsistent windows without silently correcting them. It also reports fields
ignored in fixed-gate mode. Validation is read-only.

Once transport exists, generate periodic event times, for example as follows. Adjust
the example end time for event count and the required decay tail:

```sh
python3 tools/make_timeline.py output/single_channel_run0_events.csv \
  output/my_settings/timeline.json \
  --spacing-ns 10000 --first-offset-ns 1000 \
  --window-start-ns 500 --window-end-ns 100000 \
  --provenance 'User exploratory periodic acquisition'
```

The generator sets state_start_ns=0; edit the JSON if necessary. Event times can also
be supplied manually. This is a synthetic schedule, not Poisson arrivals from a real
source. Adding the following arguments to validation checks event identity, complete
event coverage, acquisition bounds and the sample budget implied by sampling:

```sh
  --timeline output/my_settings/timeline.json \
  --events output/single_channel_run0_events.csv
```

Timeline preflight does not inspect photon CSV contents. Valid settings do not prove
that all needed signal fits the acquisition window or matches real hardware.

## Apply settings

```sh
python3 tools/digitize_cells.py \
  output/single_channel_run0_photons.csv output/single_channel_run0_events.csv \
  output/my_response --config output/my_settings/cells.json \
  --geometry examples/single_detector.gdml \
  --timeline output/my_settings/timeline.json \
  --noise output/my_settings/noise.json --seed 42

python3 tools/readout.py output/my_response_history.csv output/my_response_response.json \
  output/my_readout --config output/my_settings/readout.json \
  --gate-config output/my_settings/gate.json
```

Use the GDML that generated the photons. Outputs are protected against overwrite;
choose different names for comparisons. Applied settings are recorded in response
and readout JSON.

| Change | Stage to rerun |
| --- | --- |
| Crystal, optical properties, geometry, primary particles | Geant4 onward |
| PDE, recovery, noise, acquisition bounds/event times | digitize_cells.py onward from the same transport |
| Shaping, ADC, thresholds, gates, holdoff | readout.py from the same history/response |

Histories exclude signal after acquisition ends, so extending acquisition requires
rerunning the response stage. Settings remain separate from transport truth in
DOI and coincidence work. These commands show the single-channel baseline; the
[configured pipeline](configured-pipeline.md) connects multi-channel examples.
DOI reconstruction remains unimplemented. [Coincidence selection](coincidences.md)
uses separate JSON settings for windows, charge/quality cuts, offsets and allowed
pairs. [Opposed-head integration](opposed-heads.md) tests ideal correlated gamma
transport; realistic decay-source modeling remains future work.

See [acquisition](acquisition.md), [cell response](cell-response.md),
[noise response](noise-response.md) and [waveform readout](waveform-readout.md)
for detailed definitions.
