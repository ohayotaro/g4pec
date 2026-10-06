# BGO fixed-window and holdoff scan, with literature context

Integration length, pretrigger history, thresholds, rearming and holdoff are
measurement settings requiring real-waveform optimization and performance checks.
They are not universal material constants. Gain, ADC scale, baseline, clock scale
and channel timing offsets also require calibration. For a chosen window, energy
calibration must use that same window/processing chain. This project supplies
configurable models and reproducible checks; fitting a particular apparatus
remains a user task.

## Primary references and what they support

1. Moszyński et al., *Timing properties of BGO scintillator*, Nuclear Instruments
   and Methods 188 (1981), 403–409,
   [doi:10.1016/0029-554X(81)90521-8](https://doi.org/10.1016/0029-554X(81)90521-8).
   The measured light-pulse study reports a 60 ns fast component in addition to the
   established roughly 300 ns decay. Our existing 300 ns single-exponential example
   is a simplification, not a full fit to that experiment.
2. Dieminger and Schwarz, *Influence of Wrapping on the Light Output of BGO*, ETH
   semester project / CERN-THESIS-2019-120 (2019), section II.2,
   [CERN record](https://repository.cern/records/pqb13-r4208),
   [paper](https://repository.cern/records/pqb13-r4208/files/CERN-THESIS-2019-120.pdf?download=1).
   The authors vary ADC gate width and choose 1000 ns as a compromise between
   collected light and pileup. This is one BGO/PMT experimental setup, not a
   transferable optimum for our illustrative SiPM/noise/electronics configuration.
3. Chval et al., *Development of new mixed Lux(RE3+)1−xAP:Ce scintillators
   (RE3+=Y3+ or Gd3+): comparison with other Ce-doped or intrinsic scintillating
   crystals*, NIM A 443 (2000), 331–341,
   [doi:10.1016/S0168-9002(99)01066-9](https://doi.org/10.1016/S0168-9002(99)01066-9),
   [CERN-hosted manuscript](https://cds.cern.ch/record/617869/files/ext-2003-034.pdf).
   Table 3 compares finite charge-integration durations with a 2 us reference;
   the BGO entries are 21.4%, 41.5%, 77.4%, 94.4% for 100/200/500/1000 ns.
   These measurements illustrate window dependence; they are not numerical
   acceptance targets for our different crystal/readout model.

References were checked on 2026-10-06. Some repository PDF opens were blocked by
bot protection/decoding; indexed primary-document text supplied the specific gate
and table passages. No full experimental reproduction or calibration is claimed.

For the current single-exponential 300 ns assumption, the emitted fraction by time
T is `1-exp(-T/300 ns)`: about 86.5%, 96.4%, 99.3% at 600/1000/1500 ns. These are
emission fractions from true onset, not predicted ADC gate-charge fractions from a
measured trigger. Transport, electronic shaping, threshold time and finite ADC
sampling change the latter. Cherenkov light is not a 60 ns exponential component;
its prompt production must remain separate from scintillation components.

## Implemented optional extraction mode

`tools/readout.py --gate-config examples/bgo_fixed_gate.json` adds a fixed-gate
mode. The earlier release-based/merged-gate mode is unchanged when the option is
omitted. Gate schema 1 records `provenance`, `integration_ns`, `pretrigger_ns` and
`holdoff_ns`; the example is an exploration point, not an optimized default.

- Obtain hysteretic leading-edge crossings from ADC codes only, using existing
  high/release thresholds. No source/event/track truth participates.
- An accepted crossing at t opens `[t-pretrigger, t+integration)` and blocks new
  triggers until `t+holdoff`. Suppressed crossings do not extend this interval
  (nonparalyzable/non-extending holdoff). Equality at the end is eligible.
- Require `holdoff >= integration + pretrigger`, so recorded gates cannot overlap
  or double-count area. This deliberately models non-overlapping gates; hardware
  with overlapping buffers is outside this mode.
- Crossing detection/rearming continues during holdoff. A crossing that occurred
  during holdoff is not queued; a signal still high when holdoff ends does not
  automatically trigger. A new rearmed rising crossing is required.
- Integrate ADC bin averages over exact overlap with the gate, including fractional
  bin boundaries. Flag acquisition clipping and ADC rail codes. The overall
  acquisition duration is unchanged; no window is placed using true event time.

`n_crossings` counts raw threshold crossings within a recorded gate, not accepted
triggers or physical events. The full gate config and input hash are recorded in
the readout manifest. Timing still has the previously documented leading-edge and
bin-average biases. This change does not calibrate them.

Example:

```sh
python3 tools/readout.py output/noise_example_history.csv \
  output/noise_example_response.json output/fixed_gate_new \
  --config examples/single_channel_readout.json \
  --gate-config examples/bgo_fixed_gate.json
```

## Scan and evaluation

Reuse the exact stored ADC traces from the five-condition BGO study; do not rerun
transport, change noise realizations, or change optical/electronic parameters.
Scan post-trigger integration lengths 100/300/600/1000/1500/2000 ns and additional
holdoff 0/500/1500 ns. Pretrigger is 4 ns, so total holdoff is
`integration + 4 + additional`. These are 18 settings for each of five conditions
and each noise mode: 180 replay configurations.

```sh
python3 studies/bgo_window_scan.py output/bgo_response_study \
  --output-dir output/bgo_window_scan_new
```

Output includes per-setting configs, candidate/evaluation CSVs, waveform hashes and
a complete summary. Retained results: `output/bgo_window_scan/report.json`.
Study source events remain spaced by 10 us; this scan does not validate losses
from high-rate physical-event pileup or optimize acquisition record length.

Only subsequent evaluation knows source time. Report candidates in the existing
[-1,3000) ns source-relative interval, events with zero/multiple candidates, and
whether a previously accepted trigger still imposed holdoff at source onset.
Also count intervals with a candidate before +100 ns. These are evaluation
association criteria, not noise-corrected detection efficiencies.

First-gate charge fractions use the existing same-mode truth-aligned 3 us ADC
charge as denominator, and are conditional on no holdoff at source onset plus a
candidate in the evaluation interval. Thus different settings/noise modes can
select different subsets. In noise mode the 3 us denominator includes background
that a shorter gate need not include. Fractions must not be interpreted as a
calibrated energy efficiency or directly compared as equal-population estimates.

## Results: central 100 keV, 32 events

Noise-free first-gate charge relative to the 3 us reference (all 32 events eligible):

| Post-trigger integration [ns] | Mean charge fraction | Mean candidates/source ROI, minimum holdoff |
| --- | --- | --- |
| 100 | 24.9% | 5.38 |
| 300 | 61.7% | 3.75 |
| 600 | 86.0% | 2.53 |
| 1000 | 95.3% | 1.91 |
| 1500 | 98.9% | 1.34 |
| 2000 | 99.9% | 1.03 |

Increasing holdoff alone reduces fragmentation but does not recover the charge
outside a short first gate. At 1000 ns integration, holdoffs 1004/1504/2504 ns
produce mean candidate counts 1.91/1.34/1.00; the first-gate fraction stays 95.3%.
All 32 noiseless events have a prompt candidate under these three settings.

With the existing illustrative 1 MHz dark-attempt rate, 2 mV threshold and XT/AP,
prior noise activity makes long holdoff costly:

| Integration [ns] | Holdoff [ns] | Blocked at source | Candidate before +100 ns | Zero candidates in source ROI |
| --- | --- | --- | --- | --- |
| 1000 | 1004 | 15/32 | 17/32 | 0/32 |
| 1000 | 1504 | 22/32 | 10/32 | 0/32 |
| 1000 | 2504 | 21/32 | 11/32 | 3/32 |
| 1500 | 3004 | 24/32 | 9/32 | 6/32 |
| 2000 | 3504 | 26/32 | 6/32 | 11/32 |

Finite-sample counts need not vary monotonically across settings because accepting
or suppressing one trigger changes later eligibility. The table shows the tradeoff,
not an intrinsic limitation of BGO or a calibrated instrument dead time. A late
noise candidate can fill an evaluation interval after its signal trigger was lost;
zero-candidate counts alone therefore underestimate association problems.

The current isolated-source study supports exploring roughly 1–1.5 us integration
for charge collection, but **does not select an optimal operating setting**. With
these noise/threshold assumptions, trigger validation/threshold choices must be
examined jointly with holdoff. A measured waveform/noise spectrum, operating
bias/temperature, intended event rate and energy/timing goals are needed for an
actual instrument choice. Acquisition prehistory, record length and baseline
estimation also require separate checks; their current values were held fixed.

## Checks

Five fixed-gate unit tests verify fractional-bin charge, exact holdoff endpoints,
non-extending suppression, rearming instead of level retriggering, non-overlapping
area, empty/truncated windows and invalid configs. The public CLI was exercised on
the retained noise example. Existing readout/acquisition tests remain intact.
No measured-data fit or changes to the original BGO optical assumptions were made.
