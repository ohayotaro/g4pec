# PEC generalization and output boundary informed by the papers

G4PEC generalizes g4pec-2nd-gen toward open-source release. **A 2 × 2 crystal layout
is not assumed optimal; GDML supports comparisons of shape, segmentation and
placement.** Respect sensor-count constraints rather than adding a SiPM for every
new crystal. Geometry examples and their current orientations are listed in README.

The [portable SiPM response dataset](sipm-dataset.md) and replay without geometry or
truth implement the first version of this boundary; that document lists its scope.

## Papers reviewed

The supplied PDF text and figures were inspected, particularly detector configuration,
readout, system matrices and applicability limits.

1. Ohashi et al., *Machine-learning-based source localization for an intraoperative forceps-type
   positron emission counter*, Phys. Med. Biol. 71 (2026) 165027.
   [DOI](https://doi.org/10.1088/1361-6560/ae9711)
   - Section 2.1, Figure 1: two heads, each with 2 × 2 BGO crystals, separated by 6 mm.
   - Section 2.7, Figures 3–4: two SiPMs connect to the ends of each head's optical
     path; `(a-b)/(a+b)` distinguishes four crystals. Sensor and crystal counts are
     not one-to-one.
   - Section 2.1 and Discussion: Monte Carlo approximates response with resolution
     and misidentification probabilities rather than explicit optical transport
     and SiPM response. Models trained at fixed spacing/pose have limited applicability.
2. Ohashi et al., *Feasibility study of image reconstruction for a forceps-type positron emission
   counter: a simulation-based algorithm comparison*, Phys. Med. Biol. 71 (2026) 145004.
   [DOI](https://doi.org/10.1088/1361-6560/ae8356)
   - Sections 2.1–2.3, Figure 1: the same 2 × 2 layout defines 16 LORs and a matrix
     relating LORs to source voxels.
   - Section 2.4 compares seven reconstruction algorithms for those conditions.
     Sixteen LORs and the chosen voxel count are study parameters, not fixed
     dimensions for a general simulator.

The papers' crystal labels A–D and SiPM labels a/b are distinct from coincidence
head labels A/B. Simplified crystal/SiPM development modules do not prescribe final
crystal or sensor counts. Early fixtures used XY-facing SiPMs; the subsequent
[opposed-head fixture](opposed-heads.md) uses the user-specified YZ-facing layout.

## Simulation and post-analysis responsibilities

| Layer | Responsibilities and saved data |
| --- | --- |
| Geant4 transport | Transport radiation and optical photons through GDML materials, crystals and boundaries; save SiPM arrivals and separate interaction/annihilation truth where implemented |
| SiPM response | Apply PDE, recovery and noise; save per-channel avalanches, charge and common-clock time; retain waveform outputs from configured electronics/ADC models |
| Post analysis | Extract times, charges and singles; perform calibration, crystal identification, DOI, prompt/delayed selection, LOR aggregation, random correction, sensitivity/system matrices, CoG and image reconstruction as models are implemented |
| Evaluation | Compare reconstruction with separate truth; never use truth crystal/event IDs for measurement-based selection |

This table defines responsibilities, not a claim that annihilation-specific records,
calibration, DOI, delayed correction or matrix/image reconstruction all exist.
readout.py currently combines waveform generation and extraction in one CLI, but
internally separates shape and extraction functions. That convenience does not move
analysis into Geant4 or remove the history/waveform replay boundary.

Unconditionally adding the papers' fixed resolution and misidentification probabilities
to explicit optical/SiPM response could double-count effects. Their simplified response
is a possible independent comparison model, not a mandatory additional correction.

## Contract under GDML changes

- Keep detector/head, crystal and channel identities separate; no one-to-one crystal/SiPM assumption.
- Describe crystal count, shape, segmentation, head spacing/pose and optical boundaries
  in GDML. Do not embed 2 × 2, four crystals, 16 LORs or fixed adjacency in generic code.
- Define identifiable positions/crystals through geometry-specific analysis settings
  and calibration. A crystal existing in GDML does not make it experimentally identifiable.
- Derive LOR lists and matrix sizes from identifiable measurement elements and allowed
  pairs, not a fixed 16-element vector interface.
- Bind analysis models, calibration and system matrices to input geometry and response
  identities/hashes. Do not silently reuse them after geometry or spacing changes.
- Preserve physical sensor-count constraints; adding sensors is not a substitute for
  comparing optical geometries.

Geant4's GDML capabilities exceed those of the Python response validator. The legacy
CLI requires a single explicitly placed box sensor with numeric dimensions; the
multi-channel path supports several such sensors. Unsupported shapes/mappings must
fail explicitly; arbitrary GDML is not claimed to work through every stage.

Source models, readout mappings and post analysis are validated independently before
connection. The generalization review itself did not tune physical parameters.
