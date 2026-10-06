# BGO: separating source spacing, candidate splitting and noise effects

2026-10-06. **For the tested 10 µs spacing, dark-origin trigger holdoff caused the
reduction in prompt candidates.** At shorter spacing, holdoff from earlier events
and waveform overlap also matter without noise. Splitting a single event into
multiple candidates is a separate effect.

## Conditions and separation method

This study reuses retained transport for 32 center-injected 100 keV electrons in
`output/bgo_response_study/center_100keV/`. It is not a 511 keV gamma-source measurement
and does not substitute a new Geant4 random realization.

- Integration: 4 ns pretrigger, 1000 ns after trigger; non-extending holdoff 1504 ns.
- Threshold 2 mV, release 1 mV, sampling 1 ns; other settings match retained inputs.
- Noise: whole-channel dark-attempt rate 1 MHz, XT probability 0.1, AP probability
  0.05. These are illustrative, not calibrated values.
- Each photon's PDE draw is assigned once in event/time/track order and reused after
  acquisition-time sorting. Shorter spacing can reorder photons without changing
  their assigned random draws.
- First, events are read individually with reset cell, waveform and trigger states.
- Next, shifted independent avalanche streams are superposed and compared with
  reprocessing identical photons using persistent cell state. The former introduces
  only readout overlap; their difference isolates inter-event recovery effects.
- Noise is added using the same photons/PDE draws. For 10 µs spacing, dark avalanches
  and their XT/AP descendants are removed from the realized history, then readout
  alone is rerun.

Reconstruction functions receive only ADC samples and readout settings. Comparisons
with injection times and dark-ancestry removal below are diagnostic evaluation only,
not procedures available to measured-data reconstruction.

## 1. Candidate splitting persists for isolated events

| Readout | Mean candidates per event |
| --- | ---: |
| Legacy threshold/release window | 4.0625 |
| Fixed gate and holdoff | 1.34375 |

Even with fixed gates, 11/32 events split into multiple candidates. No other
injections or noise exist, so source spacing cannot explain this. Late photons
create new threshold crossings accepted after holdoff. The first fixed-gate
candidate collects a mean 95.26% of the isolated waveform's total ADC charge.

## 2. Shorter spacing reduces prompt candidates without noise

The following results use persistent cell state and **no noise**. Prompt means
`[-1,100)` ns relative to injection time.

| Spacing | Prompt accepted candidate /32 | Prompt crossing blocked by holdoff /32 | No prompt crossing /32 |
| --- | ---: | ---: | ---: |
| 10 µs | 32 | 0 | 0 |
| 3 µs | 22 | 10 | 0 |
| 1.5 µs | 5 | 27 | 0 |
| 0.5 µs | 4 | 8 | 20 |

Although 3 µs exceeds the 1.504 µs holdoff, a late candidate from an earlier event
starts a new holdoff extending into the next injection. At 0.5 µs, waveform overlap
changes threshold/release rearming and also reduces prompt crossings themselves.

Superposed independent avalanches and persistent-state processing produce
**identical ADC code sequences in all four conditions**. Recovery-induced total
charge reduction is zero in double precision at 10/3/1.5 µs and about `1.18e-8`
fractionally at 0.5 µs. For this photon load and cell count, cell recovery/saturation
is not needed to explain the observed candidate reduction.

## 3. At 10 µs, noise acts through dark-origin holdoff

| Condition at 10 µs spacing | In holdoff at injection /32 | Prompt accepted candidate /32 |
| --- | ---: | ---: |
| No noise | 0 | 32 |
| Dark counts, XT and AP | 22 | 10 |
| Same noisy history with dark-origin components removed | 0 | 32 |

All 32 noisy events still have a prompt threshold crossing, but holdoff blocks 22.
Removing dark-origin components changes all 22 from blocked to unblocked.
Photon-origin XT/AP and the original cell response remain. This is a **causal readout
comparison on the same realized history**, not a complete simulation of dark-free
hardware or a new realization recomputed from cell states.

## Evaluation limits

- Acquisition extends 6 µs beyond the final event origin, with no input-photon clipping
  or ADC rails. No candidate in an injection evaluation interval is truncated. Each
  noisy acquisition has one end-truncated background candidate outside these intervals.
- Candidates are counted over `[injection-1 ns, min(injection+3 µs, next injection-1 ns))`,
  avoiding double assignment at short spacing.
- Prompt-candidate presence is time-window occupancy, not detection efficiency with
  noise/earlier events truth-classified. Delayed-candidate attribution is especially
  ambiguous at short spacing.
- Holdoff at injection and suppression of a prompt crossing are distinct metrics:
  at noiseless 1.5 µs they count 28 and 27, respectively.
- Results describe 32 events and one noise realization. Absolute rates or optimal
  settings require more events and seeds. Spacing changes acquisition length; complete
  noise branching realizations are not assumed identical across conditions.
- Periodic primary origins do not model random decay times or source activity in Bq.

## Reproduction and interpretation

```sh
python3 studies/bgo_cause_separation.py output/bgo_response_study \
  --output-dir output/bgo_cause_separation_new
```

Retained verification is in `output/bgo_cause_separation_verified/`. report.json
contains settings, RNG policy, input/ADC hashes and summaries; spacing directories
contain timelines, avalanche histories, candidates and event evaluations. Keep the
original study directory for transport inputs.

Two tests registered as cause_separation verify PDE-draw correspondence under
reordering, disjoint evaluation intervals, holdoff endpoints and crossing suppression
counts. All eight related CTests passed at this milestone.

Potential follow-up comparisons could separately address dark-sensitive thresholds
and retriggering of individual BGO signals, then use random intervals at a target
rate. Parameter tuning is not part of the current implementation work. Extending
acquisition alone or holdoff alone cannot resolve every cause.
