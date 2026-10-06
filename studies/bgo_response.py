#!/usr/bin/env python3
"""Descriptive BGO end-to-end study; truth is used only for evaluation windows."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from digitize_cells import digitize
from make_timeline import make_timeline
from readout import readout

SPACING = 10000.
FIRST = 1000.
SOURCE_TIME = 7.
ROI_LENGTH = 3000.


def rows(path):
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))


def summary(values):
    values = list(values)
    return {'n': len(values), 'mean': statistics.mean(values) if values else None,
            'sd': statistics.stdev(values) if len(values)>1 else None,
            'se': statistics.stdev(values)/math.sqrt(len(values)) if len(values)>1 else None}


def quantiles(values):
    values = sorted(values)
    def q(p):
        if not values: return None
        pos = (len(values)-1)*p
        i = int(pos); fraction = pos-i
        return values[i]*(1-fraction)+values[min(i+1,len(values)-1)]*fraction
    return {f'p{int(100*p)}_ns': q(p) for p in (.1,.5,.9)}


def wilson(k, n):
    z = 1.959963984540054
    center = (k/n+z*z/(2*n))/(1+z*z/n)
    radius = z*math.sqrt(k/n*(1-k/n)/n+z*z/(4*n*n))/(1+z*z/n)
    return {'count': k, 'total': n, 'fraction': k/n, 'wilson95': [center-radius, center+radius]}


def accumulate_roi(charges, left, right, voltage_mV, resistance):
    """Evaluation only: split a sample by its geometric overlap with source ROIs."""
    first = max(0, math.floor((left-FIRST-SOURCE_TIME)/SPACING))
    last = min(len(charges)-1, math.floor((right-FIRST-SOURCE_TIME)/SPACING))
    for event in range(first, last+1):
        begin = FIRST+event*SPACING+SOURCE_TIME
        overlap = max(0., min(right,begin+ROI_LENGTH)-max(left,begin))
        charges[event] += voltage_mV*overlap/resistance


def select_candidates(singles, source):
    selected = [s for s in singles if source-1 <= float(s['time_ns']) < source+ROI_LENGTH]
    preceding = [s for s in singles if float(s['time_ns']) < source-1 and float(s['gate_end_ns']) > source]
    return selected, preceding


def run_case(executable, output, label, energy, depth, n, index, reanalyze=False):
    directory = output/label
    if not reanalyze:
        directory.mkdir()
    seeds = [12345+101*index, 67890+211*index]
    macro = directory/'source.mac'
    if not reanalyze:
        macro.write_text('\n'.join([
            '/control/verbose 0', '/run/verbose 0', '/event/verbose 0', '/tracking/verbose 0',
            f'/random/setSeeds {seeds[0]} {seeds[1]}', '/run/initialize', '/gps/particle e-',
            f'/gps/energy {energy} keV', '/gps/pos/type Point', f'/gps/pos/centre 0 0 {depth} mm',
            '/gps/direction 0 0 1', f'/gps/time {SOURCE_TIME} ns', f'/run/beamOn {n}', '']))
        result = subprocess.run([str(executable), str(ROOT/'examples/single_detector.gdml'), str(macro), str(directory/'transport')],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        (directory/'transport.log').write_text(result.stdout)
        if result.returncode or 'GeomVol1002' in result.stdout:
            raise RuntimeError(result.stdout[-8000:])
    base = directory/'transport_run0'
    photons_path, events_path = Path(str(base)+'_photons.csv'), Path(str(base)+'_events.csv')
    hits, events = rows(photons_path), sorted(rows(events_path), key=lambda e: int(e["event_id"]))
    if len(events) != n or {int(e['event_id']) for e in events} != set(range(n)):
        raise ValueError('Unexpected transport event indexing')
    by_event = {i: [] for i in range(n)}
    for h in hits:
        t = float(h['time_ns'])-SOURCE_TIME
        if not 0 <= t < SPACING-500:
            raise ValueError('Photon crosses isolation guard; increase spacing')
        by_event[int(h['event_id'])].append(t)
    timeline = directory/'timeline.json'
    window_end = FIRST+n*SPACING
    if not reanalyze:
        make_timeline(events_path, timeline, SPACING, window_end, first_offset_ns=FIRST,
                      provenance='BGO descriptive study: isolated electron events with explicit source truth evaluation gates')
    modes, records = {}, {}
    for mode, noise in (('noiseless', None), ('noise', ROOT/'examples/single_channel_noise.json')):
        response_prefix, readout_prefix = directory/mode, directory/(mode+'_readout')
        if reanalyze:
            response = json.loads(Path(str(response_prefix)+'_response.json').read_text())
            readout_manifest = json.loads(Path(str(readout_prefix)+'_readout.json').read_text())
        else:
            response = digitize(photons_path, events_path, response_prefix,
                                ROOT/'examples/single_channel_cells.json', Path(str(base)+'_geometry.gdml'),
                                seed=42+index, timeline_path=timeline, noise_path=noise)
            readout_manifest = readout(Path(str(response_prefix)+'_history.csv'), Path(str(response_prefix)+'_response.json'),
                                       ROOT/'examples/single_channel_readout.json', readout_prefix)
        if response['totals']['after_window'] or response['totals']['before_window']:
            raise ValueError('Study lost photon inputs to acquisition clipping')
        if readout_manifest['n_saturated_samples']:
            raise ValueError('Saturated readout: study must explicitly characterize clipping before comparison')
        singles = rows(Path(str(readout_prefix)+'_singles.csv'))
        adc_charge = [0.]*n
        config = readout_manifest['parameters']
        # Integrate fixed source-aligned ROI only for evaluation, independently of trigger gates.
        with Path(str(readout_prefix)+'_waveform.csv').open() as f:
            for s in csv.DictReader(f):
                left, right = float(s['bin_start_ns']), float(s['bin_end_ns'])
                accumulate_roi(adc_charge, left, right,
                               float(s['digitized_mV'])-config['baseline_mV'], config['transimpedance_ohm'])
        event_rows, assigned = [], set()
        for event in range(n):
            source = FIRST+event*SPACING+SOURCE_TIME
            selected, preceding = select_candidates(singles, source)
            assigned.update(s['single_id'] for s in selected)
            edep = float(events[event]['crystal_edep_keV'])
            if not 0 < edep <= energy+1e-6:
                raise ValueError('Invalid crystal energy deposition')
            gate_crosses = sum(float(s['gate_start_ns']) < source-1 or float(s['gate_end_ns']) > source+ROI_LENGTH for s in selected)
            event_rows.append({'event_id': event, 'edep_keV': edep, 'n_arrivals': len(by_event[event]),
                'n_candidates': len(selected), 'first_candidate_delay_ns': min((float(s['time_ns'])-source for s in selected), default=None),
                'preexisting_gate': bool(preceding),
                'unambiguous_first_delay_ns': min((float(s['time_ns'])-source for s in selected), default=None) if not preceding else None,
                'adc_roi_charge_pC': adc_charge[event], 'charge_per_edep_pC_per_keV': adc_charge[event]/edep,
                'selected_gate_charge_pC': math.fsum(float(s['charge_pC']) for s in selected),
                'gates_crossing_evaluation_roi': gate_crosses})
        records[mode] = event_rows
        with (directory/f'{mode}_evaluation.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=event_rows[0]); writer.writeheader(); writer.writerows(event_rows)
        mode_summary = {name: summary(row[name] for row in event_rows if row[name] is not None) for name in
                        ('n_candidates','first_candidate_delay_ns','unambiguous_first_delay_ns','adc_roi_charge_pC','charge_per_edep_pC_per_keV','selected_gate_charge_pC')}
        mode_summary.update({'candidate_window_occupancy': wilson(sum(r['n_candidates']>0 for r in event_rows), n),
                            'preexisting_gate_events': sum(r['preexisting_gate'] for r in event_rows),
                            'outside_evaluation_candidates': len(singles)-len(assigned),
                            'outside_evaluation_duration_ns': window_end-n*(ROI_LENGTH+1),
                            'n_rail_samples': readout_manifest['n_saturated_samples'],
                            'photon_input_sha256': response['inputs']['photons']['sha256'],
                            'transport_identity': response['transport_identity'],
                            'gates_crossing_evaluation_roi': sum(r['gates_crossing_evaluation_roi'] for r in event_rows)})
        modes[mode] = mode_summary
        print(f'{label}: {mode}, ROI charge={mode_summary["adc_roi_charge_pC"]["mean"]:.4f} pC, '
              f'unambiguous delay={mode_summary["unambiguous_first_delay_ns"]["mean"]} ns', flush=True)
    assert modes['noiseless']['photon_input_sha256'] == modes['noise']['photon_input_sha256']
    paired = {}
    for field in ('adc_roi_charge_pC','n_candidates','first_candidate_delay_ns','unambiguous_first_delay_ns'):
        paired[field] = summary(b[field]-a[field] for a,b in zip(records['noiseless'],records['noise'])
                                if a[field] is not None and b[field] is not None)
    edep = [float(e['crystal_edep_keV']) for e in events]
    return {'label': label, 'energy_keV': energy, 'source_local_z_mm': depth, 'events': n,
            'transport_seeds': seeds, 'response_seed': 42+index,
            'edep_keV': summary(edep), 'arrivals_per_event': summary(len(by_event[e]) for e in range(n)),
            'first_arrival_delay_ns': summary(min(v) for v in by_event.values() if v),
            'arrival_time_quantiles_pooled': quantiles(t for v in by_event.values() for t in v),
            'photons_after_evaluation_roi': sum(t >= ROI_LENGTH for v in by_event.values() for t in v),
            'max_arrival_delay_ns': max((t for v in by_event.values() for t in v), default=None),
            'scintillation_per_event': summary(int(e['scintillation_photons']) for e in events),
            'modes': modes, 'paired_noise_minus_noiseless': paired}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('executable', type=Path); p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--events', type=int, default=32)
    p.add_argument('--reanalyze', action='store_true', help='Recompute evaluation from existing unchanged artifacts')
    a = p.parse_args()
    if not 2 <= a.events <= 99:
        p.error('Require 2..99 events per condition (single-readout sample budget)')
    if not a.reanalyze:
        a.output_dir.mkdir(parents=True, exist_ok=False)
    cases = [('depth_minus3',100.,-3.),('center_100keV',100.,0.),('depth_plus3',100.,3.),
             ('center_50keV',50.,0.),('center_200keV',200.,0.)]
    result = {'schema_version': 1, 'purpose': 'Descriptive illustrative BGO response, not experimental validation or DOI estimation',
              'event_spacing_ns': SPACING, 'first_offset_ns': FIRST, 'source_time_ns': SOURCE_TIME,
              'evaluation_roi_ns': [0,ROI_LENGTH], 'candidate_time_roi_ns': [-1,ROI_LENGTH],
              'settings_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                [ROOT/'examples'/s for s in ('single_detector.gdml','single_channel_cells.json','single_channel_noise.json','single_channel_readout.json')]},
              'cases': []}
    if a.reanalyze:
        old = json.loads((a.output_dir/'report.json').read_text())
        if old['settings_sha256'] != result['settings_sha256'] or not old.get('complete') or any(c['events'] != a.events for c in old['cases']):
            raise ValueError('Reanalysis requires matching settings and a complete study with the same event count')
    for index,(label,energy,depth) in enumerate(cases):
        result['cases'].append(run_case(a.executable.resolve(),a.output_dir.resolve(),label,energy,depth,a.events,index,a.reanalyze))
        (a.output_dir/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    result['complete'] = True
    (a.output_dir/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
