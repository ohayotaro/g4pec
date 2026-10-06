# G4SiPM compatibility and integration evaluation

Evaluated on 2026-10-06. G4PEC uses an independent event-based backend behind
the existing pre-PDE arrival boundary. The subsequent [cell response](cell-response.md)
implements the mapping, initial state, recovery and saturation contract below;
noise and waveform modeling remain later work.
G4SiPM remains an optional comparison reference. Its existing response code can
be compiled in isolation on this machine, but adopting its complete stack would
require compatibility repairs and changes to geometry, probability ownership and
initial-state handling.

This is a bounded compatibility/behaviour evaluation, not validation of the
complete upstream SiPM model. No G4SiPM code is linked into the `g4pec` executable
or the Python digitizer. The separately built evaluation executable does link
upstream code from an ignored dependency checkout.

## Pinned source and environment

| Item | Evaluated value |
| --- | --- |
| Upstream | [ntim/g4sipm](https://github.com/ntim/g4sipm/tree/40b0017f266c0708c39c595ebb4d09385acc2717) |
| Commit | `40b0017f266c0708c39c595ebb4d09385acc2717`, 2017-03-28 |
| Platform/compiler | macOS arm64, AppleClang 21.0.0, C++17 |
| Geant4 | 11.4.0 installed libraries |
| CMake | 4.4.3 |
| Boost | 1.85.0, locally built static single-threaded libraries |
| Upstream Jansson submodule | `bc5741fb1ac730ead24e9bd08977fc6c248e04b0` |
| Upstream GoogleTest submodule | `a2b8a8e07628e5fd60644b6dd99c1b5e7d7f1f47` |
| Optional upstream features | ROOT, SQLite and UI/visualization requests disabled |
| License | Upstream [GPLv3 license](https://github.com/ntim/g4sipm/blob/40b0017f266c0708c39c595ebb4d09385acc2717/LICENSE); G4PEC release license remains undecided |

The upstream checkout was not edited. Downloads, dependencies and binaries are
under `build/` and are excluded from Git. The response probe needs no GDML parser
because it constructs no transport geometry.

## Actual build results

| Attempt | Result |
| --- | --- |
| Original top-level CMake | Fails: minimum CMake 2.8 policy compatibility is removed in CMake 4 |
| Add `CMAKE_POLICY_VERSION_MINIMUM=3.5` | Initially fails to find Boost; resolved by the local Boost build |
| With Boost and pinned submodules | Configuration succeeds; `g4sipm` library build fails on `G4OpticalPhysics::Configure` and `std::binary_function` |
| Response subset, excluding the physics-list helper | Also exposes removed `G4VisAttributes::Invisible` in housing code |
| Response subset, excluding physics-list and housing sources, with libc++ legacy comparator switch | Builds; characterization test passes |

The independent CMake project at `evaluations/g4sipm` excludes
`OpticalPhysicsList.cc` and `src/housing/`, and enables libc++'s
`_LIBCPP_ENABLE_CXX17_REMOVED_UNARY_BINARY_FUNCTION`. This restores the deprecated
comparator base typedefs without altering its comparison implementation. The
remaining library sources compile, including hit/digitizer, configuration and
waveform classes. The runtime probe exercises only cell mapping, cell-fire
control and queue ordering. It does **not** run the full upstream test suite,
sample application, sensitive detector, correlated-noise digitizer or waveform
generator. No compatibility claim is made for these unexecuted paths.

Logs from this checkout are in `build/g4sipm-evaluation/`:
`configure-original.log`, `configure-policy.log`, `configure-dependencies.log`,
`build-original.log` and the response build/configuration logs. The additional
housing API failure was observed while narrowing the response subset; the final
response build log records the successful subset build.

## Executed behaviour checks

The probe uses a synthetic 2 x 2 cell model, 1 mm pitch, 1 ns dead time, 10 ns
recovery time, fill factor 0.25, no gain variation and seed 12345. Noise is disabled.
These are deliberately simple test parameters, not a device model.

- Local coordinates map to the expected cells. The negative outside edge is
  included and the positive edge excluded. The optional dead-border check rejects
  positions outside a cell's active square.
- The recovered charge fraction after dead time plus one recovery constant is
  `1 - exp(-1) = 0.6321205588285577`.
- Simultaneous triggers in one cell and triggers exactly at the dead-time boundary
  are rejected. Different fully charged cells can fire simultaneously.
- Supplying a last-fire reference at -1000 ns gives unit charge for the first
  trigger at 0 ns. The time queue returns earlier triggers first.
- With the upstream controller initialized at `t0 = 0`, the first trigger at
  0 ns is rejected. This is a reproduced integration limitation, not a desired
  G4PEC acceptance criterion.

The last observation matters because upstream `G4SipmDigitizer::Digitize` sets
`t0` to the earliest item in its queue, and the controller initializes every
cell's last-fire time to `t0`. With thermal noise disabled, the earliest photon
cannot pass its timing filter. A simultaneous photon burst can consequently
produce no avalanches. With thermal noise enabled, prehistory partly changes
this situation, but that is a different initial-state assumption. G4PEC's
independent event response needs an explicit initially charged state or a
specified noise prehistory. This conclusion combines the executed controller
probe with inspection of the upstream digitizer's queue initialization.

The report is `build/g4sipm-evaluation/response/response-report.json`. A passing
test confirms reproduction of the behaviours above, including the known `t0`
limitation; it does not certify the upstream implementation for production use.

## How the existing arrival stream maps to G4SiPM

| G4PEC data or responsibility | Upstream API/behaviour | Adapter requirement |
| --- | --- | --- |
| Placement-path channel ID | Incrementing `G4SipmId` | Explicit stable channel-to-instance mapping |
| Sensor-local x/y in mm | `G4SipmHit::setPosition`, `G4SipmModel::getCellId` | Convert units; validate grid extent against GDML; reject out-of-area positions |
| Event-local arrival time in ns | `G4SipmHit::setTime`; Geant4 event hit collections | Populate a separate event context or refactor the digitizer's collection access |
| Photon energy in eV | `setEKin`; PDE filter converts energy to wavelength | One declared PDE owner and consistent units |
| Pre-PDE, unit-weight arrival | Digitizer assumes hits already passed sensitivity filtering | Apply PDE exactly once before creating accepted hits, or implement a new response entry point |
| GDML-owned geometry | `G4Sipm::build` makes C++ geometry and registers SD/digitizers | Avoid replacing the GDML geometry; instantiate response services separately |
| Fixed-gain output in pC | Digi weight is normalized recovered gain | Explicit reference gain and electron-to-pC conversion |
| Zero-hit event record | Noise windows derive from hit extrema and UI pre/post settings | Explicit acquisition window, including empty events |

The upstream sensitive-detector filter is especially unsuitable for direct reuse
on our ideal collector arrivals. It divides its model PDE by fill factor and by
an air/window/silicon Fresnel transmittance, then optionally applies a separate
geometric dead-area filter. Our transport can already include user-defined
coupling/window effects, and its incoming medium need not be air. Applying that
correction without a declared PDE reference plane would change photon acceptance
and can double-count or undo transport effects. The upstream digitizer itself
does not perform the base wavelength-PDE trial in `addHits`.

The global UI messenger also replaces the CLHEP random engine, defaults its seed
from wall-clock time, and attempts to read `g4sipm.mac` from the working directory.
A replay adapter would need to isolate and record that configuration. Direct
event-to-event continuation is not provided by a controller recreated for each
digitization call.

## Decision and next implementation contract

Use an independently implemented backend for the next milestone, with externally
recorded parameters and the existing ideal digitizer retained as a limiting-case
reference. The reasons are the working independent transport boundary, explicit
initial-state/window requirements and the maintenance needed for the upstream
API and runtime assumptions. This decision does not claim that the upstream
physical models are generally invalid. Revisit a separately licensed comparison
adapter after G4PEC's response contract and validation cases are established.

The first detailed backend should implement:

1. Sensor-local grid mapping with explicit cell counts, pitch and origin. The
   provisional grid must fit the 5.8 x 5.8 mm single-channel footprint; mapping
   does not add microcell geometry to Geant4.
2. Fully charged cells at the start of each independent event; time-ordered
   photon processing; specified dead time and exponential recovery. Rejected
   photon attempts must not reset cell recovery.
3. A declared effective PDE at the collector plane. The first model should not
   apply a second fill-factor or Fresnel correction. Any dependence of trigger
   probability on recovery must be an explicit documented model choice.
4. Per-avalanche cell ID, cause and recovered charge, with existing event/channel
   summaries preserved. All parameters, units, seed and model version accompany
   output. Cross-event state remains unsupported until a source-time model exists.
5. Validation of an isolated first photon, two pulses in one cell, independent
   cells, simultaneous saturation, full-recovery and PDE-zero/one limits. For M
   simultaneous photons uniformly assigned to N initially charged cells with
   detection probability p, compare mean fired cells with
   `N * (1 - (1 - p/N)^M)` under the declared no-recovery/no-noise conditions.

Introduce dark counts, crosstalk and afterpulsing after these checks, using an
explicit finite acquisition window and separate cause accounting. Then add
waveform generation as its own stage. No measurement fitting is required to
complete these software/model checks.

## Reproduce the response probe

Obtain the pinned source (the subset probe does not need its submodules):

```sh
git clone https://github.com/ntim/g4sipm.git build/dependencies/g4sipm-source
git -C build/dependencies/g4sipm-source checkout 40b0017f266c0708c39c595ebb4d09385acc2717
```

With Geant4 11.3+ and Boost date_time/regex available, configure and run separately
from the application build. The paths below match this machine:

```sh
cmake -S evaluations/g4sipm -B build/g4sipm-evaluation/response \
  -DG4SIPM_SOURCE="$PWD/build/dependencies/g4sipm-source" \
  -DGeant4_DIR=/Users/ohayotaro/geant4/geant4-install/lib/cmake/Geant4 \
  -DBOOST_ROOT="$PWD/build/dependencies/boost-install" \
  -DBoost_NO_BOOST_CMAKE=ON -DBoost_NO_SYSTEM_PATHS=ON
cmake --build build/g4sipm-evaluation/response -j 4
ctest --test-dir build/g4sipm-evaluation/response --output-on-failure
```

Boost 1.85.0 came from the [official release archive](https://archives.boost.io/release/1.85.0/source/boost_1_85_0.tar.bz2).
It was bootstrapped with `--with-libraries=date_time,program_options,filesystem,system,regex`
and the local install prefix above, then built with
`./b2 -j8 cxxstd=17 link=static threading=single variant=release install`.
Only date_time/regex are needed for the subset; the other components were needed
for the original upstream configuration attempt.

To reproduce that original attempt, initialize the pinned submodules and configure
its top-level project with `CMAKE_POLICY_VERSION_MINIMUM=3.5`, the same Boost/Geant4
paths, `Boost_USE_STATIC_LIBS=ON`, and `WITH_ROOT=OFF`, `WITH_SQLITE=OFF`,
`WITH_GEANT4_UIVIS=OFF`. Building target `g4sipm` reproduces the compiler failures.

## Inspected upstream sources

All links below refer to the evaluated commit:

- [Top-level build](https://github.com/ntim/g4sipm/blob/40b0017f266c0708c39c595ebb4d09385acc2717/CMakeLists.txt)
- [Geometry and module registration](https://github.com/ntim/g4sipm/blob/40b0017f266c0708c39c595ebb4d09385acc2717/g4sipm/src/G4Sipm.cc)
- [Hit filtering and PDE compensation](https://github.com/ntim/g4sipm/blob/40b0017f266c0708c39c595ebb4d09385acc2717/g4sipm/src/hit/G4SipmSensitiveDetectorFilter.cc)
- [Digitizer and noise queue](https://github.com/ntim/g4sipm/blob/40b0017f266c0708c39c595ebb4d09385acc2717/g4sipm/src/digi/G4SipmDigitizer.cc)
- [Cell initial state and recovery](https://github.com/ntim/g4sipm/blob/40b0017f266c0708c39c595ebb4d09385acc2717/g4sipm/src/digi/G4SipmCellFireController.cc)
- [Cell coordinate mapping](https://github.com/ntim/g4sipm/blob/40b0017f266c0708c39c595ebb4d09385acc2717/g4sipm/src/model/G4SipmModel.cc)
- [Global UI configuration and random engine](https://github.com/ntim/g4sipm/blob/40b0017f266c0708c39c595ebb4d09385acc2717/g4sipm/src/G4SipmUiMessenger.cc)
