"""Single-pass absorption and polarized Fresnel checks; no sensor PDE filtering.

Run with an optional --output-dir to retain GDML, macros, transport output and a
JSON comparison report. Default CTest runs use a disposable temporary directory.
"""
import argparse
import copy
import csv
import json
import math
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET


EVENTS = 20000
SIGMAS = 6
C_MM_NS = 299.792458


def transmission(n1, n2, angle_deg, polarization):
    """Lossless dielectric photon probability from Snell/Fresnel equations."""
    incident = math.radians(angle_deg)
    sin_t = n1 / n2 * math.sin(incident)
    if sin_t >= 1:
        return 0.0, None
    cos_i, cos_t = math.cos(incident), math.sqrt(1 - sin_t * sin_t)
    if polarization == "s":
        reflection = ((n1 * cos_i - n2 * cos_t) /
                      (n1 * cos_i + n2 * cos_t)) ** 2
    else:
        reflection = ((n2 * cos_i - n1 * cos_t) /
                      (n2 * cos_i + n1 * cos_t)) ** 2
    return 1 - reflection, math.asin(sin_t)


def geometry(root, target, n1, n2, absorption_mm):
    """Two 10 mm slabs, black outer faces, one full-face ideal collector.

    The crystal/coupling names are reused only to keep the fixture small. Their
    materials are replaced, with no scintillation or scattering properties.
    Reflected photons terminate on black faces instead of retrying the interface.
    """
    tree = ET.parse(root / "examples/single_detector.gdml")
    define = tree.find("define")
    for name, value in (("incidentIndex", n1), ("sampleIndex", n2)):
        ET.SubElement(define, "matrix", name=name, coldim="2",
                      values=f"2*eV {value} 4*eV {value}")
    materials = tree.find("materials")
    for name, index in (("IncidentMedium", "incidentIndex"),
                        ("SampleMedium", "sampleIndex")):
        material = copy.deepcopy(materials.find("material[@name='CouplingGlass']"))
        material.set("name", name)
        material.find("property[@name='RINDEX']").set("ref", index)
        material.remove(material.find("property[@name='ABSLENGTH']"))
        if name == "SampleMedium" and absorption_mm is not None:
            ET.SubElement(define, "matrix", name="sampleAbsorption", coldim="2",
                          values=f"2*eV {absorption_mm}*mm 4*eV {absorption_mm}*mm")
            # GDML properties precede density/composition.
            material.insert(1, ET.Element("property", name="ABSLENGTH", ref="sampleAbsorption"))
        materials.append(material)
    solids = tree.find("solids")
    for name, depth in (("crystalBox", 10), ("couplingBox", 10), ("sensorBox", 0.1)):
        box = solids.find(f"box[@name='{name}']")
        box.set("x", "100")
        box.set("y", "100")
        box.set("z", str(depth))
    world_box = solids.find("box[@name='worldBox']")
    for axis in ("x", "y", "z"):
        world_box.set(axis, "400")
    ET.SubElement(solids, "opticalsurface", name="dielectricInterface", model="unified",
                  finish="polished", type="dielectric_dielectric", value="1")
    structure = tree.find("structure")
    for volume, material in (("Crystal", "IncidentMedium"), ("Coupling", "SampleMedium")):
        structure.find(f"volume[@name='{volume}']/materialref").set("ref", material)
        skin = ET.SubElement(structure, "skinsurface", name=f"black{volume}",
                             surfaceproperty="inactiveSensor")
        ET.SubElement(skin, "volumeref", ref=volume)
    world = structure.find("volume[@name='World']")
    for placement, z in (("crystal", -5), ("coupling", 5), ("sipm", 10.05)):
        world.find(f"physvol[@name='{placement}']/position").set("z", str(z))
    border = ET.SubElement(structure, "bordersurface", name="testInterface",
                           surfaceproperty="dielectricInterface")
    ET.SubElement(border, "physvolref", ref="crystal")
    ET.SubElement(border, "physvolref", ref="coupling")
    tree.write(target, encoding="utf-8", xml_declaration=True)


