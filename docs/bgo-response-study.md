# Illustrative BGO end-to-end response study

This study runs the actual GDML BGO transport, cell response, acquisition noise,
waveform/ADC and candidate extraction. It is distinct from the analytical readout
benchmarks, which inject synthetic charges without a crystal. Results describe
this example's assumptions; they are not measured BGO performance, DOI resolution,
a coincidence measurement, or device calibration.

## Fixed conditions and reproducibility

- One 12 x 12 x 10 mm BGO crystal, one 5.8 mm square sensor on the +Z face; the
  existing ideal collector and example optical parameters (including 8000 photons/
  MeV and 300 ns scintillation decay) are retained.
- Point-source electrons directed along +Z, with true start time 7 ns. Depth scan:
  local z = -3, 0, +3 mm at 100 keV. Energy scan at z=0: 50, 100, 200 keV.
  The shared central 100 keV point makes five distinct conditions, 32 events each.
- The first event origin is at 1000 ns, followed by 10,000 ns spacing. Transport
  seeds vary deterministically by condition and are recorded. Both response modes
  reuse exactly the same per-condition photon input/hash and photon RNG seed.
- Noise off versus all three illustrative noise effects on (dark/XT/AP together).
  Existing cell, noise and readout JSONs are unchanged; complete responses,
  waveform CSVs, input snapshots, manifests, seeds and hashes are retained.

Run after sourcing the Geant4 environment:

```sh
python3 studies/bgo_response.py build/g4pec \
  --output-dir output/bgo_response_study_new --events 32
# Recompute only evaluation on an existing, complete study with unchanged configs:
python3 studies/bgo_response.py build/g4pec \
  --output-dir output/bgo_response_study_new --events 32 --reanalyze
# Optional matplotlib plot:
python3 studies/plot_bgo_response.py output/bgo_response_study_new/report.json \
  output/bgo_response_study_new/comparison.png
```

The initial output directory must be new. `--reanalyze` deliberately updates only
summary/evaluation files, reusing existing transport/response/readout artifacts.
The retained local study is `output/bgo_response_study/`; it is ignored by Git.
The report has `complete: true` only after all conditions finish. The full study
is an opt-in characterization job, not a physics pass/fail regression with frozen
counts. CTest `bgo_evaluation` checks the evaluation window/ambiguity/statistics
helpers on synthetic boundary cases.

## What is measured

Transport metrics include energy deposited in the crystal, scintillation count,
arrivals per event, first arrival delay, and pooled photon arrival-time quantiles
relative to the primary start. Pooled quantiles weight photons, not events equally.

For evaluation only, integrate baseline-subtracted ADC voltage in the fixed
`[primary start, primary start + 3000 ns)` window and divide by the declared
transimpedance. This **truth-aligned evaluation charge is not the production
candidate charge estimator**. It measures total signal in a known interval even
when the readout splits an event into several candidates. Noise in that interval
is included; it is not subtracted using truth. The report separately retains the
sum of candidate-gate charges, which can spill outside the evaluation interval.

Candidate association for this study uses the first-threshold timestamp in
`[primary start - 1 ns, primary start + 3000 ns)`. The 1 ns lead allowance covers
the previously documented bin-average/interpolation bias. This matching happens
only after the truth-independent reconstruction, never inside the readout algorithm.
The measured delay contains transport, photon statistics, PDE, cell response and
threshold/sampling effects; it cannot be attributed to electronic time walk alone.

If a candidate that triggered before this matching interval has a gate overlapping
the primary start, flag the event as having a pre-existing gate. Keep raw matching
statistics, but exclude those events from the conditional first-delay statistic
(`unambiguous_first_delay_ns` in the report). That field name means only **no flagged
pre-existing gate**: it does not prove signal/noise identity or eliminate all
association ambiguity. Report the reduced sample count and standard error.

Means, event-to-event SDs and standard errors are reported. Differences between
noise modes are also summarized as paired per-event differences on their common
eligible subset. Candidate-window occupancy includes a Wilson 95% interval;
it is not noise-corrected detection efficiency. Candidates outside evaluation
intervals are counted but are not automatically classified as pure dark counts.

