# Acquisition noise model, version 1

Use `tools/digitize_cells.py --timeline ... --noise examples/single_channel_noise.json`
to enable noise on the single-channel acquisition clock. Omitting `--noise` retains
the noiseless implementation and its output format. Noise requires a timeline and
identified transport inputs; it is not supported in the independent-event mode.

This is an explicit simplified engineering model with illustrative parameters, not
a calibrated SiPM description. Noise simulation itself adds no reconstruction or detector channels. The separate
[waveform/readout stage](waveform-readout.md) now extracts ADC-based candidates;
DOI and coincidence selection remain future work.

## Parameters and assumptions

The strict schema-1 JSON requires a nonempty `provenance` and these parameters:

| Parameter | Example | Meaning |
| --- | --- | --- |
| `dark_rate_hz` | 1000000 | Whole-channel Poisson **attempt** rate, before dead-time suppression |
| `crosstalk_probability` | 0.1 | Probability of one prompt neighbor attempt from a fully recovered avalanche |
| `afterpulse_probability` | 0.05 | Probability of one delayed same-cell attempt from a fully recovered avalanche |
| `afterpulse_time_ns` | 50 | Mean of the exponential afterpulse-delay distribution |
| `max_candidates` | 1000000 | Hard bound on scheduled in-window/warmup candidates, including photons |

Rates/probabilities must be nonnegative, the delay positive, and XT probability plus
AP probability strictly less than one. The latter conservatively bounds expected
branching below one; finite windows and a candidate budget still enforce finite
resource use. The budget is at most two million and is not a physics truncation:
exceeding it fails the run before any output is created.

Dark attempts follow homogeneous Poisson times from `state_start_ns` to the exclusive
window end. Each chooses uniformly among all cells. Dark rate is not multiplied by
cell count. An attempt directly triggers an available cell, with charge determined
by its recovery; it is lost during dead time. Thus the configured attempt rate and
observed dark avalanche rate can differ.

Every successful avalanche, including noise avalanches, can independently generate:

- One simultaneous crosstalk attempt with probability `p_xt * parent_recovery`.
  Choose uniformly among existing orthogonal neighbors, with no wrapping or diagonal
  coupling. The total attempt probability is unchanged at edges; only neighbor
  selection changes. A one-cell grid cannot produce this crosstalk.
- One same-cell afterpulse attempt with probability `p_ap * parent_recovery` and an
  exponential positive delay of the configured mean. When released, it competes
  with all intervening photons/noise and uses the cell's current recovered charge.

Only successful avalanches spawn children. Both internal causes bypass optical
PDE: PDE is applied once to incident photons, never again to dark/XT/AP attempts.
A cell can fire only once at one timestamp. Available internal triggers otherwise
have unit trigger probability; voltage-dependent release/trigger probabilities,
multiple trap populations and more detailed optical crosstalk are not modeled.
Recovery-scaled offspring probabilities are declared model choices, not inferred
from a measured device.

## Clock, state, RNG and finite windows

Cells start fully charged and traps empty at `state_start_ns`. Supplied photons and
dark attempts before the observation window warm up this state, and their delayed
children can enter the observed window. No earlier dark or trap prehistory is
invented. This does not claim stationary noise equilibrium; choose an explicit
warmup interval when needed.

One queue interleaves photons, dark counts and correlated children. At equal times,
priority is photon, dark, crosstalk, afterpulse, then insertion order. Input photons
are inserted in time/event/track order. This tie rule is deterministic, not a claim
about sub-time-resolution physics. The window remains `[start, end)`. Delayed
children at/after the end are counted as clipped and not followed. No state/trap
checkpoint is carried into another CLI invocation.

Photon Bernoulli draws retain the existing response RNG. Noise uses a separate
Python RNG whose seed is the SHA-256 integer of `g4pec-noise-v1:<response seed>`.
The independent Poisson candidate stream is generated before correlated branches.
The manifest saves this seed and parameters. A zero-noise configuration reproduces
noiseless photon outcomes. Turning noise on can change photon acceptance through
cell availability, without consuming additional photon-PDE random draws.

## Outputs and truth attribution

With noise enabled:

- `_avalanches.csv` contains **all observed causes**, ordered by queue processing.
  It adds `avalanche_id`, `parent_avalanche_id`, `root_event_id`, `root_track_id`.
- `_history.csv` contains all successful avalanches, including unobserved warmup
  ancestors. IDs are sequential within this response run; every parent reference
  resolves here. The `observed` field marks membership in the observation window.
- `_channel.csv` contains one channel/window row with the total observed avalanche
  count and charge, including noise and zero-output cases. This is integrated
  window accounting, not a trigger or a reconstructed single.
- `_events.csv` and `_signals.csv` retain **direct photon-trigger-only** diagnostic
  attribution. They exclude noise, even photon-induced XT/AP. The existing photon
  arrival accounting identity therefore remains valid.

Dark and correlated-noise rows have empty `event_id` and `track_id`; they are not
Geant4 tracks. A photon-induced descendant carries the ancestor's `root_*` truth
keys and a parent avalanche link. Dark-induced families have empty root keys as
well. Truth labels are for simulation evaluation, never coincidence selection.
History is scoped to the single channel and the transport identity in the manifest.

Manifest `totals.avalanches` counts all observed causes, while
`totals.photon_avalanches` counts direct photon-triggered avalanches.
`observed_by_cause` sums to the former. Only `photon_avalanches`, photon rejections
and excluded photon counts sum to the incident-photon total. Noise diagnostics
record attempts and outcomes over warmup plus observation; these must not be
confused with observed-only counts. The channel's integrated charge sums all
observed avalanche charges.

## Validation

`tests/check_noise.py` has seven tests covering zero-noise equivalence, Poisson dark
attempts, suppression at PDE zero (internal noise still triggers), a two-cell XT
limit, exponential AP release and recovered charge, warmup ancestry/window clipping,
neighbor geometry, parameter/budget rejection, replay and CSV/manifest accounting.

Predeclared statistical checks use fixed independent response seeds:

- 1,000 noise-only 100 ns windows with a 200 MHz attempt rate: expected Poisson
  mean and variance 20. Mean tolerance is six standard errors; variance tolerance
  is six times `sqrt((20 + 2*20^2)/999)`.
- 2,000 isolated fully charged photon avalanches on two cells with `p_xt=0.4`:
  the second cell fires with probability 0.4; a prompt return to the first cell
  is suppressed. The count is checked against a binomial six-sigma interval.
- 2,000 root avalanches with `p_ap=0.4`, delay mean 5 ns and dead time 2 ns:
  the probability of a detected direct AP child by T is
  `0.4 * (exp(-2/5) - exp(-T/5))`, for T=8 and 20 ns. Each count has a binomial
  six-sigma tolerance. Every successful descendant's charge is checked against
  its parent's time and the declared recovery equation.

On the current run the dark-attempt mean/variance are 19.913/21.0104; XT fires the
second cell in 796/2,000 trials; direct AP counts are 386 by 8 ns and 537 by 20 ns.
These checks validate this declared model's limits, not commercial device behavior.

A retained replay of the 64-event truth-benchmark gamma input uses
`output/noise_example_timeline.json` and `output/noise_example_*`: 12 ns event
spacing and a 100,000 ns window produce 3,890 direct photon avalanches, 95 dark,
427 XT and 228 AP avalanches with the example configs and seed 42. Inputs/results
are ignored by Git and must be regenerated on another machine.
