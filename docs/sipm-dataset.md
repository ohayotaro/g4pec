# Portable SiPM response dataset v1

The geometry-independent boundary is a **per-channel SiPM response history**.
Simulation produces optical transport and SiPM response; post analysis extracts
measured features. Crystal IDs, DOI values and fixed 16-LOR representations are
not embedded in the common output.

```text
GDML + source + acquisition timeline + SiPM settings
    → transport and SiPM response
    → portable dataset (channel histories, clock, settings, identities)
    → waveforms/singles → calibration/crystal identification/DOI → coincidences/reconstruction
                          separate truth → evaluation only
```

The dataset layer implements export from existing responses, integrity validation,
waveform/singles replay and coincidence binding. It does not itself implement
calibration, channel aggregation, DOI or image reconstruction. Subsequent head
aggregation is described in [head features](dual-sipm-head.md).

## Storage format

```text
dataset/
  manifest.json
  channels/0000/history.csv
  channels/0000/response.json
  channels/0001/history.csv
  channels/0001/response.json
  ...
  truth.json                     # Optional; analysis does not require it.
```

Each dataset corresponds to one geometry, transport dataset/run and acquisition
timeline. It uses schema_version=1 and artifact_type=sipm_response_dataset, with
relative paths for relocation. Original GDML, photon CSVs and response CSVs are
not needed after export.

| Metadata | Definition |
| --- | --- |
| `dataset_id` | UUID for the response dataset, separate from transport event IDs |
| `channel_id` | Unique readout-channel ID within the dataset |
| `detector_id` | Explicit head assignment; multiple channels may share a head |
| `channel_path` | Original physical placement path, not reconstructed crystal identity |
| `geometry_sha256` | GDML SHA256 recorded by the response, identifying geometry without interpreting it |
| `clock` | Common ns clock, state initialization, acquisition bounds and a clock ID hashing the full timeline |
| `response_settings_sha256` | Per-channel hash of canonical cell/noise settings JSON |
| `response.json` | Response settings, available RNG metadata, original input hashes, observed/warmup counts and dataset binding |

history.csv has four columns: `avalanche_id,time_ns,charge_pC,observed`. IDs are
channel-local; references use `(dataset_id, channel_id, avalanche_id)`. The observed
window is `[window_start_ns, window_end_ns)`; earlier history is retained to reproduce
waveform tails. Registered inactive channels remain present with header-only CSVs.

Histories are simulated SiPM outputs, not an assumption that individual avalanches
can be directly measured in hardware. The declared electronics model generates
waveforms/ADC. Importing measured waveforms as the common input is not implemented.

## Export and replay

In `examples/sipm_dataset_export.json`, each channels entry specifies channel ID,
head assignment, existing `_response.json` and `_history.csv`. Paths are relative
to the configuration. Equal observation windows alone are insufficient: all channels
must share transport identity, GDML hash and the **complete timeline including every
event offset**. Independent acquisitions are not silently merged. Recorded history
hashes, counts, times, IDs and observed flags are validated before export.

To create the single-channel example:

```sh
build/g4pec examples/single_detector.gdml examples/optical.mac output/common_transport
python3 tools/make_timeline.py output/common_transport_run0_events.csv \
  output/common_timeline.json --spacing-ns 1000 --window-end-ns 101000
python3 tools/digitize_cells.py output/common_transport_run0_photons.csv \
  output/common_transport_run0_events.csv output/common_response \
  --config examples/single_channel_cells.json \
  --geometry output/common_transport_run0_geometry.gdml \
  --timeline output/common_timeline.json --seed 42
python3 tools/sipm_dataset.py examples/sipm_dataset_export.json output/common_dataset
python3 tools/analyze_sipm.py output/common_dataset sipm0 output/common_analysis \
  --config examples/single_channel_readout.json
```

analyze_sipm.py validates the requested portable channel and invokes existing
waveform/ADC/singles extraction without GDML or truth. `--gate-config` selects fixed
integration gates. Outputs remain `_waveform.csv`, `_singles.csv` and `_readout.json`,
with dataset/channel/head/geometry/clock context added to the readout manifest.
Use a new output prefix for each analysis; existing files/directories are protected.

Export with `--include-truth` to save original event/track/cause/cell annotations
separately in truth.json. The common manifest does not require it, and deleting it
does not change analysis. This does not copy all detailed transport-interaction truth.

## Coincidence and analysis-model binding

For portable singles, set coincidence clock_id to the dataset's clock.clock_id and
use registered detector_id values. Mixed datasets, geometries or clocks and detector
remapping are rejected. Legacy inputs remain supported, but cannot be mixed with
portable inputs.

The coincidence tool requires one singles stream per detector. Two SiPMs from one
head must not be treated as separate opposing heads. The subsequent
[two-SiPM model](dual-sipm-head.md) builds uncalibrated head singles; calibrated
position reconstruction remains future work.

Future calibration, crystal-identification and DOI models must bind to channel lists,
geometry and response-setting identities. A common format does not imply calibration
transfer across geometries. Current identities propagate to analysis and detect
incompatible coincidence inputs.

## Verification and limitations

Six sipm_dataset tests cover exact legacy-output replay, relocation and removal of
source/truth, multiple channels in one head, inactive channels, changed geometry
identities, timeline mismatch, tampering, output protection and coincidence binding.
Synthetic geometry changes test identity/format handling, not U-crystal transport.

Retained noisy center-100-keV BGO responses were exported to
`output/sipm_dataset_verified/` and replayed with existing settings. Waveforms and
371 singles in `output/sipm_dataset_verified_analysis_*` are byte-identical to the
original saved outputs.

[digitize_channels.py](multi-channel-response.md) connects multiple physical SiPMs
to the format. The legacy digitize_cells.py CLI retains its single-SiPM restriction.
Both response paths require explicitly placed box sensors. Common-trigger waveform
aggregation and DOI remain separate work; integration fixtures do not prescribe a
final PEC design.
