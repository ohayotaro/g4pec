# DOI and coincidence analysis contract

DOI (depth of interaction) reconstruction and coincidence processing are required
downstream capabilities. Transport, response and acquisition interfaces must support
them from the outset. This document defines the implementation target; it does not
claim that the records or algorithms listed below already exist.

The first metadata/truth slice is implemented as documented in
[transport truth](transport-truth.md). Explicit single-run acquisition timing and continuous cell state are also
implemented in [acquisition mode](acquisition.md). [Coincidence selection](coincidences.md)
now implements configurable time/charge/quality cuts and all-pairs multiplicity;
DOI reconstruction and detector-level channel aggregation remain future work.

## Ownership

The latest scope is recorded in [PEC generalization](pec-generalization.md):
GDML-variable crystal geometry/segmentation/layout is a primary objective; 2 x 2
crystals and 16 LORs are reference cases, never assumed optimal or fixed interface
dimensions. Crystal count and SiPM count are independent. The current single-crystal/
single-SiPM fixture does not prescribe the final head architecture. Preserve the
present SiPM arrangement and limited channel budget while permitting geometry studies.
Simulation outputs extend through SiPM response (including modeled waveforms);
feature extraction, calibration, crystal identification/DOI, coincidences, correction
and reconstruction are replayable post analysis. The linked document distinguishes
this intended contract from currently implemented features and GDML limitations.

The project's purpose is to generalize `g4pec-2nd-gen` into an open-source PEC
simulation and post-analysis framework. The user confirmed the physical A/B
development arrangement: two copies of the current module, each with one crystal
and one SiPM, for positron annihilation coincidence measurement. This is a minimal
fixture, not a restriction on final crystal segmentation. The present geometry is the
unit to preserve, not a reason to add a second SiPM to one crystal. Physical A/B
positions, separation and source placement must be taken from the reference design
or explicit configuration, not inferred from synthetic coincidence test inputs.

An initial correlated-source implementation can use a simultaneous, back-to-back
511 keV photon pair at a common point. This is an idealized annihilation test source;
positron transport, source encapsulation and deviations from that idealization must
be separate declared model choices. Each pair shares a transport event for truth
evaluation, while the coincidence selector continues to use reconstructed timing
and configured detector relationships rather than event identity.

PEC packaging constrains the SiPM count. Preserve the current SiPM arrangement;
do not require additional SiPMs for implementing coincidence selection or assume
multi-channel charge sharing as the DOI method. In the current GDML the sensor
is an unrotated 5.8 x 5.8 x 0.1 mm box on the +Z face, so its entrance plane is
parallel to world XY (normal along Z), not XZ. Any future physical geometry change
must follow the user's detector constraints rather than the generic schema's
ability to represent multiple channels.

- Geant4 transports radiation and optical photons. It exports pre-PDE arrivals
  and separate simulation truth for validation.
- The response layer applies PDE once, cell dynamics, noise and electronics. It
  produces channel readout, with explicit acquisition timing and detector state.
- Post analysis builds singles from readout, reconstructs energy, time, position
  and DOI, and forms coincidences using reconstructed measurements and configured
  selection rules. It can replay these choices without rerunning transport.

Truth is optional evaluation input, never an implicit reconstruction feature or
coincidence selection criterion. In particular, matching Geant4 event IDs is not
a coincidence algorithm, and sensor photon-arrival positions are not measured
crystal interaction positions.

## Required data interfaces

The first geometry-independent response boundary is implemented as the
[portable SiPM dataset](sipm-dataset.md): distinct dataset/channel/detector IDs,
shared clock, geometry/settings hashes, and history free of truth annotations.
Portable post analysis preserves existing readout outputs and propagates this
context to coincidence selection. The registry supports multiple channels per head;
[multi-channel response generation](multi-channel-response.md) now connects Geant4
arrivals to it. [Two-SiPM head features](dual-sipm-head.md) now provide candidate
pairing, charge sum/asymmetry and time difference with explicit ambiguity/unmatched
outputs. Valid features are exported as uncalibrated head singles and can feed
coincidence selection with shared dataset/geometry/clock checks. Energy/time
calibration and DOI reconstruction remain future work.

