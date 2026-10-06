# Opposed heads: optical transport through coincidence analysis

`examples/opposed_heads.gdml` is an integration fixture with two 12 × 12 × 10 mm
BGO crystals centered at (0,0,+15) and (0,0,-15) mm. The inner faces are 20 mm apart.
Each head has two SiPMs, four in total. Sensor centers are X=+6.15 mm, Y=±3 mm,
Z=+15 mm for A and −15 mm for B. Faces are parallel to YZ, arranged horizontally
along Y. Both heads use the +X crystal face with a 0.1 mm coupling layer centered
at X=+6.05 mm. Couplings and sensors rotate 90 degrees about Y in GDML; cell
processing still uses sensor-local XY coordinates. Materials, crystal/sensor sizes,
response, readout and gate settings match the original single-head example.

```sh
# Source your Geant4 installation's bin/geant4.sh if needed.
python3 studies/opposed_heads.py build/g4pec \
  --output-dir output/opposed_heads_new --events 32
```

Two simultaneous 511 keV gamma primaries originate at the origin along ±Z. GPS
multiple sources generate both in one event. Primary truth records verify count,
energy, position, direction and time. This ideal back-to-back pair fixture does
not model radioactive decay, positron range, acollinearity or isotropic acceptance.

Geant4 computes gamma interactions and scintillation-light transport, including
transmission and scattered-photon escape; full absorption or detection in both
heads is not forced. Four SiPM responses share a periodic 10 µs acquisition clock.
Each head's two channels produce singles, followed by A/B coincidence selection.
Both within-head and between-head half-windows use the illustrative 20 ns setting.
No parameters are tuned; this integration fixture has no noise or energy selection.

`response/dataset/` contains portable responses, `A/` and `B/` contain head features
and singles, `pairs_coincidences.csv` contains pairs, and `coincidence.json` contains
replayable settings. Primary and crystal-step truth is used only for source checks
and descriptive summaries, never single selection or pair matching. Time-selected
pairs are not automatically classified as true coincidences. Results are integration
checks, not sensitivity, CTR or DOI-resolution estimates.

The retained 32-event run in `output/opposed_heads_yz_verified/` verified 64 primary
gammas. Arrivals were A left/right 4650/4747 and B left/right 4221/4377. It produced
14 A singles, 15 B singles and 6 coincidence candidates, with no ambiguous pairs.
These are descriptive results for the stated conditions and fixed random seeds.

`opposed_heads_pipeline` runs eight events through transport and coincidence
selection, checking four registered channels, head assignments, window conditions,
placement transforms and references to input singles.

## Geometry-independent interface checks

Use `--geometry path/to/variant.gdml` for an alternate GDML; the exact input is
saved as `input.gdml`. This study script retains the A/B two-channel naming and
assignment convention. Other channel configurations use `digitize_channels.py`
settings or the [configured runner](configured-pipeline.md).

`geometry_contract` runs five conditions with the same source and response/analysis
settings: baseline, changed crystal thickness, a subtraction-solid slit, artificial
optical-property changes, and nonemitting test properties. The material variants
are not calibrated models of other real scintillators. Checks cover dataset format,
channel IDs/assignments/paths, feature/single/coincidence CSV columns, geometry and
clock references. Neither identical nor positive detection counts are required.
Zero response retains channel metadata and produces valid empty analysis outputs.
The SiPM collector remains an ideal arrival-recording boundary (efficiency 1),
separate from PDE.

Synthetic-input tests verify window endpoints, offsets, charge cuts, quality,
multiplicity, truth independence and empty inputs. Physical detection yields from
Geant4 are not pipeline acceptance criteria.
