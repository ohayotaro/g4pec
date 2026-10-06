# G4PEC: configurable optical transport and SiPM analysis

G4PEC simulates scintillation detectors defined in GDML and exports SiPM responses
for replayable post analysis. Its main application is positron-annihilation
coincidence measurement with a limited number of SiPM channels per detector head.
Crystal shape, segmentation, sensor placement and head arrangement are supplied
through GDML; a 2 × 2 crystal array is not a framework requirement.

The project generalizes concepts from
[ohayotaro/g4pec-2nd-gen](https://github.com/ohayotaro/g4pec-2nd-gen).
See the [reference comparison](docs/reference-pec.md) and
[design boundary](docs/pec-generalization.md). No predecessor or G4SiPM source code
is vendored here.

This is an **engineering prototype with illustrative parameters**, not a calibrated
detector model. Software correctness and model checks are distinct from collection
efficiency, DOI resolution and agreement with a particular instrument.

## Processing boundary

```text
GDML geometry + source macro
    → Geant4: particle interactions and scintillation/optical transport
    → pre-PDE photon arrivals at each SiPM
    → Python: cell response, optional noise, shared acquisition clock
    → portable SiPM response dataset
    → post analysis: waveforms, channel candidates, head singles, coincidences
```

Geant4's collector boundary records arrivals before PDE. The Python response
applies PDE once and maintains independent state for each SiPM. The portable
response dataset is the common interface: post analysis does not need GDML,
transport tracks or truth event IDs. Simulation truth is exported separately for
evaluation, never used to select measured candidates or coincidences.

| Stage | Current implementation |
| --- | --- |
| Transport | External GDML, GPS source macros, optical arrivals, placement metadata and separate transport truth |
| SiPM response | Multiple channels, finite-cell recovery/saturation, optional dark counts, crosstalk and afterpulses |
| Readout | Shaping, sampled ADC, threshold extraction and configurable fixed integration gates |
| Head analysis | Explicit two-SiPM model: charge sum/asymmetry, time difference, mean time, quality and ambiguity flags |
| Coincidences | Truth-independent all-pairs time matching between configured heads, with charge/quality cuts and multiplicity flags |
| Position/DOI | Not yet implemented; response variation alone does not establish unique position identification |

Energy and timing calibration, crystal identification and image reconstruction are
also future analysis work. Model definitions and units are described in the
[analysis contract](docs/analysis-contract.md).

## Build

Requires Geant4 11.3+ built with GDML support and installed physics datasets,
CMake 3.16+, a C++17 compiler and Python 3.9+. Core Python processing uses the
standard library; optional plotting tools require Matplotlib. Development has
been tested with Geant4 11.4.0.

```sh
# Source your Geant4 installation's bin/geant4.sh if needed.
cmake -S . -B build -DGeant4_DIR=/path/to/geant4/lib/cmake/Geant4
cmake --build build -j 4
ctest --test-dir build --output-on-failure
```

## Run and replay

Run the configured two-head example from the repository root:

```sh
python3 tools/run_pipeline.py examples/pipeline/opposed.json \
  output/opposed --executable build/g4pec
```

This example emits eight ideal simultaneous 511 keV gamma pairs from the origin
along +Z/−Z. It runs transport, four SiPM responses, two head analyses and
coincidence selection. It does not simulate radioactive decay, positron range,
acollinearity or isotropic source acceptance.

Replay analysis from the saved SiPM responses, without rerunning transport:

```sh
python3 tools/run_pipeline.py examples/pipeline/opposed.json \
  output/opposed_replay --dataset output/opposed/response/dataset
```

A one-head/two-SiPM electron example uses the same execution path:

```sh
python3 tools/run_pipeline.py examples/pipeline/single_head.json \
  output/single_head --executable build/g4pec
```

Use a new output directory for every execution. Inputs and settings are saved with
hashes. `run.json` with `complete: true` marks completion; failures retain
`failure.json` and available diagnostics. Nested macro/GDML dependencies are not
copied automatically.

| Output | Content |
| --- | --- |
| `input.gdml`, `source.mac`, `channels.json`, `timeline.json` | Transport, response and acquisition inputs |
| `transport_runN_*` | Photon arrivals, event accounting, geometry/placement metadata and separate truth |
| `response/dataset/` | Portable channel registry, common clock and SiPM pulse histories; optional separate truth |
| `analysis/head_0000/result/` | Channel waveforms/candidates, head features, unmatched candidates and head singles |
| `analysis/pairs_coincidences.csv` | Selected head pairs and multiplicity flags, when enabled |
| `analysis/coincidence.json`, `run.json` | Resolved coincidence settings and execution summary |

The [configured pipeline guide](docs/configured-pipeline.md) explains all fields,
relative paths, model selection, complete channel coverage and relocating replay
inputs. The [settings guide](docs/user-settings.md) covers acquisition/integration
windows, thresholds, holdoff, ADC and SiPM parameters.

## Geometry, heads and SiPM identities

| Example GDML | Layout |
| --- | --- |
| `examples/single_detector.gdml` | Baseline BGO crystal with one XY-facing SiPM |
| `examples/dual_sipm_head.gdml` | One BGO crystal with two XY-facing SiPMs on its +Z face |
| `examples/opposed_heads.gdml` | Two BGO crystals at Z=±15 mm, each with two YZ-facing SiPMs on its +X side, arranged along Y |

These are separate fixtures, not required detector designs. The opposed-head
example has a 20 mm gap between the crystal faces. Each crystal is 12 × 12 × 10 mm;
each SiPM footprint is 5.8 × 5.8 mm. Current examples have no reflective wrapping.
See the [opposed-head geometry](docs/opposed-heads.md) and
[single-head study](docs/dual-sipm-head.md).

Tag each sensor logical volume in GDML:

```xml
<auxiliary auxtype="Readout" auxvalue="SiPM"/>
<auxiliary auxtype="DetectorID" auxvalue="A"/>
```

`DetectorID` identifies the head. A response configuration maps a logical
`channel_id`, such as `A_left`, to a unique physical placement path, such as
`/World_PV[0]/A_sipm_left[0]`. Names and copy numbers form the placement path;
copy numbers alone do not define a head or channel ID. DetectorID currently belongs
to the **logical volume**, so sensor logical volumes must be distinct when their
head assignments differ.

Transport and the portable dataset allow multiple SiPMs per head. The configured
runner currently supports only the explicit **two-SiPM head model** and rejects
missing channels or heads with a different channel count. Generalizing the data
interface does not imply that every head reconstruction model is implemented.

Sensor placement and rotation come from GDML. The response backend currently
requires explicitly placed box sensors with numeric dimensions and a cell grid
covering their local XY face. Nested/rotated placements are supported; replicas
and parameterised placements are rejected. Crystal shapes can differ from boxes.

The coupling-to-sensor entrance is an ordered border surface with ideal
`dielectric_metal` collection (`REFLECTIVITY=0`, `EFFICIENCY=1`); the sensor skin
has `EFFICIENCY=0`. This defines pre-PDE arrival collection, not device detection
efficiency. Move/rotate the coupling and sensor together to preserve contact.
See the [optical model contract](docs/optical-model.md) for required surfaces,
placement constraints and optical assumptions.

## Verification and scope

The current suite contains **20 CTest entries**. It covers optical interfaces and
transport against analytical expectations, local coordinates, source/energy
accounting, SiPM limiting cases, waveform/gate behavior, coincidence boundaries,
truth independence, geometry variants and portable replay.

Detector-dependent collection yields are not pass/fail criteria for pipeline
integration. Dimension, slit and optical-property variants must preserve the data
contract; zero-response inputs must keep channel identities and produce valid
empty analysis outputs. Coincidence logic is checked with known synthetic inputs,
including timing offsets, window endpoints, quality cuts, multiplicity and empty
streams. Physical benchmark tests use their own stated analytical/statistical
acceptance criteria.

Useful references:

- [Optical benchmarks](docs/optical-benchmarks.md) and [transport truth](docs/transport-truth.md)
- [Cell response](docs/cell-response.md), [noise](docs/noise-response.md), [acquisition clock](docs/acquisition.md) and [waveform/readout](docs/waveform-readout.md)
- [Portable SiPM dataset](docs/sipm-dataset.md) and [multi-channel generation](docs/multi-channel-response.md)
- [Head features](docs/dual-sipm-head.md), [coincidence selection](docs/coincidences.md) and [configured execution](docs/configured-pipeline.md)
- [BGO response study](docs/bgo-response-study.md), [window scan](docs/bgo-window-scan.md) and [cause separation](docs/bgo-cause-separation.md)

The Geant4 application is serial; current processing targets small studies and
keeps substantial data in memory. Weighted/bundled optical photons, detailed
sensor packaging, timing jitter and calibrated device response are not supported.
The example acquisition clock is periodic, not a radioactive activity model.
Device-specific fitting and validation against measurements are user work;
passing software tests does not establish real-detector performance.

## References and licensing status

The independent Python cell backend is the production response path.
[G4SiPM](https://github.com/ntim/g4sipm) is an optional comparison reference;
its [pinned-source evaluation](docs/g4sipm-evaluation.md) lives in `evaluations/g4sipm`
and is separate from the G4PEC application. Upstream sources are not vendored.

The project aims for open-source release; **a G4PEC release license has not yet
been selected**. The external G4SiPM evaluation uses its upstream GPLv3 code only
in a separate local executable.
