# Reference PEC implementation and generalization

The two supplied papers and division of responsibilities are summarized in the
[PEC generalization design](pec-generalization.md). The 2 × 2 layout is one
reproduction condition, not a limit on GDML geometry comparisons.

The reference is [ohayotaro/g4pec-2nd-gen](https://github.com/ohayotaro/g4pec-2nd-gen).
On 2026-10-06, main was inspected at pinned commit
`ce0aba99ecf993cd29b40197bd834a0fae69d875`: README, detector construction, primary
generation, EventAction, main and macros. The reference was not built or run during
this review, and its source was not copied into this repository.

## Findings from source inspection

| Topic | Reference | G4PEC implementation or intended treatment |
| --- | --- | --- |
| Geometry | Two frames, four BGO crystals each; cylindrical sectors and spherical parts; frames on ±Y | GDML fixtures use box crystals; original geometry is not yet reproduced |
| Readout | Aggregate deposits by frame, select the maximum-deposit crystal, smear energy/time and apply crystal misidentification | Explicit optical transport → SiPM → ADC → candidates, respecting sensor-count/placement constraints |
| Source | F-18 ions in a macro with radioactive-decay physics registered | Distinguish ideal correlated-photon fixtures from sources including positron transport |
| Acquisition time | EventAction accumulates random intervals from current activity and updates activity with elapsed time | Separate source process and acquisition timeline; periodic examples are not physical decay times |
| Coincidences | Nearest candidate in the other frame for prompt and delayed histories | Post analysis currently retains all prompt-window pairs; the policy differs explicitly |
| Random correction | Subtract delayed-window counts from projections | Future implementation must specify delayed selection, acquisition-edge exposure and window normalization |

Geometry findings refer to
[DetectorConstruction.cc](https://github.com/ohayotaro/g4pec-2nd-gen/blob/ce0aba99ecf993cd29b40197bd834a0fae69d875/src/DetectorConstruction.cc);
source findings to
[run.mac](https://github.com/ohayotaro/g4pec-2nd-gen/blob/ce0aba99ecf993cd29b40197bd834a0fae69d875/macros/run.mac)
and [main.cc](https://github.com/ohayotaro/g4pec-2nd-gen/blob/ce0aba99ecf993cd29b40197bd834a0fae69d875/main.cc);
response, clock and coincidence findings to
[EventAction.cc](https://github.com/ohayotaro/g4pec-2nd-gen/blob/ce0aba99ecf993cd29b40197bd834a0fae69d875/src/EventAction.cc).

The reference detector construction has no explicit SiPM placements. Sensor counts
or orientations must not be inferred from its crystal placements. User-approved
simplified A/B modules are development fixtures, not evidence that the original
frames each contained one crystal. Early fixtures used XY-facing readout; the later
opposed-head fixture uses YZ-facing readout as documented in [its geometry guide](opposed-heads.md).

## Distinctions when carrying the design forward

- The reference compares `abs(dt) <= coincidenceWindow`; current selection uses
  `-half_window <= dt < half_window`. Names alone do not establish identical full
  widths or endpoints. Compatibility comparisons must state conversions explicitly.
- Nearest-neighbor and all-pairs selection differ under multiplicity. If compatibility
  is required, expose the policy rather than silently replacing current behavior.
- Truth-derived crystal positions, energies and times in the reference must not be
  confused with reconstructed measurements. Its simplified response is a separate
  comparison model when used.
- At the user's request, current work does not tune parameters. Validate physics,
  data boundaries and selection conventions independently before model comparisons.

Open-source generalization places device-specific geometry, source, response and
selection conditions in external settings; the original PEC becomes one reproduction
example. A release license has not been selected. The pinned reference file listing
contained no LICENSE file.
