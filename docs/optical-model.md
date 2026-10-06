# Optical model contract

The geometry and optical boundary definitions are loaded from GDML. SiPM PDE and
gain belong to the independent digitizer, not the Geant4 collector surface.
This separation permits replaying response settings without rerunning transport.

## A single-channel entrance

The example uses a BGO crystal, a glass coupling layer matching the sensor footprint,
and a silicon collecting volume. The sensor logical volume is tagged with
`Readout=SiPM`. Its passive skin has zero detection efficiency and zero reflectivity.
A directed border overrides the skin at the coupling-to-sensor interface:

```xml
<skinsurface name="sensorInactive" surfaceproperty="inactiveSensor">
  <volumeref ref="Sensor"/>
</skinsurface>
<bordersurface name="sensorEntrance" surfaceproperty="collector">
  <physvolref ref="coupling"/>
  <physvolref ref="sipm"/>
</bordersurface>
```

`collector` is polished, unified, dielectric-metal, with explicit constant
`REFLECTIVITY=0` and `EFFICIENCY=1` vectors. The passive skin must explicitly use
`EFFICIENCY=0`. These conventions are checked at initialization to prevent accidental
all-face readout or a second PDE filter in transport. A border with zero efficiency
is passive and does not satisfy the requirement for an incoming collector.

The border is directional and refers to physical placements. Only their actual
shared interface is active. It supports rotation/translation without selecting a
fixed global Z face. If two volumes share several interfaces, all interfaces in
that ordered pair use the border; model a distinct entrance/window volume when
only one should collect. The current checker does not establish whether volumes
touch. Geometry overlap checks do not detect gaps.

The example absorbs side/rear photons without a signal. This is an explicit ideal
boundary assumption, not a prediction of a packaged SiPM. The collector is not a
physical silicon Fresnel interface. Window reflection, transmission and absorption
should be modelled upstream of the ideal collector, rather than folded into its
efficiency and then counted again in the digitizer.

## Parameter ownership and provenance

| Definition | Owner | Units and interpretation |
| --- | --- | --- |
| Shapes, placement and material assignment | GDML solids/structure | Explicit mm/degrees |
| Refractive index | GDML material property | Dimensionless versus photon energy |
| Absorption length | GDML material property | Length versus photon energy |
| Emission spectrum | GDML material property | Relative spectral weights versus energy |
| Scintillation yield and decay time | GDML material properties | Photons/MeV and ns |
| Passive and collecting interfaces | GDML optical/border/skin surfaces | Transport conditions, not sensor PDE |
| Photon selection and avalanche gain | Independent digitizer arguments | PDE in [0,1]; electrons per accepted photon |

All example optical numbers are illustrative assumptions, not measured or fitted
device parameters. Material composition and density define the transport medium;
they do not establish the optical quality of a real crystal. User configurations
should document the source of each parameter (measurement, datasheet, publication,
or assumption), units, applicable energy range and model limitations. The current
example records its illustrative provenance in GDML comments and this document;
there is not yet a structured provenance schema or separate optical YAML loader.

Input GDML and macro snapshots and the random state accompany each run. Response
settings are written separately by the digitizer. Never interpret the sample
constants as recommended calibration values. Real-device calibration remains a
user responsibility.

## Verification and limits

Automated checks exercise the directed entrance with front, side and rear beams;
translated and rotated local coordinates; analytic flight time in constant-index
glass; malformed collector definitions; and gamma-induced scintillation transport.
Independent response checks cover PDE endpoints, fixed-gain charge and seeded replay.

Separate [analytical optical benchmarks](optical-benchmarks.md) check exponential
attenuation, polarized Fresnel transmission, Snell refraction, Brewster-angle
transmission and total internal reflection with a single-pass synthetic fixture.
The separate [cell response](cell-response.md) adds dead time, charge recovery
and saturation after optical transport. Optional acquisition noise is also modeled
offline. A separate linear waveform/ADC readout is implemented. A physical
entrance window, detailed electronics and measurement calibration are not implemented.

Geant4 implementation reference: `G4OpBoundaryProcess` selects a directed logical
border before falling back to a logical skin. The application relies on that
selection and records only `Detection` at tagged sensor volumes.
