# Waveform generation and ADC readout, version 1

`tools/readout.py` converts all acquisition avalanches into one channel waveform,
quantizes it, and extracts threshold-based candidate singles from ADC samples.
It does not use source event IDs, particle tracks, causes or ancestry to find
signals. The detector remains one crystal and one readout channel; DOI and
coincidence reconstruction are not implemented.

## Run and inputs

```sh
python3 tools/readout.py output/single_channel_acquisition_history.csv \
  output/single_channel_acquisition_response.json output/single_channel_readout \
  --config examples/single_channel_readout.json
```

Acquisition response now writes `_history.csv` and `_channel.csv` in both noiseless
and noise-enabled modes. History contains successful avalanches from state start,
including unobserved warmup. **Do not substitute the observed-only avalanche CSV**:
pre-window pulses can leave tails in the recorded waveform. A newer response manifest
binds history with a SHA-256 hash, checked by the readout loader. Older manifests
without that hash are accepted with observation/window/count consistency checks;
these do not prove byte-for-byte association. Readout records hashes of all inputs.

The loader uses only history time, charge, ID uniqueness and observation flags.
Channel and clock come from the response manifest. Missing warmup rows, incompatible
counts, invalid values and output overwrites are rejected. Independent-event
responses are not accepted because they do not define a common acquisition clock.

## Linear shaper and ADC

Each avalanche with charge Q pC at t0 contributes the following voltage above the
configured baseline, for u = t - t0 >= 0:

```text
V(u) [mV] = R [ohm] * Q [pC] * (exp(-u/tau_f) - exp(-u/tau_r)) / (tau_f - tau_r)
```

For u < 0 the response is zero. The full voltage-time integral divided by R is Q:
1 pC/ns is 1 mA, and 1 mA * 1 ohm is 1 mV. This is an assumed area-normalized linear
impulse response, not a circuit simulation or a calibrated sensor pulse shape.
Use `fall_time_ns >= 1.01 * rise_time_ns` to avoid near-degenerate numerical subtraction.
The configured gain/recovery is already in Q and is not applied again here.

Pulses superpose before ADC conversion. An exponential-state recurrence integrates
each sampling bin analytically, including fractional-bin arrivals and pre-window
tails. The analog sample is the **bin-average voltage**, timestamped at the bin
center; it is not instantaneous point sampling. A final partial-width bin is
supported. Infinite pulse tails are not renormalized when truncated by the window.

ADC conversion divides by `adc_lsb_mV`, rounds to nearest with half steps upward,
and clips to `[0, 2^adc_bits - 1]`. Rail-code samples are flagged `saturated`; this
is an observable rail warning, not proof that the underlying voltage exceeded the
rail (quantization alone can produce an endpoint code). Baseline is a known fixed
configuration value. No electronic noise, baseline drift/estimation, time jitter,
nonlinearity, analog saturation or channel-to-channel calibration is modeled.

The illustrative config uses rise/fall constants 2/20 ns, R=1000 ohm, 1 ns bins,
20 mV baseline, 16 bits and 0.05 mV/LSB. These are engineering choices, not hardware
recommendations. A sample budget rejects overly large requests rather than silently
coarsening the waveform. Computation is linear in samples plus sorted pulses;
results are currently held in memory.

## ADC-only candidate extraction

`extract_singles` operates on sample codes, timestamps/bin widths and rail flags:

1. Subtract the known baseline from digitized voltage. Start an excursion at the
   high threshold (`threshold_mV`); release it at or below `release_mV`.
2. Interpolate the high-threshold crossing between sample centers. If already above
   threshold at the first sample, use that sample center and mark truncation: the
   true crossing is outside/unknown, not inferred from avalanche truth.
3. Pad each excursion by `pre_samples` and `post_samples`. Merge overlapping padded
   gates and retain their earliest threshold time plus the number of crossings.
   An ADC bin is never integrated twice across output gates.
4. Integrate baseline-subtracted ADC voltage over the gate's actual bin widths and
   divide by R to obtain charge in pC. Record peak amplitude, rail count and a
   truncation flag (window-limited excursion or padding).

These are readout candidates, not source events: pileup can merge multiple source
interactions, noise can create candidates, and thresholds can lose pulses. A finite
gate can miss charge in tails; ADC rounding/clipping also changes charge. There is
no truth-derived charge correction. Leading-edge time has sampling uncertainty and
amplitude-dependent time walk; it is not the photon time or a calibrated interaction
time. No energy calibration or position/DOI estimate is attached.

An optional [fixed integration and holdoff mode](bgo-window-scan.md) is available
with `--gate-config`; its gates replace the release-based padding/merging rules
above. The original mode remains the default. Both use ADC crossings, never truth.

## Outputs

