# Session handoff — 2026-10-06

## Restore on another computer

Clone https://github.com/ohayotaro/g4pec (branch `main`). Source, GDML, macros,
tests, rendering/digitization scripts and documentation are tracked. `build/`
and `output/` are intentionally ignored; binaries, result CSVs and preview images
must be regenerated. The local Geant4 installation and this chat are not in Git.

Install a C++17 toolchain, CMake 3.16+, Python 3.9+, and Geant4 11.3+ built with GDML
support (including Xerces-C and the required physics datasets). The tested
environment was macOS with Geant4 11.3.0; other versions/platforms need verification.
Matplotlib is required only for the geometry preview.

```sh
git clone https://github.com/ohayotaro/g4pec.git
cd g4pec
# Source your Geant4 installation's bin/geant4.sh if needed.
cmake -S . -B build -DGeant4_DIR=/path/to/geant4/lib/cmake/Geant4
cmake --build build -j 4
ctest --test-dir build --output-on-failure

build/g4pec examples/single_detector.gdml examples/gamma.mac output/single_channel
python3 tools/digitize.py output/single_channel_run0_photons.csv \
  output/single_channel_run0_events.csv output/single_channel_readout \
  --pde 0.3 --gain 1000000 --seed 42
python3 tools/render_geometry.py examples/single_detector.gdml output/single_channel_geometry.png
```

Choose fresh output prefixes for subsequent runs; existing result files are protected
from overwrite. Numerical results need not be bit-identical across Geant4 versions
or toolchains; run the checks on the destination machine.

## Agreed scope

- New implementation, informed by the private predecessor; do not import its code
  or history. The public repository is the source of truth.
- Minimum example: one crystal and **one SiPM channel**. Keep this baseline while
  building detailed response models.
- All geometry/placement comes from GDML. Physical parameters are externally
  configurable; optical values currently live in GDML, source settings in macros.
- Separate Geant4 optical transport, SiPM/electronics response and analysis.
- DOI reconstruction and coincidence processing are required post-analysis
  capabilities. Follow `docs/analysis-contract.md` when designing data interfaces;
  keep truth labels separate from measured/reconstructed features.
- Verify simulation/model behaviour against analytical/statistical expectations
  and suitable references. Real-device fitting and measurement agreement are the
  user's responsibility, not a deferred project deliverable.
- Example parameters are illustrative. Record assumptions, units and provenance;
  do not claim experimental calibration.

## Completed

The original baseline implementation commit is `7aa6b11`. Subsequent local work
is described below; check `git status` before assuming those changes are committed.
The BGO crystal is 12 x 12 x 10 mm. The coupling layer and sensor are both
5.8 x 5.8 x 0.1 mm, centered on the crystal's +Z face.

An ordered coupling-to-sensor GDML border is the ideal collector. Side/rear skin
absorbs without readout. Startup checks reject missing incoming borders, active
skins, and non-ideal collectors that could apply PDE twice. CSV output preserves
arrival time, energy, local coordinates/direction and channel placement path.
The standalone Python response applies constant PDE and fixed gain.

Checks cover front/side/rear illumination, translated/rotated local coordinates,
analytic flight time, invalid surface definitions, changed channel IDs, PDE
endpoints, charge conversion, seeded replay and gamma-induced scintillation.

## Next work

1. Study trigger validation/threshold together with holdoff using the fixed-gate
   scan (`docs/bgo-window-scan.md`). A 1–1.5 us gate collects most charge in this
   example, but low thresholds plus illustrative dark noise cause prior-trigger
   blocking. Do not select a universal optimum or equate window occupancy with
   signal detection. Acquisition length/prehistory and high-rate source pileup
   remain separate validation tasks.
2. Extend suitable detector/source examples for DOI reconstruction and PEC
   coincidence analysis. The current one-crystal/one-channel model supports neither.

Current limits: constant available-cell PDE and simplified noise; no physical entrance-window response, detailed
electronics, stochastic/correlated source generation or coincidence analysis. GDML replicas
and parameterised placements are rejected; the preview supports only flat,
unrotated boxes. The collector checker does not prove adjacency. A project release
license has not been selected.

Suggested next-session request: "Read README.md, docs/optical-model.md and
docs/handoff.md; verify the build on this PC and continue the next work while
preserving the single-channel baseline."

## Resumed work — 2026-10-06

Added `tests/check_optical_benchmarks.py` and its CTest registration. Fourteen
single-channel synthetic slab cases check exponential attenuation, polarized
Fresnel transmission, Snell direction/position, flight time, Brewster transmission
and total internal reflection. Each uses 20,000 photons and a predeclared
six-binomial-standard-deviation count criterion; zero/one endpoints are exact.
See `docs/optical-benchmarks.md` for geometry, formulas, assumptions and tolerances.
Retained results are in `output/optical_benchmarks_verified/report.json` with
inputs, logs, CSVs and random states alongside it (ignored by Git).

