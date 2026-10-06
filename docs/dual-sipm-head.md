# One crystal, two SiPMs: optical transport and head features

`examples/dual_sipm_head.gdml` is a research geometry; `tools/head_features.py`
analyzes a portable SiPM dataset. The original baseline geometry is retained.

## Research geometry

| Part | X × Y × Z size [mm] | Center [mm] |
| --- | --- | --- |
| BGO crystal | 12 × 12 × 10 | (0,0,0) |
| Left coupling | 5.8 × 5.8 × 0.1 | (-3,0,5.05) |
| Right coupling | 5.8 × 5.8 × 0.1 | (+3,0,5.05) |
| Left SiPM | 5.8 × 5.8 × 0.1 | (-3,0,5.15) |
| Right SiPM | 5.8 × 5.8 × 0.1 | (+3,0,5.15) |

Both SiPMs belong to `detector0`, with XY-parallel faces side by side on the +Z
crystal face. Couplings are separated by 0.2 mm. Existing sensor/material parameters
are retained without optical optimization. This example has no slit or reflective
wrapping and does not reproduce the papers' semicylindrical geometry or U-shaped
light path. It is separate from the later YZ-facing opposed-head fixture.

## Truth-independent post analysis

```sh
python3 tools/head_features.py path/to/response/dataset \
  examples/head_features.json output/head_analysis
```

The first `channels` entry is left and the second is right. Each specifies a channel
ID, timing offset, readout configuration and optional fixed gate. Dataset metadata
must assign both to the requested head. Existing waveform/singles extraction is
reused without reading GDML or truth.

Offset-corrected candidates are matched using `-W <= t_right - t_left < W`, keeping
all pairs. The illustrative half-window is 20 ns, not a calibrated or optimal value.
ADC settings, the 1 µs integration window and 1504 ns holdoff retain existing values.

`features.csv` contains:

- Left/right input single IDs, corrected times, charges and `t_right-t_left`.
- Total charge `Q_left+Q_right` and asymmetry `(Q_left-Q_right)/(Q_left+Q_right)`.
- Representative time: the arithmetic mean of both trigger times, not a calibrated timing estimate.
- Partner counts, ambiguity, ADC rail count, gate truncation and `valid`.

`valid` means a unique match on both sides, no truncation or rails, nonnegative
individual charges and positive total charge. It does not establish correct signal
origin or DOI. Many-to-many matches remain visible with `valid=false`. Singles with
no partner are saved to `unmatched.csv`; a missing side is not filled with zero charge.

Charges come from **independently extracted integration windows**, not reintegration
using a common trigger. Bias from different start times and finite gate lengths
remains an evaluation topic. Calibrated energy and DOI are not emitted.

## From head singles to coincidences

The same run produces `singles.csv` and `singles.json` from `valid=true` features.
`single_id=feature_id`, time is the mean of corrected triggers, and charge is their
sum. Original left/right single IDs remain available; rejected features and unmatched
candidates remain in their respective tables. Logical `head:<detector_id>` names are
distinct from physical sensor paths. This quality selection is not annihilation-origin
classification or energy/DOI calibration.

After analyzing heads from the same dataset, use entries like these in the
`inputs` field of a `tools/coincidences.py` configuration. Set `clock_id` to
`response_head.clock_id` from singles.json and adapt IDs and paths to the data.

```json
[
  {"detector_id":"A", "singles":"head_A/singles.csv", "manifest":"head_A/singles.json", "time_offset_ns":0},
  {"detector_id":"B", "singles":"head_B/singles.csv", "manifest":"head_B/singles.json", "time_offset_ns":0}
]
```

This is only the inputs fragment; see [coincidence selection](coincidences.md) for
other settings. Users specify window width, inter-head offsets and charge cuts in
pC, not keV. Channel offsets have already been applied and must not be added again.
The mean of corrected channel acquisition bounds is an enclosing time range, not
common effective exposure.

Selection checks dataset, geometry, clock and head assignments. It rejects reused
SiPMs across heads, mixtures of head/channel/legacy streams and hash mismatches.
Inter-head multiplicities retain all pairs and flags. Original GDML, truth and SiPM
dataset files are not reread. Synthetic A/B tests verify the interface; the later
[opposed-head study](opposed-heads.md) adds ideal gamma-pair transport.

Waveforms and channel singles are retained. `head.json` records geometry, dataset,
clock, response/readout references and hashes, definitions and counts. Existing
outputs are protected; failed runs remove their newly created output directory.

## Position scan with crystal scintillation

```sh
python3 studies/dual_sipm_response.py build/g4pec \
  --output-dir output/dual_sipm_response_new --events 16
```

Sixteen 100 keV electrons were injected at each of five internal positions, through
scintillation, light transport, both SiPM responses, ADC and head features. Spacing
was 10 µs, event time 7 ns and first offset 1 µs. Each position reused identical
transport with noise off/on. Every event deposited 100 keV, with no photon acquisition
clipping or ADC rails.

The following noiseless results define prompt as `[-1,100)` ns relative to the known
injection time. Charge statistics use only the first valid pair in that interval.

| Position (x,y,z) [mm] | Prompt valid pair | Mean asymmetry | Mean total charge [pC] |
| --- | ---: | ---: | ---: |
| (-3,0,0) | 13/16 | +0.394 | 6.801 |
| (0,0,0) | 11/16 | -0.024 | 7.359 |
| (+3,0,0) | 12/16 | -0.411 | 7.517 |
| (0,0,-3) | 11/16 | +0.004 | 6.966 |
| (0,0,+3) | 12/16 | -0.026 | 7.170 |

Lateral response variation is observed, but **X-position discrimination and Z-depth
identification are different questions**. These conditional averages do not establish
continuous DOI. Sixteen events per position provide descriptive results, not a
position-resolution estimate or calibration curve.

With noise, prompt valid-pair counts were 2/16, 0/16, 2/16, 0/16 and 2/16 in the same
order. Independent channel thresholds/holdoff and finite matching windows contribute,
but were not further separated in this study. A few successful ratios do not describe
all events. Noise can enter these intervals, so occupancy is not truth-classified
detection efficiency. Settings were not tuned; unmatched singles were retained.

Results are saved in `output/dual_sipm_response/`. report.json contains summaries;
position directories contain response, portable data, head features and separate
truth-based evaluation. `*_evaluation.json` is never used for feature extraction.

## Automated verification

Seven `head_features` tests cover charge/time definitions, endpoints, many-to-many
matches, missing partners, quality, nonpositive charges, input-order/truth invariance,
offsets, replay without original inputs/truth, head mismatch and output protection.
They also cover four-channel/two-head coincidence replay, removal of original data,
inter-head endpoints and shared clock/assignment/hash checks.

`dual_sipm_pipeline` runs two events at each of five positions in two noise modes.
It checks shared transport, arrivals at both sensors, no rails and complete execution.
No particular Monte Carlo count or position-performance target is required.
