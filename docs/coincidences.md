# Post-analysis coincidence selection

`tools/coincidences.py` creates candidates for configured detector pairs from
acquisition-time singles. Geant4 event IDs, track IDs and ancestry never drive
selection. Existing SiPM, noise, waveform and integration parameters are unchanged.

## Inputs and outputs

```sh
python3 tools/coincidences.py examples/coincidence/config.json output/coincidence_demo
```

This synthetic example is not a correlated-gamma transport simulation. It produces
three pairs, two sharing a single. Retained verification outputs are
`output/coincidence_example_coincidences.csv` and its corresponding `.json`.

Each configuration `inputs` entry specifies the following. Relative paths resolve
from the configuration file directory.

| Field | Meaning |
| --- | --- |
| `detector_id` | Detector assigned to the input stream |
| `singles` | `_singles.csv` emitted by readout.py, or head singles.csv |
| `manifest` | Corresponding `_readout.json`, or head singles.json |
| `time_offset_ns` | Common-clock correction: corrected time = input time + offset |

One input stream is required per detector; channel aggregation is an upstream step.
Inputs require a schema-1 manifest with `time_basis=acquisition_relative_ns` and CSV
columns `single_id,channel_path,time_ns,charge_pC,n_saturated,truncated`. Rows need
not be sorted. Extra truth columns are ignored. Duplicate IDs, channel mismatches,
manifest/count inconsistencies, nonfinite values and out-of-window times are rejected.

New readout manifests record a verified singles SHA256. Legacy manifests may omit
it, indicated by `singles_hash_verified=false`. Even for legacy inputs, the hashes
of the CSV and manifest actually read are recorded.

PEC packaging limits sensor counts. A/B identify separate head streams, not a
request to add sensors to one crystal. The main application is annihilation-photon
coincidence measurement between crystal/SiPM modules. The synthetic fixture tests
the readout interface, not physical placement. Device geometry, separation and
source configuration are specified separately using GDML and source settings.

## Selection rules

| Setting | Definition |
| --- | --- |
| `clock_id` | Declared common-clock identifier |
| `provenance` | Source of settings and synchronization/correction assumptions |
| `detector_pairs` | Allowed pairs, e.g. `[["A","B"]]` |
| `half_window_ns` | Half-width W; full width is 2W |
| `min_charge_pC`, `max_charge_pC` | Inclusive charge bounds; null upper bound means unlimited |
| `reject_truncated` | Exclude singles with truncated gates |
| `reject_saturated` | Exclude singles containing ADC rails |
| `max_pairs` | Pair budget; exceeding it fails without valid partial output |

For `[A,B]`, define `Δt = tB - tA` and accept **`-W <= Δt < W`**. The lower bound
is inclusive, the upper exclusive. The example W=5 ns is a 10 ns-wide boundary
test, not a recommended calibration. Same-detector pairs and duplicate/reversed
pair specifications are rejected.

All matching partners are retained. There is no nearest-neighbor selection or
first-match consumption. `matches_a` and `matches_b` count uses of each single
across all allowed pairs; either exceeding one sets `ambiguous=true`. Multiplicity
is not hidden.

`_coincidences.csv` records pair ID, both detector/single IDs, channels, corrected
times, charges, time difference and multiplicities. Member references are
`(detector_id, single_id)` scoped to the input files in the output manifest.
`_coincidences.json` records settings, clock convention, input hashes, accepted
counts, rejection reasons and output hashes. Empty results retain a CSV header
and summary. Existing outputs are never overwritten.

## Clock and physical scope

For legacy data, clock_id and time_offset_ns declare a clock relationship; equal
labels do not prove separate acquisitions were physically synchronized. Event
numbers never imply synchronization or correlation. Supply corrections explicitly.

Inputs from a [portable dataset](sipm-dataset.md) additionally validate dataset,
geometry, clock and detector assignment. clock_id must match the recorded value.
Different datasets or mixtures of portable and legacy formats are rejected.

ADC-derived charges are not calibrated energies: cuts are explicitly in pC. True,
scattered and random-coincidence classification is not implemented and belongs to
separate truth-based evaluation. Ideal correlated gamma transport is covered by
the [opposed-head study](opposed-heads.md); DOI and realistic decay-source modeling
remain future work.

## Verification

Eight tests in `tests/check_coincidences.py` are registered as CTest `coincidences`:

- Time offsets, inclusive/exclusive window endpoints, charge bounds and quality cuts.
- All-pairs multiplicity, scoped IDs and deterministic output independent of row order.
- Exact agreement with brute-force matching of randomized times for three detectors.
- Acceptance independent of event IDs; unchanged CSV selection after truth removal.
- Empty selections, one/both empty streams, duplicate IDs, invalid settings, hash/count
  mismatches, reused inputs, overwrite protection and pair budgets.
- Two synthetic electrical pulses through existing readout settings produce one pair
  at a corrected 3 ns separation; readout output hashes are verified.

These test selection and readout integration, not measured CTR or gamma-pair efficiency.

## Two-SiPM head inputs

Use `singles.csv` / `singles.json` from `tools/head_features.py` as each detector's
singles/manifest. They contain mean times and summed charges from unique, quality-valid
within-head pairs. Energy and DOI remain uncalibrated, with cuts in pC. See
[from head singles to coincidences](dual-sipm-head.md#from-head-singles-to-coincidences).
Heads must share a dataset, clock and geometry and use distinct SiPM channels.
Head/channel/legacy stream mixtures are rejected; head singles require content hashes.