The new time checks exposed a Geant4 11.4 behaviour: scintillation is registered
for optical photons and its particle change overwrites the boundary-updated
velocity with the incident-medium velocity. At normal incidence from n = 1 to
n = 1.5, the 1 + 10 mm path took 0.03669205047 ns instead of 0.05337025523 ns.
`Physics::ConstructProcess` now removes the scintillation registration from
optical photons only; it leaves scintillation for other particles intact. This
preserves transport-only optical photons and restores the analytic flight time.
Both polarization cases and both index directions exercise this regression.

This computer has Geant4 11.4.0, originally built **without GDML**. CMake now stops
with a direct explanation when that component is absent. To verify without
changing the existing installation, a local build-only CMake overlay in
`build/dependencies/geant4-gdml` compiles the matching installed-version GDML
sources from `/Users/ohayotaro/geant4/geant4-source` and links them with the
installed Geant4 libraries. Xerces-C 3.3.0 was built from the Apache source archive
under `build/dependencies/xerces-install`. These are temporary local verification
dependencies, not vendored project code or a normal GDML-enabled Geant4 install.

For this existing checkout, use its configured build:

```sh
source /Users/ohayotaro/geant4/geant4-install/bin/geant4.sh
cmake --build build --target g4pec -j 4
PYTHONPYCACHEPREFIX="$PWD/build/pycache" ctest --test-dir build --output-on-failure
```

When cloning elsewhere or deleting `build/`, follow the standard setup above with
a Geant4 installation built with `GEANT4_USE_GDML=ON` and Xerces-C. The overlay is
ignored and will not be restored by Git. Geant4 11.3 was tested in the original
session; this resumed implementation is verified with 11.4.0 plus its matching
GDML sources. It has not been rerun against 11.3 in this session.

## G4SiPM evaluation — 2026-10-06

Evaluated upstream commit `40b0017f266c0708c39c595ebb4d09385acc2717` with the
installed Geant4 11.4.0, AppleClang 21.0.0, CMake 4.4.3 and a locally built Boost
1.85.0. Original CMake needs a legacy-policy override; the library then fails on
removed `G4OpticalPhysics::Configure` and `std::binary_function`. A narrower build
also encountered the removed `G4VisAttributes::Invisible` housing helper.

The opt-in project `evaluations/g4sipm` compiles the response subset without the
old physics-list/housing helpers, restoring the libc++ comparator base with a
compatibility definition. No upstream source was edited. Its characterization
test passes: mapping, dead areas, recovery, dead time, independent cells and time
ordering, including reproduction of the upstream earliest-trigger rejection.
This is not a pass of the full upstream test suite or a production integration.

The independent cell backend below implements explicit initial state and PDE
ownership. G4SiPM remains an optional comparison reference. Read
`docs/g4sipm-evaluation.md` for evidence, interface mapping, limitations, reproduction
commands and the cell model acceptance contract. Upstream sources and dependencies
live under ignored `build/dependencies/`; the local report is
`build/g4sipm-evaluation/response/response-report.json`. The G4PEC executable and
Python digitizers do not link or import the upstream code.


## Independent cell response — 2026-10-06

Implemented `tools/sipm_cells.py` and the standalone `tools/digitize_cells.py` CLI.
The external versioned `examples/single_channel_cells.json` configures a 116 x 116
cell grid over the 5.8 mm sensor, constant available-cell PDE, gain, dead time and
exponential charge recovery. Events start fully charged; accepted avalanches alone
reset cell recovery. Same-time illumination saturates at one avalanche per cell.
No upstream source was copied or imported. The ideal digitizer remains available.

The CLI validates the single-channel GDML box footprint and arrival/event counts,
orders photons by time/track ID, rejects invalid inputs before writing, and records
parameters, provenance, input SHA-256 hashes and RNG conventions. Read
`docs/cell-response.md` for formulas, output columns, restrictions and run commands.
This is a constant-trigger-probability model with recovering charge, not a model
of recovery-dependent PDE or a calibrated commercial sensor.

All three CTests pass: `optical_pipeline`, `optical_benchmarks`, `cell_response`.
The 12 pure-Python cell tests include six exact occupancy comparisons with 2,000
trials each; all sample means are within one standard error of prediction (the
predeclared acceptance is six standard errors plus 1/2,000 cell). The retained
report is `output/cell_response_validation.json`. Pipeline checks include actual
direct, rotated and gamma-induced Geant4 arrivals plus ideal-limit comparison.