| Suffix | Contents |
| --- | --- |
| `_waveform.csv` | Sample ID, bin edges/center, analog average voltage, ADC code, digitized voltage, rail flag |
| `_singles.csv` | Readout-local single ID, channel, threshold time, gate edges, integrated charge, peak, crossing count, rail count and truncation |
| `_readout.json` | Model/schema, full config/provenance, clock/window, channel/transport identity, input hashes and output counts |

Analog voltage is diagnostic only and is not used to reconstruct singles. Single
IDs are scoped to this readout artifact; join using the readout manifest/hash and
single ID, not a Geant4 event ID. No cross-artifact globally unique single key is
claimed yet. Configuration is strict and all output paths are protected. Failures
while writing remove files created by that invocation.

## Verification and retained example

Seven tests cover analytic finite-window integrals and individual bin averages,
fractional arrival times, pre-window tails, pulse superposition, ADC rounding/rails,
ADC-only interpolated threshold times and gate merging, empty/truncated windows,
parameter/sample-budget rejection, warmup history exports, repeatability and output
protection. Removing every event/track/cause/ancestry field from history and reversing
its rows leaves waveform and reconstructed singles identical (with the input hash
binding updated to identify the edited test fixture).

The retained noisy gamma replay produced `output/readout_example_*`: 4,640
avalanches give 100,000 samples and 86 readout candidates with no rail samples for
the illustrative configuration. This candidate count is neither detection efficiency
nor the number of simulated source events. Data are ignored by Git.

Further work includes targeted time-walk/pileup/readout-efficiency studies and
optional electronics effects, then detector/source extensions and calibrated
analysis interfaces suitable for DOI and coincidence processing.

## Time-walk, pileup and charge-bias benchmark

`tests/check_readout_benchmarks.py` characterizes the current implementation with
analytical oracles and fixed synthetic pulses. It does not tune thresholds or
silently correct the output. Run:

```sh
python3 tests/check_readout_benchmarks.py --report output/readout_validation_new.json
```

The current retained report is `output/readout_validation.json`; the illustrative
plot is `output/readout_timewalk.png`. CTest registers this as `readout_benchmarks`.

Time walk means that larger pulses with the **same true onset** cross a fixed
voltage threshold earlier. For the example 2 mV threshold, the continuous analytic
rising-edge crossings are 1.4719, 0.5857, 0.2690 and 0.1295 ns after onset for
charges 0.08, 0.16, 0.32 and 0.64 pC respectively. A 0.04 pC pulse never reaches
the threshold. These times are roots of the declared double-exponential waveform,
not measured device timing parameters.

The benchmark scans four sub-bin phases (0, 0.25, 0.5, 0.75 ns) and those five
charges. It checks detection/no-detection, decreasing measured time with amplitude,
and a predeclared 1.05 ns absolute deviation limit from the continuous crossing
for the coarse 1 ns sampler. Maximum observed deviation is 0.3732 ns. That pass
**does not establish precision timing**: bin-average samples interpolated between
centers can give an onset estimate earlier than the true causal pulse onset. At
0.64 pC and zero phase the estimate is -0.2015 ns relative to the true onset,
while the analytic threshold crossing is +0.1295 ns. This is a sampling/estimator
bias on top of amplitude-dependent time walk, not premature physical light arrival.
The present single output has no dedicated correction for either effect.

At 0.02 ns bins and 0.0001 mV ADC steps, four charges at phase 0.007 ns approach
the continuous crossing with errors at most 0.000042 ns, below the predeclared
0.025 ns acceptance bound. This is a noiseless numerical convergence check;
it is not a prediction of detector or electronics time resolution. Constant-fraction
timing, fitted-pulse timing or calibrated amplitude correction remain future options.

The two-pulse scan uses 0.16 pC pulses separated by 0, 5, 20, 40, 60, 80, 100 and
140 ns. The current settings produce one candidate through 80 ns and two at 100
and 140 ns. At 60/80 ns there are already two threshold excursions, but the padded
integration gates overlap and are deliberately merged. Therefore this scan is a
characterization of this amplitude, sampling phase and gate configuration, **not a
universal 100 ns resolving time**. Each gate pair is checked for non-overlap, and
charge is compared with the analytic waveform area over the actual union of gates.

For every non-rail gate the ADC charge must agree with the exact gate area within
`0.5 * LSB_mV * total_gate_duration_ns / R_ohm + 1e-10 pC`, the sum of per-bin
rounding-error bounds. This separates finite-gate tail loss from ADC rounding.
For one 0.16 pC pulse, post-padding of 0/10/40/100 samples recovers respectively
87.5625% / 92.46875% / 98.375% / 99.875% of input charge in the current ADC output.
Longer gates recover more tails but can merge more nearby signals. The default
40-sample gate thus has about -1.63% charge bias for this particular isolated pulse.

A separate forced-saturation case (100 pC, 8 bits, 1 mV/LSB) produces 64 rail
samples and only 19.621 pC reconstructed charge. Rail-flagged candidates are not
corrected or silently discarded; downstream energy/quality selection must handle
them explicitly. This is a clipping regression case, not a default-config limit.
