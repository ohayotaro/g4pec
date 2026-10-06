# Analytical optical benchmarks

`tests/check_optical_benchmarks.py` exercises optical transport through two planar
dielectric slabs and one SiPM collecting channel. CTest runs it separately from
the single-crystal pipeline. The BGO example and the offline PDE/gain response are
unchanged; benchmark materials are deliberately synthetic.

## Fixture and comparison conditions

The first slab occupies -10 < z < 0 mm, the second 0 < z < 10 mm. Both are
100 x 100 mm in transverse extent. One 100 x 100 x 0.1 mm collecting volume touches
the second slab at z = 10 mm. This large test collector prevents geometrical
acceptance from contaminating the probability comparison; it does not represent
the example SiPM dimensions. All geometry remains in generated GDML.

Each independent event launches one 2.5 eV photon from (0, 0, -1) mm. The incident
direction lies in XZ and crosses the interface at x = tan(theta_i) mm, y = 0. For s
polarization the electric vector points along Y; for p it is (cos(theta), 0,
-sin(theta)), perpendicular to propagation. Constant refractive indices eliminate
dispersion in this fixture. No scintillation, scattering, wavelength shifting or
bulk absorption is defined except for the explicit attenuation cases.

A polished unified dielectric/dielectric border overrides black outer skins at
the first-to-second slab interface. Reflected photons terminate at other black
faces instead of returning for another transmission attempt. A directed ideal
collector border at the second-to-sensor interface records all surviving photons.
PDE filtering is absent from the benchmark. Therefore the arrival fraction
measures single-pass transmission times bulk survival.

## Independent expectations

For slab depth d = 10 mm and absorption length L, survival is
`exp(-d / (L cos(theta_t)))`. Equal indices isolate attenuation. Tests use L = 5,
10 and 20 mm at normal incidence, and L = 20 mm at 60 degrees. A clear-medium
case requires all photons to arrive.

For lossless dielectric boundaries, Snell's law gives
`sin(theta_t) = n1 sin(theta_i) / n2`. With `ci = cos(theta_i)` and
`ct = cos(theta_t)`, the Fresnel power reflectances are:

```text
Rs = ((n1 ci - n2 ct) / (n1 ci + n2 ct))^2
Rp = ((n2 ci - n1 ct) / (n2 ci + n1 ct))^2
T  = 1 - R
```

The formulas calculate photon probabilities rather than electric-field amplitude
transmission. The implementation is independent Python arithmetic, not a call to
Geant4's boundary probability calculation. Cases cover n1 = 1 to n2 = 1.5 at
0 and 60 degrees for both polarizations, p polarization at the Brewster angle
`atan(1.5)`, n1 = 1.5 to n2 = 1 at 30 degrees, and total internal reflection at
50 degrees for both polarizations. There are 14 cases in total.

For every arriving photon, checks compare the sensor-local direction and position
with Snell's law, and the flight time with
`(n1 / cos(theta_i) + 10 n2 / cos(theta_t)) / c`, where c = 299.792458 mm/ns.
The local collecting plane is z = -0.05 mm. Relative tolerance is 1e-7 and absolute
tolerance is 1e-8 in each CSV field's units. Photon energy and event/channel
accounting are checked as well.

## Statistics and acceptance

Each case uses 20,000 independent events and a fixed pair of random seeds. For
analytic probability p, the expected count is Np and its binomial standard
deviation is `sqrt(Np(1-p))`. Before running, the acceptance interval is fixed to
six standard deviations plus one count for integer discretization. Exact zero
and one probabilities require exact counts. The interval is a regression
criterion; it is not a confidence claim about a real detector. Interior cases
have substantial success and failure counts, so the Gaussian six-sigma scale is
appropriate here. Seeds and criteria must not be tuned to make a failed check pass.

Retain reproducible inputs, random states, output CSVs, logs and a JSON report with:

```sh
python3 tests/check_optical_benchmarks.py build/g4pec . \
  --output-dir output/optical_benchmarks
```

Use a new output directory each time. The report records indices, incidence,
polarization, attenuation length, seeds, counts, probabilities, standard errors
and count acceptance intervals. CTest uses temporary files and prints case results;
use the command above when results must be retained.

## Scope and references

The resumed session ran all 14 cases successfully with Geant4 11.4.0 plus matching
GDML sources and Xerces-C 3.3.0 (see the local setup in `handoff.md`). The tests
found an optical-photon scintillation registration that reset boundary-updated
group velocity. The application now removes that optical-photon registration;
scintillation remains enabled for other particles. Before the fix, the normal
n = 1 to 1.5 flight time was 0.03669205047 ns rather than 0.05337025523 ns. The
unchanged analytic time criterion passes after the fix.

These checks validate single-pass transport under ideal planar conditions. They
do not validate rough surfaces, measured BGO optical constants, physical entrance
windows, dispersion, scattering or sensor microcells. Reflection is inferred as
one minus transmission in the lossless Fresnel fixture; reflected trajectories
are not separately recorded. Real-device calibration remains the user's task.

The governing polarization and dielectric-boundary equations are documented in
the [Geant4 Physics Reference Manual, Interactions of optical photons](https://geant4.web.cern.ch/documentation/pipelines/master/prm_html/PhysicsReferenceManual/electromagnetic/optical_photons/optical.html).
Bulk absorption uses the mean-free-path interpretation of `ABSLENGTH` in the
[Geant4 application developer guide, optical physics](https://geant4.web.cern.ch/documentation/dev/bfad_html/ForApplicationDevelopers/TrackingAndPhysics/physicsProcess.html).
