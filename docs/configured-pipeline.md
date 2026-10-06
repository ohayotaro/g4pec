# Configured execution and analysis replay

```sh
python3 tools/run_pipeline.py examples/pipeline/opposed.json \
  output/my_run --executable build/g4pec
python3 tools/run_pipeline.py examples/pipeline/opposed.json \
  output/my_replay --dataset output/my_run/response/dataset
```

`single_head.json` demonstrates one head with two SiPMs; `opposed.json` demonstrates
two opposing heads with two SiPMs each. Both use the same execution path and retain
the existing illustrative acquisition windows and SiPM response parameters.

## Configuration

Top-level fields are schema_version=1, provenance, transport, response and analysis.
File paths are resolved relative to the configuration file containing that path.

- `transport.geometry`: GDML. DetectorID on each SiPM logical volume specifies its head.
- `transport.macro`: Geant4 source, initialization and event-count macro.
- `transport.run_id`: Geant4 run to analyze. Multiple runs are not merged automatically.
- `transport.timeline`: spacing_ns, window_start_ns, window_end_ns, first_offset_ns,
  provenance. Uses the existing periodic clock, not a radioactive-decay time distribution.
- `response`: Existing configuration listing every SiPM's channel_id, GDML placement
  path, cell response and noise settings.
- `analysis.heads`: List of model, config and time_offset_ns entries. Currently the
  only model is `two_sipm_candidate_features_v1`; config points to an existing head
  analysis configuration. time_offset_ns is the head-to-head coincidence correction,
  separate from individual channel corrections within a head.
- `analysis.coincidence`: Existing coincidence settings without inputs or clock_id.
  Input files and clock are bound automatically. Use null to skip coincidence processing.

The runner does not assume head names A/B or channel names left/right. It checks
all channel assignments against the GDML-derived dataset. The current model requires
exactly two channels per head. Heads with three or more channels, or missing analysis
entries, are rejected instead of silently selecting two channels. The lower-level
`head_features.py` retains its previous partial-selection behavior; the completeness
check applies to this runner. Placement-specific DetectorID overrides in GDML are
not implemented.

## Saved inputs and replay

The runner saves `input.gdml`, `source.mac`, `channels.json`, the original
pipeline.json, timeline.json and transport outputs. `response/dataset` contains
the portable SiPM response. Each `analysis/head_0000/` directory contains the
original head configuration, copied readout/gate settings, a resolved configuration,
and features/singles under result/. `analysis/coincidence.json` binds the generated
head inputs. run.json records original configuration/input hashes; response and
analysis stages retain their existing hashes as well.

`--dataset` does not read GDML, macros, original transport or truth.json. The
transport and response fields may be null. Head and readout/gate settings remain
required. When relocating saved settings, point each head.config in the new pipeline
configuration to the relocated `head_0000/config.json`, etc. Separate output paths
allow analysis comparisons without regenerating SiPM responses.

Existing destinations are rejected. Failures after execution starts retain
failure.json and partial files; only run.json with complete=true marks completion.
External macro files and GDML includes are not recursively collected. Use
self-contained inputs for reproducibility. Relative paths inside macros are
resolved from the pipeline configuration directory.

## Verification

`configured_pipeline` checks one- and two-head Geant4 runs, replay after relocation
and removal of original transport/truth, byte-identical analysis CSVs, output
protection, unsupported models and missing head/channel assignments. Detection
counts and position-identification performance are not acceptance criteria.