## Observed results (32 events per condition)

All 160 electrons deposited their nominal energy in the crystal in this run.
No ADC rail samples or acquisition-clipped photons occurred. The latest recorded
arrival was about 3091 ns after its primary, well before the next source event;
one photon in the central 100 keV case arrived after the 3000 ns evaluation window.
The script checks the isolation guard and fails on clipping/rails rather than
silently presenting those cases as unsaturated isolated measurements.

100 keV depth scan (local +Z approaches the sensor), mean ± standard error:

| Source z [mm] | Arrivals/event | 3 us charge, noise off [pC] | 3 us charge, noise on [pC] |
| --- | --- | --- | --- |
| -3 | 133.41 ± 2.04 | 6.338 ± 0.185 | 7.750 ± 0.219 |
| 0 | 146.50 ± 1.66 | 6.788 ± 0.164 | 8.456 ± 0.194 |
| +3 | 154.38 ± 2.25 | 7.754 ± 0.164 | 9.480 ± 0.247 |

This run shows depth-dependent collection/charge in the declared geometry. The
noise-free first-candidate delays are 7.34 ± 1.15, 6.14 ± 1.10 and 7.59 ± 1.31 ns
respectively; these small samples do not establish a monotonic depth timing trend.
No DOI classifier, DOI resolution or energy/depth disentanglement is evaluated.

Central energy scan, mean ± standard error:

| Electron energy [keV] | Arrivals/event | Charge, noise off [pC] | Charge, noise on [pC] | First delay, noise off [ns] |
| --- | --- | --- | --- | --- | --- |
| 50 | 73.28 ± 1.46 | 3.634 ± 0.154 | 4.685 ± 0.187 | 16.34 ± 2.60 |
| 100 | 146.50 ± 1.66 | 6.788 ± 0.164 | 8.456 ± 0.194 | 6.14 ± 1.10 |
| 200 | 294.97 ± 3.50 | 14.168 ± 0.330 | 17.047 ± 0.414 | 5.17 ± 0.85 |

Arrival counts scale approximately with deposited energy. Noise-free charge per
keV is about 0.073, 0.068 and 0.071 pC/keV; this is a preliminary response check,
not a calibrated linearity specification. The combined noise model raises charge;
this paired on/off comparison does not isolate the contribution of each mechanism.

## Important readout limitations exposed by the study

Every evaluation interval had at least one candidate in both modes (32/32 per
condition), but that does not demonstrate 100% efficiency: the Wilson lower bound
is about 89.3%, and noise can satisfy the occupancy criterion. More importantly,
**one source event is not one reconstructed candidate**. Without noise, an event
produces on average 3.25 to 4.06 candidates with the current fast shaper/threshold
and short padding compared with BGO's 300 ns decay. With noise the corresponding
averages are 4.72 to 5.44. This fragmentation matters for future energy/event
building and coincidence processing.

Noise also creates gates that merge into later source signals while retaining the
earlier noise trigger. Pre-existing-gate flags occur in 5/32, 2/32, 4/32 depth-scan
events, and in 2/32 (50 keV) and 3/32 (200 keV) central events. In the central 100 keV
case, blindly taking the next timestamp inside the source interval gives a 56.0 ns
mean delay. Excluding the two pre-existing-gate cases gives 6.08 ± 1.18 ns (30 events),
versus 6.14 ± 1.10 ns without noise. The former large number is therefore strongly
affected by candidate association/merging and must not be called intrinsic timing
resolution degradation. Comparing conditional subsets also carries selection bias.

The next readout work should address ADC-only event building/integration appropriate
to the slow scintillation signal, and test its tradeoff between fragmentation,
noise merging, charge loss and timing. Truth may evaluate that work but must not
supply reconstruction gates in production. Only after this distinction is handled
should candidate counts be interpreted as physical singles for DOI/coincidence
extensions. Increasing statistics alone does not fix this readout definition.