def run_case(exe, root, directory, case, seed):
    name, n1, n2, angle, polarization, absorption = case
    gdml, macro = directory / f"{name}.gdml", directory / f"{name}.mac"
    geometry(root, gdml, n1, n2, absorption)
    theta = math.radians(angle)
    # Incidence plane XZ: s is along Y; p lies in XZ and is transverse to k.
    electric = (0, 1, 0) if polarization == "s" else (math.cos(theta), 0, -math.sin(theta))
    macro.write_text(
        f"/random/setSeeds {seed} {seed + 137}\n/run/initialize\n"
        "/gps/particle opticalphoton\n/gps/energy 2.5 eV\n"
        f"/gps/polarization {' '.join(str(v) for v in electric)}\n"
        "/gps/pos/type Point\n"
        "/gps/pos/centre 0 0 -1 mm\n"
        f"/gps/direction {math.sin(theta)} 0 {math.cos(theta)}\n"
        f"/run/beamOn {EVENTS}\n", encoding="utf-8")
    prefix = directory / name
    result = subprocess.run([str(exe), str(gdml), str(macro), str(prefix)],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=90)
    (directory / f"{name}.log").write_text(result.stdout, encoding="utf-8")
    if result.returncode or "GeomVol1002" in result.stdout or "COMMAND NOT FOUND" in result.stdout:
        raise AssertionError(result.stdout[-12000:])
    with (directory / f"{name}_run0_events.csv").open(newline="") as stream:
        events = list(csv.DictReader(stream))
    with (directory / f"{name}_run0_photons.csv").open(newline="") as stream:
        hits = list(csv.DictReader(stream))
    assert [int(e["event_id"]) for e in events] == list(range(EVENTS)), name
    assert all(int(e["n_arrivals"]) in (0, 1) and
               int(e["n_active_channels"]) == int(e["n_arrivals"]) and
               int(e["scintillation_photons"]) == 0 for e in events), name
    assert len({int(h["event_id"]) for h in hits}) == len(hits), name
    assert sum(int(e["n_arrivals"]) for e in events) == len(hits), name
    assert {int(h["event_id"]) for h in hits} == {
        int(e["event_id"]) for e in events if int(e["n_arrivals"]) == 1}, name
    probability, theta_t = transmission(n1, n2, angle, polarization)
    if absorption is not None:
        probability *= math.exp(-10 / (absorption * math.cos(theta_t)))
    expected = EVENTS * probability
    sigma = math.sqrt(EVENTS * probability * (1 - probability))
    # Exact physical endpoints are deterministic. Interior binomial counts get
    # a predeclared six-sigma interval plus one count for integer discretization.
    if probability == 0 or probability == 1:
        tolerance = 0.0
    else:
        tolerance = SIGMAS * sigma + 1
    assert abs(len(hits) - expected) <= tolerance, (
        f"{name}: {len(hits)}/{EVENTS}, expected p={probability:.9g}, "
        f"count deviation={len(hits) - expected:.3f}, allowed={tolerance:.3f}")
    if theta_t is not None:
        expected_time = (n1 / math.cos(theta) + 10 * n2 / math.cos(theta_t)) / C_MM_NS
        for hit in hits:
            assert hit["channel_path"] == "/World_PV[0]/sipm[0]", name
            for key, value in (("local_x_mm", math.tan(theta) + 10 * math.tan(theta_t)),
                               ("local_y_mm", 0), ("local_z_mm", -0.05),
                               ("local_dx", math.sin(theta_t)), ("local_dy", 0),
                               ("local_dz", math.cos(theta_t)), ("time_ns", expected_time),
                               ("photon_energy_eV", 2.5)):
                assert math.isclose(float(hit[key]), value, rel_tol=1e-7, abs_tol=1e-8), (name, key, hit[key], value)
    report = dict(name=name, n1=n1, n2=n2, incident_angle_deg=angle,
                  polarization=polarization, absorption_length_mm=absorption,
                  slab_depth_mm=10, energy_eV=2.5, seeds=[seed, seed + 137],
                  events=EVENTS, arrivals=len(hits), expected_probability=probability,
                  observed_probability=len(hits) / EVENTS,
                  binomial_standard_error=sigma / EVENTS,
                  allowed_count_deviation=tolerance,
                  z_score=(len(hits) - expected) / sigma if sigma else None)
    print(f"PASS {name}: {len(hits)}/{EVENTS}; expected {probability:.6f}", flush=True)
    return report


def benchmark(exe, root, directory):
    cases = [
        ("clear", 1.5, 1.5, 0, "s", None),
        ("absorption_5mm", 1.5, 1.5, 0, "s", 5),
        ("absorption_10mm", 1.5, 1.5, 0, "s", 10),
        ("absorption_20mm", 1.5, 1.5, 0, "s", 20),
        ("absorption_oblique", 1.5, 1.5, 60, "s", 20),
        ("normal_s", 1, 1.5, 0, "s", None),
        ("normal_p", 1, 1.5, 0, "p", None),
        ("oblique_s", 1, 1.5, 60, "s", None),
        ("oblique_p", 1, 1.5, 60, "p", None),
        ("brewster_p", 1, 1.5, math.degrees(math.atan(1.5)), "p", None),
        ("high_to_low_s", 1.5, 1, 30, "s", None),
        ("high_to_low_p", 1.5, 1, 30, "p", None),
        ("total_internal_s", 1.5, 1, 50, "s", None),
        ("total_internal_p", 1.5, 1, 50, "p", None),
    ]
    reports = [run_case(exe, root, directory, case, 24680 + index * 1000)
               for index, case in enumerate(cases)]
    with (directory / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(dict(acceptance_sigma=SIGMAS, cases=reports), stream, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("repository", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    exe, root = args.executable.resolve(), args.repository.resolve()
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        benchmark(exe, root, args.output_dir.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="g4pec-benchmarks-") as directory:
            benchmark(exe, root, Path(directory))


if __name__ == "__main__":
    main()
