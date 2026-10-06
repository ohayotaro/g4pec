# Transport identity, geometry and truth (schema 1)

The minimum example remains one crystal and one SiPM channel. These exports prepare
for future DOI and coincidence analysis; neither algorithm nor a continuous source
clock is implemented. Truth must not be used as an implicit reconstruction input.

## Identity and compatibility

Each application invocation receives a random 128-bit hexadecimal `dataset_id`
from system entropy, independently of Geant4's physics RNG. Each `/run/beamOn`
receives its Geant4 `run_id`. Events are keyed by `(dataset_id, run_id, event_id)`;
tracks add `track_id`, and crystal steps add `step_number`. IDs are provenance,
not an acquisition clock or a coincidence criterion. Rerunning identical physics
inputs produces a new dataset identity; physics reproducibility checks should
compare physical values, not dataset IDs.

Existing photon/event columns keep their names and ordering. New columns are
appended, so named-column readers and the ideal digitizer continue to work. Each
run has a `_manifest.json` declaring schema version, dataset/run identity, Geant4
version number, time basis and geometry/truth conventions. `_placements.csv` is
scoped to this manifest. The same-prefix geometry, macro and RNG snapshots remain
the run's transport inputs; nested input dependencies are still not archived.

The cell digitizer checks consistent dataset/run identity when supplied and records
it as `transport_identity` in its response manifest. Legacy files remain accepted
with a null identity. It rejects mixed identified/legacy rows and mixed runs;
it does not concatenate runs into an acquisition. A zero-event legacy-compatible
input cannot establish an identity from rows. Response input hashes continue to
identify the exact input files. The older ideal digitizer retains its existing
interface and does not validate the added transport identities.

## Geometry metadata

`_placements.csv` contains every explicit placement's full path, logical-volume
name, role, optional `detector_id`, solid type, box full lengths where applicable,
and a local-to-world transform. For a column coordinate vector in mm:

```text
world = R * local + (tx_mm, ty_mm, tz_mm)
```

`rxx` through `rzz` are the row-major rotation matrix. Transforms are composed
through the placement hierarchy. The placement path identifies the crystal or
channel within this geometry; changing placements may change those IDs. Non-box
solids have empty box dimensions; the GDML snapshot defines their actual shape.

Logical-volume GDML auxiliary tags declare roles/grouping:

```xml
<auxiliary auxtype="Truth" auxvalue="Crystal"/>
<auxiliary auxtype="DetectorID" auxvalue="detector0"/>
```

`Readout=SiPM` continues to identify sensor roles. The example crystal and sensor
share `DetectorID=detector0`; grouping is explicit metadata, not inferred adjacency.
Other fixtures need not tag a crystal and then produce an empty step table. No
DOI axis/reference face is inferred from a coordinate named Z. That definition
belongs to the future detector/DOI analysis configuration.

## Tracks and crystal steps

`_tracks.csv` records every transported track at its first tracking entry, including
optical tracks: event/track/parent IDs, PDG code, particle and creator-process names,
initial world position, event-relative time, kinetic energy in keV and direction.
A suspended/resumed track is recorded only once. `parent_id=0` identifies transported
primaries; their rows retain primary kinematics. Optical PDG values alone are not
unique particle identifiers, so use the particle name as well. Parent linkage
allows detected photons to be traced through their ancestry. This is transported
track truth, not a separate record of untransported source vertices/particles.

`_steps.csv` records **all non-optical steps whose pre-step volume is tagged
`Truth=Crystal`**, including transport-only steps and zero energy deposits. Columns
include the crystal path, event/track/parent/step IDs, process defining the step,
pre/post times, total deposited energy in keV, and both endpoints in world and
crystal-local coordinates. Both local endpoints use the pre-step crystal frame,
even when the step exits the crystal.

Deposited energy belongs to the entire step. An endpoint is not an exact point
location of continuous energy loss, and the process defining a step is not a
complete decomposition of all processes contributing to its deposit. No photon
energy is re-counted as crystal deposition. First gamma interactions and
energy-weighted deposit-depth labels must be defined explicitly by future analysis.