A retained 100-event gamma example uses the prefix `output/cell_response_example`:
37,644 arrivals yield 11,236 avalanches, 26,408 PDE rejections and zero dead-time
rejections with the sample parameters and response seed 42. Its photon/geometry
inputs and ideal/cell responses are in ignored `output/`. Zero dead-time rejections
in this example is not evidence of absent saturation; dense simultaneous synthetic
illumination supplies that validation. Results and local dependencies must be
regenerated after cloning; source changes still require committing/pushing to be
available elsewhere.


## Minimum-geometry truth export — 2026-10-06

Added schema-1 run manifests, dataset/run row keys, resolved placement transforms
and explicit detector grouping. The example crystal is tagged `Truth=Crystal`;
all its non-optical steps are recorded with endpoints in world/local coordinates,
process, time and deposited energy. Track births (including optical ancestry) are
exported separately; event rows include crystal deposit/step totals. Existing
photon/event columns remain a compatible prefix. The cell response validates and
retains supplied transport identity; legacy inputs still work.

See `docs/transport-truth.md` for exact semantics and limitations. The configuration
is still one crystal/one channel, with event-relative timing. No DOI reconstruction,
coincidence processing, acquisition source clock or cross-event response state was
added. Track truth increases output size; do not use truth as a reconstruction
feature. Tests cover joins, deposited energy and rotated-crystal transforms.


## Known-source truth verification — 2026-10-06

Added `tests/check_truth_benchmarks.py` / CTest `truth_benchmarks`: six 10 keV
electron fixtures at three known depths before/after a 90-degree rotation plus
translation, and one 511 keV internal gamma fixture. Four additive crystal-step
columns retain pre/post kinetic energy and entry/exit flags for energy accounting.
The independent oracle checks source positions/times, non-optical boundary flux
and deposits, and ancestry of detected scintillation/Cherenkov light.

Retained report: `output/truth_benchmarks_verified/report.json`. All 72 electron
events contain their 10 keV; 64 gamma events include 16 contained and 48 escape
cases. Maximum gamma energy residual is 1.71e-13 keV versus the predeclared 1e-5 keV
tolerance. All 14,226 arrivals have checked parent chains and birth-step spatial
consistency, including 43 Cherenkov photons. See `docs/transport-truth.md` for
reproduction, exact criteria and limitations. No DOI or coincidence algorithm was
added. The next interface work remains source/acquisition timing and persistent
response state.


## Explicit acquisition response — 2026-10-06

`tools/make_timeline.py` creates a synthetic periodic event-origin schedule tied to
one dataset/run. `tools/digitize_cells.py --timeline ...` interleaves shifted arrivals
and retains shared cell state across source events. A single explicit observation
window supports pre-window warmup; end-window arrivals are excluded and counted.
The response manifest declares the clock and complete schedule. Truth-event signal
summaries are diagnostic attribution, not reconstructed singles. The default
independent-event mode remains available with identical response semantics.

`tests/check_acquisition.py` adds seven deterministic tests for cross-event recovery,
interleaving, warmup, boundaries, invalid schedules, identity and output accounting.
The optical pipeline runs both CLIs on actual gamma-derived arrivals. See
`docs/acquisition.md` for commands and schema. No noise, waveforms, DOI/coincidence
algorithm, stochastic/correlated source generator or state checkpointing was added.


## Acquisition noise — 2026-10-06

Added optional `--noise examples/single_channel_noise.json` (requires timeline).
`tools/sipm_noise.py` interleaves whole-channel Poisson dark attempts, prompt
orthogonal-neighbor XT and exponential delayed same-cell AP. Successful avalanches
can spawn children; probabilities scale with parent recovery and have a subcritical
sum. Internal triggers bypass PDE but share dead time/recovery. A separate seeded
noise RNG preserves the zero-noise photon limit. Candidate limits fail explicitly.

Observed all-cause avalanches and a channel/window charge row accompany complete
warmup/observed history, with parent avalanche and optional root photon keys. Noise
has no fabricated Geant4 event/track ID. Event/signal diagnostics remain direct
photon-only. Read `docs/noise-response.md` before consuming these accounting fields.
Seven noise tests cover analytical/statistical limits and output semantics. Retained
real-transport replay: `output/noise_example_*`. Initialization is fully charged,
empty traps, with explicit finite warmup; no stationary-prehistory or trap/state
checkpointing claim is made. Waveforms, DOI and coincidence remain future work.


## Waveform and ADC readout — 2026-10-06

Added `tools/readout.py` and `examples/single_channel_readout.json`: normalized
linear double-exponential shaping, exact bin-average sampling, ideal quantizing/
clipping ADC and truth-independent hysteretic threshold candidates. Candidate
charge comes from padded, merged ADC gates; time is interpolated leading edge.
Finite-window/gate losses and rail/truncation flags are explicit. This is not DOI,
energy calibration or coincidence reconstruction.

