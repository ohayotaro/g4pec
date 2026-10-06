# Multi-SiPM transport and response to portable output

`tools/digitize_channels.py` processes one Geant4 transport dataset and acquisition
timeline through independent per-channel SiPM responses, producing a
[portable dataset](sipm-dataset.md). Crystal shape and segmentation do not select
response-processing branches. This layer retains the existing example parameters.

## Processing contract

- Each channel has independent cell state, PDE random draws and noise state. Equal
  cell indices on different SiPMs are unrelated. Recovery/noise persists across
  events within each channel.
- All channels use the same transport dataset/run and acquisition timeline, with
  time defined as `event offset + Geant4 time`.
- Total photon counts, per-event active-channel counts, unknown channels and duplicate
  event-local track IDs are checked before filtering. Channel selection must not
  hide invalid global input.
- Every GDML `Readout=SiPM` placement must be configured, including inactive channels.
  Head assignments come from each sensor logical volume's DetectorID.
- Seeds derive from SHA256 of the master seed and physical placement path, independent
  of configuration-list order or logical channel name. Changing the physical path
  changes its seed. The derivation rule and seeds are recorded.
- Geant4 handles optical light sharing. This response model does not add electrical
  coupling or inter-channel crosstalk; existing XT/AP models act within one SiPM.

## Configuration and execution

Each entry in `examples/validation/two_channels.json` contains channel_id, an existing
cells configuration and noise settings (null disables noise). cells.channel_path
specifies the physical binding. Multiple channels may share DetectorID; crystal
numbers or one-to-one crystal/sensor mappings are not required.

```sh
build/g4pec examples/validation/two_collectors.gdml \
  examples/validation/two_collectors.mac output/two_collectors
python3 tools/make_timeline.py output/two_collectors_run0_events.csv \
  output/two_collectors_timeline.json --spacing-ns 12 \
  --first-offset-ns 100 --window-end-ns 2000
python3 tools/digitize_channels.py output/two_collectors_run0_photons.csv \
  output/two_collectors_run0_events.csv output/two_collectors_run0_geometry.gdml \
  output/two_collectors_timeline.json examples/validation/two_channels.json \
  output/two_collectors_response
python3 tools/analyze_sipm.py output/two_collectors_response/dataset left \
  output/two_collectors_left --config examples/single_channel_readout.json
```

Outputs include input snapshots in inputs/, legacy channel responses in responses/,
the portable dataset/ and channel/seed/count summaries in run.json. Only dataset/
needs to move for post analysis. Retain everything for verification requiring original
inputs, responses or truth. Existing destinations are rejected; failure removes only
the directory newly created by that execution.

## Meaning of the validation geometry

`examples/validation/two_collectors.gdml` directly illuminates two equally oriented
box SiPMs. The second coupling/sensor is displaced by 15 mm along X. Two sources
illuminate from within the respective couplings; sensor faces remain parallel to XY.
Both sensors belong to detector0 to test two channels in one head. This is an optical
bench, not a proposed PEC layout or positron-annihilation model.

The five multi_channel_response tests check:

1. Thirty-two Geant4 events produce 64 photons, 32 per SiPM and two active channels
   per event. With test-only PDE=1, both sensors independently provide full initial
   charge, then recovery `1-exp(-(12 ns-0.001 ns)/30 ns)` on the next input.
2. Noisy histories remain identical when channel configuration order is reversed.
3. Removing one channel's input and recounting events causes no cross-feed; the
   inactive channel remains in portable output.
4. Missing settings and global count mismatches fail without invalid partial output.
5. Replacing the crystal with a GDML subtraction-solid slit preserves the transport
   to response to portable-data path under the same direct illumination.

The last test checks a non-box crystal interface. Because sources are in the
couplings, it does not assess U-crystal light sharing or DOI discrimination.

Retained results in `output/two_channels_verified_final/` include transport snapshots,
noise-on/off responses, inactive channels, subtraction-solid transport, portable
outputs and replay. At that milestone all 15 CTest entries were exercised; after
repairing a legacy error-message mismatch, affected cell_response and
multi_channel_response tests passed again.

The legacy CLI retains its single-SiPM requirement. The multi-channel CLI still
requires numerically sized box sensors and explicit GDML placements. Arbitrary
sensor shapes and replica/parameterised placement support remain unimplemented.
Later stages add [scintillation/head features](dual-sipm-head.md), uncalibrated head
singles and [ideal gamma-pair integration](opposed-heads.md). Common-trigger waveform
aggregation, calibrated head response and continuous DOI remain future work.