`_events.csv` adds `crystal_edep_keV` and `n_crystal_steps`, including zeros, plus
dataset/run IDs. `_photons.csv` adds parent ID and dataset/run IDs. Track and step
records are separate from readout; the response simulation does not consume truth.
Recording all optical track births increases storage significantly; exports stream
to disk and the test fixtures remain small. Output paths, including the new files,
are checked for existing files before the run writes them. A failed/interrupted
run may leave partial files and must not be treated as a completed dataset.

## Validation

The pipeline test checks track-parent and photon joins, unique track identities,
per-event step/deposit accounting, primary gamma energy, and the 511 keV event
energy upper bound for this source. Crystal-local endpoints round-trip through
metadata transforms for both the original and a rotated/translated detector.
Direct optical events have no non-optical crystal steps. The existing optical
benchmarks and both response backends continue to exercise compatibility.

All times remain Geant4 event-relative ns, including any configured primary time.
No source-event offset, shared acquisition clock, cross-event cell state, DOI
estimate or coincidence label is generated by Geant4. The separate
[acquisition response](acquisition.md) now adds explicit offsets and cross-event
cell state; reconstruction remains future work. See [the analysis contract](analysis-contract.md)
for the remaining interface work.

## Known-source truth benchmarks

`truth_benchmarks` adds seven deterministic fixtures, retaining the one-crystal,
one-channel geometry:

- 10 keV electrons at local `(0.6, -0.4, z)` mm for z = -3, 0, +3, each with
  12 events; repeat all three after a 90-degree rotation and translation.
- 64 events with a 511 keV gamma starting inside the crystal at `(0.6, -0.4, 0)` mm,
  exercising both full containment and energy escape.

Every source starts at 7 ns. Tests compare the recorded primary vertex, energy,
start time and first crystal-step position with the independent source definition.
For rotated cases the known transform is `(x,y,z) -> (7-z, -3+y, 2+x)` mm;
expected coordinates are not derived from the exported metadata. Position tolerance
is 1e-8 mm. These are known birth-depth checks, not reconstructed DOI estimates or
claims that all subsequent deposition occurs exactly at that depth.

Four columns appended to `_steps.csv` support an energy ledger:
`pre_kinetic_energy_keV`, `post_kinetic_energy_keV`, `entering_crystal`, and
`leaving_crystal`. Entry is a pre-step geometry-boundary status; exit is a post-step
geometry/world-boundary status. Both flags refer to the pre-step crystal volume.
For these internal-source, electromagnetic fixtures:

```text
initial primary kinetic energy + incoming non-optical kinetic energy
  - outgoing non-optical kinetic energy - crystal deposited energy = 0
```

The acceptance tolerance is 1e-5 keV per event. Boundary flux includes secondary
particles and would include re-entry. These fixed-seed fixtures recorded no
re-entry steps, so re-entry behavior is not independently exercised by this suite. Secondary birth energies are internal transfers and must
not be counted as additional source energy. Optical photon energies are not added
again: this tests Geant4's non-optical deposition bookkeeping, not an independent
microscopic optical-energy conservation model. This kinetic-energy ledger is scoped
to these fixtures, not to reactions involving rest-mass conversion, nuclear energy
release, or delayed/stopped tracks in a future acquisition model.

For every detected optical photon, the benchmark verifies a same-event parent
chain ending at the known primary, absence of cycles, creator process, photon
energy and nondecreasing arrival time. Scintillation births must lie on a depositing
parent-step segment; Cherenkov births must lie on a parent-step segment but need
not have positive local energy deposition. This checks spatial/ancestry consistency,
not a stored one-to-one emission-step ID or an emission-yield calibration.

To retain all generated macros, geometry snapshots, raw outputs, logs and report:

```sh
python3 tests/check_truth_benchmarks.py build/g4pec . \
  --output-dir output/truth_benchmarks_new
```

The output directory must be new. The verified local report is
`output/truth_benchmarks_verified/report.json` (ignored by Git). On the tested
Geant4 11.4 setup, all 72 electron events deposited 10 keV; the gamma fixture had
16 contained and 48 escape events, with a maximum energy residual of
1.71e-13 keV. Ancestry was verified for 14,226 arrivals, including 43 Cherenkov
photons. These observed counts are recorded results, not hard-coded acceptance
criteria or expected detector performance.