Both acquisition modes now export warmup-inclusive `_history.csv` and `_channel.csv`,
with a history hash in the response manifest. This preserves pre-window waveform
tails even without noise. Seven readout tests check analytic bin areas, superposition,
ADC, trigger/gate semantics, truth-independent replay and file validation. Retained
`output/readout_example_*` has 100,000 samples, 86 candidates and zero rail samples
from the previous noisy gamma replay. See `docs/waveform-readout.md` for commands,
units, config semantics and limitations. The geometry remains one crystal/channel.


## Readout characterization — 2026-10-06

Added `readout_benchmarks` CTest and `tests/check_readout_benchmarks.py`. Retained
report/figure: `output/readout_validation.json`, `output/readout_timewalk.png`.
No readout algorithm or calibration was changed. Five amplitudes/four sample phases
verify fixed-threshold time walk; the 1 ns-bin crossing error reaches 0.3732 ns and
can precede true onset due to bin averaging/interpolation. A refined noiseless
sampler converges to analytic crossings. This is not a timing-resolution claim.
Two 0.16 pC pulses merge through 80 ns and separate at the tested 100/140 ns gaps;
at 60/80 ns the merge comes from padded gates despite two crossings. Default
isolated-pulse charge bias is about -1.63%; gate integrals agree within ADC rounding
bounds. A forced-saturation case validates rail flags and charge loss. See the
waveform contract for acceptance bounds, limitations and reproduction.


## BGO end-to-end characterization — 2026-10-06

`studies/bgo_response.py` runs five conditions: 100 keV electrons at z=-3,0,+3 mm,
and central 50/200 keV, 32 events each, spaced by 10 us. Each transport realization
is replayed with/without the same example dark/XT/AP noise. Readout uses ADC only;
subsequent evaluation uses a known-source 3 us charge ROI and reports candidate
matching ambiguity, including pre-existing noise gates. Three helper tests are
registered as `bgo_evaluation`. No detector/response/readout parameters were tuned.

Retained full artifacts/report/plot: `output/bgo_response_study/`. All events deposit
nominal energy, no rails/acquisition clipping occur. Central noise-free ROI charges
are 3.634/6.788/14.168 pC at 50/100/200 keV. Depth-dependent collection is observed,
not DOI resolution. Candidate fragmentation (3.25–4.06 per input without noise) and
noise-triggered gate merging limit use as physical singles. See the study document
for SEs, exclusions, conditional timing and reproducibility; do not interpret raw
window occupancy as noise-corrected detection efficiency. The report is descriptive,
not a regression requiring identical Monte Carlo counts on all Geant4 versions.


## Literature-informed window scan — 2026-10-06

Added optional `--gate-config` fixed ADC integration/non-extending holdoff mode
(`tools/fixed_gate.py`), with five unit tests. Gates use measured threshold times,
exact partial-bin overlap and non-overlapping windows. `studies/bgo_window_scan.py`
reuses the prior 10 ADC traces across 18 gate/holdoff settings each (180 total).
Retained configs/candidates/evaluation/report are in `output/bgo_window_scan/`.
Central 100 keV noise-free first-gate recovery versus a 3 us reference is 86.0%,
95.3%, 98.9% at 600/1000/1500 ns. Longer holdoff reduces fragmentation but prior
noise triggers block later source triggers. No optimal or calibrated setting was
chosen; no optical/noise/ADC parameters were changed. The original readout mode
remains the default. `examples/bgo_fixed_gate.json` is an exploration example.

The window-scan document records primary literature (BGO decay measurements and
ADC gate-width experiments), source-access limitations, implementation definitions
and parameter-calibration responsibility. This scan varies integration/holdoff;
it does not sweep acquisition record length, baseline estimation, source rate or
threshold. The next meaningful comparison is trigger validation/threshold vs
noise blocking, using the same truth-free reconstruction boundary.

## User-configurable settings — 2026-10-06

Added `docs/user-settings.md` with a parameter map, editable JSON examples,
timeline generation, processing commands and rerun boundaries. Existing parameter
schemas and readout defaults remain unchanged. Added a read-only
`tools/validate_settings.py` preflight using the runtime configuration validators;
it optionally checks geometry footprint, timeline identity/event coverage and the
acquisition-duration/sample-interval budget. Fixed-gate reports explicitly mark
`pre_samples`/`post_samples` inactive. This validates configuration consistency,
not physical calibration or signal containment.

The new `user_settings` CTest passes (two unit tests), covering custom thresholds,
invalid hysteresis, timeline identity and sample limits. The combined example CLI
also passed against retained transport/timeline files. The prior ten CTests passed
before this addition; this addition was verified with the targeted settings test.

## BGO cause separation — 2026-10-06