| Interface | Required information | Current status |
| --- | --- | --- |
| Dataset identity | Versioned schema; dataset/run IDs and input/configuration provenance; event/track keys scoped to their run | Schema-1 run manifests, dataset/run IDs and scoped row keys exist; input snapshots and response hashes are retained |
| Geometry metadata | Stable detector, crystal and channel IDs; channel-to-detector mapping; local-to-world transforms; crystal dimensions and declared DOI axis, origin and sign | Resolved placement roles, explicit detector grouping, box sizes and local-to-world transforms are exported; DOI axis/origin remain future analysis configuration |
| Transport arrivals | Run/event/track identity, channel, event-relative time, photon energy, sensor-local position and direction | Current photon CSV provides these, including in-row run/dataset keys and parent IDs |
| Interaction truth | Source-primary identity and kinematics; track/parent linkage; crystal ID, process, interaction position/time and deposited energy; local and world coordinates or reproducible transforms | Transported track births and non-optical crystal steps are exported; separate untransported source-primary records remain future work |
| Acquisition timeline | Source-event time offsets, shared clock origin and units, acquisition windows and boundary rules; source and RNG provenance | Explicit event-origin offsets, a single half-open window, provenance and stateful response exist; stochastic/correlated source generation remains future work |
| Readout | Stable readout ID, channel, shared-clock time, charge and/or waveform with sample origin/interval; threshold and timing definitions, configuration provenance | Acquisition waveform/ADC sampling and channel candidates with charge/time exist; detailed electronics remain future work |
| Reconstructed singles | Single ID, detector/crystal ID, reconstructed energy/time/position/DOI, validity/quality flags and links to contributing readouts | ADC-derived channel candidates with charge/time and quality flags exist; calibrated energy, crystal assignment, position and DOI remain future work |
| Coincidences | Coincidence ID, member single IDs, time difference, selection configuration and ambiguity/multiplicity handling | All-pairs selection from acquisition singles exists, with explicit clock offsets, detector pairs, half-open time windows, charge/quality cuts, scoped member keys and multiplicity flags; correlated transport-source validation remains future work |

Persist versioned joins between these records. Do not assume event or track IDs
are unique across runs. Preserve per-channel measurements before detector-level
aggregation so DOI algorithms can use charge sharing and timing where the detector
configuration makes them observable. User-supplied calibration/model versions must
accompany reconstructed outputs.

## DOI definition and truth validation

Define depth in each crystal's local frame with an explicit reference face and
axis, rather than interpreting world Z or SiPM-local Z as DOI. Rotation and
translation of a detector must preserve the local depth definition.

A gamma can interact at several positions. Retain interaction-level truth so an
analysis can explicitly select a first-interaction depth, energy-weighted deposit
depth or another documented target. These labels are distinct; do not silently
replace one with another. Reconstructed DOI must come from the simulated readout,
with truth used separately for residuals and performance evaluation. The current
single integrated channel does not establish DOI observability. Evaluate the
information available from the permitted geometry/readout before choosing a DOI
method; do not add sensor placements merely to make a reconstruction method work.

## Coincidence timing and state

Use a common acquisition clock: arrival time equals a source-event time offset
plus its Geant4 event-relative time. Adding offsets must not double-count any
primary time already present in the event. A declared source process supplies
correlated primaries and inter-event times; independent single-gamma runs alone
do not constitute a correlated coincidence source.

Interleave arrivals on this timeline before continuous response simulation. Cell
state and delayed noise must survive event boundaries when modeling acquisition;
the existing fully charged, independent-event mode remains an explicit benchmark
mode. Adding timestamps after independently resetting each event cannot reproduce
pileup, dead-time losses or delayed noise across events. Specify initialization,
prehistory, window clipping and delayed activity at window boundaries.

Coincidence selection uses reconstructed singles, detector relationships, a stated
time-window convention, and configurable energy/quality criteria. Specify whether
multiple matches are retained or resolved and how duplicate pairs are prevented.
Simulation ancestry can subsequently label true, scattered and random categories
under a documented definition; it must not remove random coincidences during
selection. Do not assign independent noise a fabricated source-event ancestry.

## Implementation order and acceptance checks

1. Introduce versioned dataset/geometry metadata and separate interaction truth,
   retaining existing arrival and ideal/cell response compatibility. Verify joins,
   energy-deposit accounting and local/world transforms, including rotated crystals.
2. Add the source/acquisition timeline and stateful response boundary before
   acquisition noise. Test overlapping source events, empty windows, boundary
   arrivals and cross-event recovery with deterministic fixtures.
3. Add noise, waveforms and readout extraction, preserving per-channel outputs and
   configuration provenance. Validate each added physical/statistical model.
4. Add pluggable DOI and singles/coincidence analysis with suitable detector/source
   examples. Test synthetic known-depth cases, clock offsets, time-window endpoints,
   multiple candidates, and pairs from different truth events. Removing truth
   inputs must not change reconstruction or coincidence selection.

Real-device parameter fitting remains the user's responsibility. Analytical,
synthetic and statistical validation of these simulation and analysis interfaces
remains part of implementation.