Added `studies/bgo_cause_separation.py` and a Japanese report in
`docs/bgo-cause-separation.md`. Retained results: `output/bgo_cause_separation_verified/`.
Reuses the central 100 keV electron transport (32 events), with a fixed per-photon
PDE draw assignment across reordered arrivals. Isolated events still fragment:
4.0625 legacy or 1.34375 fixed-gate candidates/event. For 10/3/1.5/0.5 us spacing,
noiseless prompt-window occupancy is 32/22/5/4 out of 32. Isolated-pulse replay and
shared-cell simulations produce identical ADC codes for all four spacings;
inter-event recovery is negligible here. At 10 us, full noise suppresses 22 prompt
crossings via holdoff. Removing dark-rooted avalanches from that realized history
restores all 32 prompt windows, retaining photon-rooted XT/AP and realized cell
response. This is a conditional readout ablation, not a recalibrated detector.

No photon clipping or ADC saturation; end-truncated background gates are outside
source evaluation slots. Short-spacing slots are disjoint; occupancy is not
truth-matched efficiency. The new 2-test `cause_separation` CTest and seven related
response/readout/evaluation CTests pass. No transport implementation was changed.

## Coincidence post analysis — 2026-10-06

At the user's request, implemented coincidence selection before multi-channel
transport. Existing response/readout parameter values are unchanged. The tentative
multi-channel changes were removed. `tools/coincidences.py` consumes one acquisition
single stream per declared detector, with a user-declared common clock and additive
offsets, allowed oriented detector pairs, -W <= tB-tA < W, inclusive charge cuts,
and optional rejection of truncated/rail-containing candidates. All eligible pairs
are retained; constituent multiplicities and ambiguity are recorded. Truth IDs and
transport identity do not select pairs. Explicit pair budgets and no-overwrite
output handling are implemented.

New readout manifests hash their singles CSV; the selector verifies the hash when
available and marks older unhashed manifests explicitly. The example in
`examples/coincidence/` produces 3 synthetic pairs (2 ambiguous), retained in
`output/coincidence_example_coincidences.{csv,json}`. See `docs/coincidences.md` for
clock assumptions, schema, controls and limits. No correlated-source transport,
calibrated energy selection, detector-channel aggregation or DOI claim is made.

Seven new tests cover boundaries, offsets, charge/quality cuts, truth removal,
brute-force comparison on three randomized streams, multiplicity, invalid inputs,
hashes, pair limits and the waveform-readout-to-coincidence connection. All 13
CTest entries passed (35.75 s), including existing Geant4 optical/truth benchmarks.

## PEC packaging and orientation constraint — 2026-10-06

The user clarified that PEC size limits the available SiPM count and that the
present SiPM arrangement should stay. Do not resume the proposed channel expansion
or make additional SiPMs a prerequisite for DOI/coincidence work. The exact physical
mapping of the synthetic A/B coincidence inputs remains to be defined from the
allowed detector arrangement; synthetic stream labels do not imply added sensors.

Verified `examples/single_detector.gdml`: sensorBox is X=5.8, Y=5.8, Z=0.1 mm;
sipm is unrotated at (0,0,5.15) mm. Its sensitive entrance at Z=5.10 mm is already
parallel to XY, with normal along Z, as requested. No geometry or response parameters
were changed. Updated the roadmap/analysis contract to preserve this arrangement
and assess DOI observability within the permitted readout rather than assuming
charge sharing from extra channels.

## Confirmed physical A/B and project origin — 2026-10-06

The user confirmed that A/B are two instances of the crystal-plus-one-SiPM module,
primarily for positron-annihilation coincidence measurements. This supersedes the
earlier unresolved physical mapping of A/B. Preserve the existing arrangement
within each module; no extra SiPMs on a crystal are implied. The project generalizes
`g4pec-2nd-gen` for OSS use. Its reference location has been requested: neither
`/g4pec-2nd-gen` nor `/Users/ohayotaro/g4pec-2nd-gen` exists, it is not in the app's
registered projects, and a bounded search of Documents/Desktop/Downloads/backups
did not find it. Do not claim the reference implementation has been inspected.

Next implementation should align the reference detector/source design with explicit
configuration. An idealized simultaneous back-to-back 511 keV photon pair is a
candidate first correlated-source benchmark, distinct from full positron transport.
Keep the existing response parameter values and truth-independent selector. No
physical A/B separation or source position has yet been inferred or implemented.

## Reference repository located and inspected — 2026-10-06

Located `https://github.com/ohayotaro/g4pec-2nd-gen` via GitHub and pinned main at
`ce0aba99ecf993cd29b40197bd834a0fae69d875`. This supersedes the pending-location note.
Read README, DetectorConstruction.cc, PrimaryGeneratorAction.cc, EventAction.cc,
main.cc and macros/run.mac, without copying upstream code or running it. See
`docs/reference-pec.md` for source links and the comparison.

Key distinction: upstream is two frames with four BGO crystals per frame, not two
single-crystal optical modules, and has no explicit SiPM geometry in its detector
construction. It uses F-18 GPS ions, radioactive decay physics, frame-level summed
deposits with response smearing/misidentification, and closest-history prompt/delayed
selection plus delayed subtraction. The new all-pairs selector is not identical to
that policy. Preserve user's permitted SiPM layout and separate ideal pair-source
tests, correlated transport, optical/readout response, and post-analysis prompt/
delayed selection. No parameter tuning or geometry change was performed in this
reference inspection. Public license remains undecided.

## Attached papers and generalized geometry/output boundary — 2026-10-06

Read the user's attached PMB 71 (2026) 165027 (DOI ae9711) and 145004 (DOI ae8356),
especially detector/readout methods, figures 1/3/4, matrix construction and geometry
limitations. `docs/pec-generalization.md` records the findings and the user's latest
instructions. 2 x 2 is a reference design, not an optimum or a fixed framework size.
GDML-variable shape, segmentation, head spacing/orientation and optical boundaries
are central to OSS generalization. Preserve the present SiPM layout/channel budget.

Important clarification: the papers describe two SiPMs per head reading four crystals
via light sharing. Crystal A-D, SiPM a/b and coincidence head A/B are different levels.
The earlier one-crystal/one-SiPM wording is only the minimal development fixture;
do not hard-code it as the final detector architecture or tie added crystals to
added SiPMs. Do not hard-code 16 LORs or carry geometry-specific calibration/matrices
unchanged to another GDML configuration.

The user explicitly agrees to simulation output through SiPM response and analytic
processing in post analysis. Preserve history/waveform outputs, with timing/charge
extraction, calibration, crystal identification/DOI, prompt/delayed processing,
LOR aggregation and reconstruction downstream; truth is for separate evaluation.
The current readout CLI combines shaping/extraction as a convenience but its internal
functions and output boundary remain separable. These documents record the intended
contract, not completed implementation of all analyses or arbitrary GDML support.
No source code, geometry or physical parameters changed in this paper review.

## Portable SiPM response boundary implemented — 2026-10-06

Added `tools/sipm_dataset.py` (schema-1 export/validation) and `tools/analyze_sipm.py`
(portable channel post-analysis entry point). See `docs/sipm-dataset.md` and
`examples/sipm_dataset_export.json`. The registry distinguishes dataset, channel,
detector/head and physical channel path; multiple channels may share a head and
inactive channels are retained. Geometry and response-setting hashes, shared-clock
identity, response/RNG metadata and input/output hashes accompany truth-free pulse
histories. Full original timelines/transport identities must agree across imported
channels; neither GDML nor original transport inputs are needed for replay. Optional
truth annotations are exported separately and can be removed. Export refuses existing
destinations and cleans up only its newly created directory on failure.

Readout propagates dataset/channel/detector/geometry/clock context. Coincidence
selection verifies that context and rejects mixed datasets, geometry, clocks,
detector remapping and portable/legacy mixtures. Existing legacy workflows are
preserved. No cell backend geometry constraints or physical parameter values changed:
physical multi-channel generation and head-level channel aggregation remain future
work, while the common data contract supports those shapes without crystal/LOR counts.

Six new contract tests cover legacy-equivalent replay, relocation plus deletion of
source/truth, inactive/multiple channels per head, alternate geometry identity with
the same schema, clock/hash/registry errors, and post-analysis-to-coincidence binding.
All 14 CTests passed (35.78 s). Retained BGO center 100 keV noisy data exported to
`output/sipm_dataset_verified/` and replayed as `output/sipm_dataset_verified_analysis_*`;
waveforms and 371 singles are byte-identical to the original retained readout.
The export invocation is recorded in `output/sipm_dataset_verified_export.json`.

## Multi-SiPM transport/response connection — 2026-10-07

Added `tools/digitize_channels.py`: snapshots shared transport/geometry/timeline,
validates coverage of all GDML SiPMs, derives detector IDs from sensor DetectorID,
and runs independent stateful cell/noise processing per channel with stable
SHA256-derived seeds keyed by physical placement path. Existing digitize_cells
gains an internal selected-channel mode with global photon/event/active-channel
accounting before filtering; the legacy CLI retains its single-SiPM restriction.
Output includes legacy channel responses and a ready-to-replay portable dataset.
No existing geometry or response parameter values changed.

The dedicated `examples/validation/two_collectors.{gdml,mac}` optical bench directly
illuminates two SiPMs assigned to the same detector0; it is not a proposed PEC layout
or correlated annihilation source. `two_channels.json` retains existing response
values with per-channel paths. Five tests under `multi_channel_response` cover
64 Geant4 photons split 32/32, independent recovery with test-only PDE=1, noise
reproducibility under configuration reordering, inactive channels, input failures,
portable post analysis, and a GDML subtraction-solid crystal variant with unchanged
collector geometry. The latter tests the interface, not U-crystal light sharing/DOI.

All 15 CTest entries were exercised; a legacy arrival-count error-message mismatch
was repaired and both affected cell_response/multi_channel_response tests then
passed. Final five-test retained run: `output/two_channels_verified_final/`.
See `docs/multi-channel-response.md`. Head-level waveform aggregation, DOI and
correlated-source measurement validation remain next work; SiPM sensors still must
be explicitly placed boxes with numeric dimensions.

## Single crystal / two-SiPM head features — 2026-10-07

Added separate research geometry `examples/dual_sipm_head.gdml`: the existing
12x12x10 mm BGO with two 5.8x5.8 mm collectors at X=-3/+3, Z=5.15 mm, both faces
parallel to XY and assigned detector0. Couplings touch the same crystal +Z face.
The standard single-SiPM geometry is unchanged; no slit/wrapping or optimized
physical parameters were introduced. `dual_sipm_channels.json` preserves the
existing cell values.

`tools/head_features.py` replays two portable channels and performs truth-free
all-pairs matching with explicit timing offsets, signed half-open window, pair
budget, multiplicity/quality flags and unmatched outputs. It writes independent
gated charges, sum, (left-right)/(left+right), time difference and mean trigger
time. The example uses existing ADC and 1 us/1504 ns gate settings; the new head
matching half-window of 20 ns is exploratory, not calibrated. Features are not
yet calibrated detector singles or DOI and are not automatically sent to head-head
coincidence selection. See `docs/dual-sipm-head.md` for definitions and limits.

Retained full study `output/dual_sipm_response/`: five known positions, sixteen
100 keV electrons each, full scintillation transport and two response modes on the
same photon data. All 80 events deposit 100 keV, no source-photon acquisition clipping
or ADC rails. Noiseless valid-prompt occupancy is 13/11/12/11/12 out of 16 at
x=-3, center, x=+3, z=-3, z=+3. Conditional mean charge asymmetry is
+0.394/-0.024/-0.411/+0.004/-0.026. This shows lateral response variation, not DOI
resolution. With the existing noise example valid-prompt occupancy falls to
2/0/2/0/2; no tuning was performed and these windows are not truth-classified
detection efficiencies. Reconstruction never consumes the evaluation positions.

Six head-feature unit tests pass, including truth removal, offsets, quality,
ambiguity, missing partners and cleanup. The full 16-test suite passed (36.43 s).
An additional `dual_sipm_pipeline` CTest runs a five-position/two-noise-mode Geant4
smoke study at two events per position; both its direct invocation and registered
CTest passed (2.15 s). All 17 registered tests have passed. It adds no
Monte Carlo performance threshold, only structural/containment/interface checks.
## Head singles to coincidence connection — 2026-10-07

`head_features.py` now also emits singles.csv/singles.json for valid features only.
IDs preserve feature_id and left/right input references; time is the mean of
offset-corrected triggers, charge is the sum of independently gated charges.
The logical head path is distinct from physical placement paths. Calibration
fields explicitly remain null. The manifest carries dataset/geometry/clock,
ordered channel IDs, source feature/config hashes, content hash and mean corrected
window bounds (an enclosing range, not effective live time). All rejected features
and unmatched candidates remain in their original tables.

`coincidences.py` accepts this head stream with strict shared-context checks,
mandatory singles hashes, and rejection of reused channels or mixed head/channel/
legacy inputs. Existing coincidence policies and physical parameters are unchanged.
Seven head tests now include a four-channel/two-head synthetic replay after deleting
source/truth/dataset, signed half-open endpoints, detector/context/hash guards.
All 17 CTests passed in one run (38.59 s). Retained BGO center/noiseless replay in
`output/head_singles_verified/` has 11 head singles and 16 unmatched channel singles;
features.csv is byte-identical to the prior study. This is interface validation,
not annihilation-source efficiency or calibrated DOI. Actual correlated photon
transport through opposing heads remains the next stage.

## Opposed-head gamma transport integration — 2026-10-07

Added examples/opposed_heads.gdml and studies/opposed_heads.py: two unchanged-size
BGO heads centered at Z=+/-15 mm, two external SiPMs per head at Z=+/-20.15 mm,
XY-parallel faces, DetectorID A/B. Standard/research single-head examples unchanged.
GPS emits simultaneous directed 511 keV primaries at origin along +/-Z. This is an
ideal pair integration fixture, not positron/decay/isotropic source simulation.
Four channels share one dataset and periodic 10 us clock; existing PDE/cell/readout/
gate values retained, noise off, no energy selection. Head and coincidence windows
both use uncalibrated 20 ns half-width. No truth enters reconstruction/selection.

Retained output/opposed_heads_verified_v2/: 32 events/64 verified primaries,
arrivals A_left/right 5294/5253, B_left/right 5166/4571; valid head singles A=18,
B=14; coincidence candidates=10, ambiguous=0. These are descriptive counts, not
sensitivity/CTR/DOI estimates. Initial validation used exact floating-point equality
for 511 keV and was corrected to 1e-9 keV tolerance (Geant4 output 510.99999999999989).
Initial failed output is retained as output/opposed_heads_verified/ for diagnostics.
New CTest opposed_heads_pipeline validates eight-event transport through all four
channels, nonempty head-head pairing and member/window consistency. Existing 17
tests passed in the preceding stage; only the added integration test rerun here.
See docs/opposed-heads.md. Next: realistic source/acceptance and separate truth-based
performance evaluation, without changing the measured-response selection boundary.

## User correction: YZ-facing side readout — 2026-10-07

User clarified that in the opposed-head figure SiPM faces must be parallel to YZ,
with two sensors horizontally side by side. Updated opposed_heads.gdml only:
both heads use the +X crystal face, couplings X=6.05 mm, SiPMs X=6.15 mm,
Y=-3/+3 mm, Z=+15 (A)/-15 (B). Couplings and sensors rotate 90 degrees about Y;
local XY cell coordinates and cell parameters remain unchanged. Earlier single-head
examples remain historical separate fixtures. Updated docs/opposed-heads.md.

32-event retained run output/opposed_heads_yz_verified/ completed: arrivals
A=4650/4747, B=4221/4377, singles A=14/B=15, coincidence candidates=6 (ambiguous=0).
These counts replace the old orientation's descriptive example, not a performance
comparison. Added Geant4 placement checks for world centers and YZ sensor normals.
Updated figure output/figures/opposed_heads_yz.png, visually inspected.

## Separate detector performance from software contract checks — 2026-10-07

User clarified that geometry/material-dependent collection efficiency is not an
implementation defect. Removed positive-arrival/positive-coincidence requirements
from opposed_heads_pipeline. Existing known-input coincidence tests already verify
window endpoints, cuts, offsets, multiplicity, truth independence and brute-force
agreement; added one-/two-empty-stream IO cases (8 coincidence unit tests pass).

studies/opposed_heads.py now accepts --geometry and snapshots exact input.gdml.
Its fixture still requires the existing A/B two-channel mapping, explicitly documented;
this is not an arbitrary-geometry auto-configuration claim. New geometry_contract
CTest runs 8 events each for baseline, Z thickness 8 mm, subtraction slit, artificial
optical index/yield changes, and nonemitting materials (zero scintillation yield,
index 1 in crystal/coupling). Same response/readout settings across all variants.
Checks stable dataset/channel mapping/CSV schemas and head context, distinct geometry
hashes, and zero-response propagation without dropping channels. No detector-yield
thresholds. First attempted empty fixture changed collector efficiency; the existing
ideal-boundary guard correctly rejected it. Corrected fixture varies material light
production instead, preserving pre-PDE collector semantics.

Affected tests: coincidences and opposed_heads_pipeline passed, then corrected
geometry_contract passed (11.55 s); 19 tests registered, full suite not rerun this
turn. No response parameter tuning or DOI reconstruction added.

## Configured execution and analysis replay — 2026-10-07

Added tools/run_pipeline.py and examples/pipeline/{single_head,opposed}.json.
User config selects GDML, source macro, run ID, periodic acquisition window/spacing,
existing channel response config, head model configs and optional coincidence policy.
No A/B or left/right identifiers are embedded in the generic runner. Initial model
is explicitly two_sipm_candidate_features_v1; every dataset head/channel must be
covered with matching DetectorID. Third channels, omitted heads and unknown models
are rejected instead of silently selecting subsets. Low-level head_features remains
backwards-compatible; GDML DetectorID is still logical-volume-level.

--dataset replays analysis without accessing GDML, source macro or truth; transport
and response fields may be null in replay configs. Copies exact transport inputs,
original head configs and readout/gate bytes, emits resolved per-head config and
coincidence inputs, and records input/config hashes. Refuses output reuse; failures
after creation retain diagnostics/failure.json without a completed run.json. External
macro/GDML include files are not recursively snapshotted (documented limitation).

Retained full run output/configured_pipeline_verified/: 8 ideal directed pairs,
A=3/B=5 head singles, 2 coincidence candidates, descriptive only. New test checks
single-/two-head full runs, relocation plus deletion of source transport/truth,
byte-identical analysis CSV replay, output protection, unsupported model and missing
head/channel rejection. Targeted configured_pipeline passed (5.06 s).
See docs/configured-pipeline.md for schema, replay instructions and limitations.

Final regression: all 20 registered CTests passed in one run (58.03 s).
