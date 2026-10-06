#!/usr/bin/env python3
"""Controlled timing/noise ablations of retained BGO transport; truth for evaluation only."""
import argparse
import csv
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from acquisition import prepare_acquisition, simulate_acquisition
from fixed_gate import ADCTrace, GateConfig
from readout import ReadoutConfig, shape, extract_singles
from sipm_cells import CellConfig, Photon, simulate_event
from sipm_noise import NoiseConfig, simulate_noise
from bgo_response import rows, summary


class DrawStream:
    """One preassigned PDE draw per photon, independent of acquisition ordering."""
    def __init__(self, values):
        self.values = iter(values)
        self.used = 0

    def random(self):
        self.used += 1
        return next(self.values)


def assigned_draws(arrivals, seed):
    rng = random.Random(seed)
    return {(e, p.track_id): rng.random() for e in sorted(arrivals)
            for p in sorted(arrivals[e], key=lambda p: (p.time_ns, p.track_id))}


def evaluate(singles, sources, holdoff, crossings=None):
    """Disjoint source-time slots; occupancy is not a truth-matched efficiency."""
    events = []
    for i, source in enumerate(sources):
        end = min(source+3000, sources[i+1]-1 if i+1 < len(sources) else math.inf)
        selected = [s for s in singles if source-1 <= s['time_ns'] < end]
        blockers = [s for s in singles if s['time_ns'] < source-1 and s['time_ns']+holdoff > source]
        prompt = any(s['time_ns'] < source+100 for s in selected)
        raw_prompt = any(source-1 <= t < min(source+100, end) for t in crossings) if crossings is not None else None
        events.append({'event_index': i, 'source_ns': source, 'slot_end_ns': end,
                       'n_candidates': len(selected), 'blocked_at_source': bool(blockers),
                       'blocker_time_ns': blockers[-1]['time_ns'] if blockers else None,
                       'prompt_candidate': prompt, 'raw_prompt_crossing': raw_prompt,
                       'first_delay_ns': selected[0]['time_ns']-source if selected else None})
    metrics = {'events': len(events), 'total_candidates': len(singles),
               'blocked_events': sum(e['blocked_at_source'] for e in events),
               'prompt_occupied_events': sum(e['prompt_candidate'] for e in events),
               'empty_slots': sum(e['n_candidates'] == 0 for e in events),
               'multiple_candidate_slots': sum(e['n_candidates'] > 1 for e in events),
               'candidates_per_slot': summary(e['n_candidates'] for e in events)}
    if crossings is not None:
        metrics['no_raw_prompt_crossing_events'] = sum(not e['raw_prompt_crossing'] for e in events)
        metrics['raw_prompt_crossing_but_no_accepted_prompt'] = sum(e['raw_prompt_crossing'] and not e['prompt_candidate'] for e in events)
    return metrics, events


def write_csv(path, records):
    if not records:
        return
    with path.open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)


def record_trace(target, label, history, sources, end, config, gate):
    samples = shape([(h['time_ns'], h['charge_pC']) for h in history], 0, end, config)
    trace = ADCTrace(samples, config)
    singles = trace.extract(gate)
    metrics, events = evaluate(singles, sources, gate.holdoff_ns, trace.crossings)
    adc_hash = hashlib.sha256()
    for s in samples:
        adc_hash.update(s['adc_code'].to_bytes(4, 'little'))
    metrics.update({'label': label, 'n_rail_samples': sum(s['saturated'] for s in samples),
                    'truncated_candidates': sum(s['truncated'] for s in singles),
                    'truncated_candidates_in_source_slots': sum(s['truncated'] for s in singles if any(t-1 <= s['time_ns'] < min(t+3000, sources[i+1]-1 if i+1 < len(sources) else math.inf) for i,t in enumerate(sources))),
                    'adc_code_sha256': adc_hash.hexdigest(),
                    'avalanche_charge_pC': math.fsum(h['charge_pC'] for h in history),
                    'adc_full_record_charge_pC': trace.areas[-1]/config.transimpedance_ohm})
    write_csv(target/(label+'_singles.csv'), singles)
    write_csv(target/(label+'_evaluation.csv'), events)
    write_csv(target/(label+'_history.csv'), history)
    return metrics, events


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('study', type=Path, help='Completed bgo_response study directory')
    p.add_argument('--output-dir', type=Path, required=True)
    a = p.parse_args()
    base = json.loads((a.study/'report.json').read_text())
    if not base.get('complete'):
        raise ValueError('Input study incomplete')
    case = next(c for c in base['cases'] if c['label'] == 'center_100keV')
    directory = a.study/case['label']
    response = json.loads((directory/'noiseless_response.json').read_text())
    readout = json.loads((directory/'noiseless_readout_readout.json').read_text())
    noise_manifest = json.loads((directory/'noise_response.json').read_text())
    config = CellConfig.from_dict(response['parameters'])
    adc = ReadoutConfig.from_dict(readout['parameters'])
    # Use retained study parameters, not potentially edited example files.
    noise = NoiseConfig.from_dict(noise_manifest['noise']['parameters'])
    gate = GateConfig(1, 'Controlled cause separation: fixed 1 us integration, 1.504 us holdoff', 1000, 4, 1504)
    photons = directory/'transport_run0_photons.csv'
    if hashlib.sha256(photons.read_bytes()).hexdigest() != response['inputs']['photons']['sha256']:
        raise ValueError('Transport photon hash mismatch')
    events = sorted(rows(directory/'transport_run0_events.csv'), key=lambda r: int(r['event_id']))
    identity = response['transport_identity']
    arrivals = {int(e['event_id']): [] for e in events}
    for r in rows(photons):
        if (r['dataset_id'], int(r['run_id'])) != (identity['dataset_id'], identity['run_id']):
            raise ValueError('Photon identity mismatch')
        arrivals[int(r['event_id'])].append(Photon(int(r['track_id']), float(r['time_ns']),
                                                  float(r['local_x_mm']), float(r['local_y_mm'])))
    for e in events:
        if (e['dataset_id'], int(e['run_id'])) != (identity['dataset_id'], identity['run_id']):
            raise ValueError('Event identity mismatch')
        if len(arrivals[int(e['event_id'])]) != int(e['n_arrivals']):
            raise ValueError('Photon count mismatch')
    seed, first, source_time = case['response_seed'], base['first_offset_ns'], base['source_time_ns']
    draws = assigned_draws(arrivals, seed)
    isolated, isolated_metrics = {}, []
    a.output_dir.mkdir(parents=True, exist_ok=False)
    for e, photons_e in arrivals.items():
        ordered = sorted(photons_e, key=lambda p: (p.time_ns, p.track_id))
        state = simulate_event(config, photons_e, DrawStream(draws[e, p.track_id] for p in ordered))
        isolated[e] = state.avalanches
        samples = shape([(first+h.time_ns, h.charge_pC) for h in state.avalanches], 0, first+6000, adc)
        trace = ADCTrace(samples, adc)
        fixed, legacy = trace.extract(gate), extract_singles(samples, adc)
        source = first+source_time
        selected = [s for s in fixed if source-1 <= s['time_ns'] < source+3000]
        isolated_metrics.append({'event_id': e, 'legacy_candidates': len(legacy),
                                 'fixed_candidates': len(fixed),
                                 'first_gate_charge_fraction': selected[0]['charge_pC']/(trace.areas[-1]/adc.transimpedance_ohm) if selected else None,
                                 'avalanche_charge_pC': math.fsum(h.charge_pC for h in state.avalanches)})
    write_csv(a.output_dir/'isolated_evaluation.csv', isolated_metrics)
    reference_charge = math.fsum(m['avalanche_charge_pC'] for m in isolated_metrics)
    report = {'schema_version': 1, 'purpose': 'Descriptive controlled ablations; not calibrated detection efficiency',
              'source_report_sha256': hashlib.sha256((a.study/'report.json').read_bytes()).hexdigest(),
              'photon_sha256': response['inputs']['photons']['sha256'], 'transport_identity': identity,
              'response_seed': seed, 'source_time_ns': source_time,
              'parameters': {'cells': asdict(config), 'noise': asdict(noise), 'readout': asdict(adc), 'gate': asdict(gate)},
              'pde_draw_policy': 'Canonical event/time/track draws, permuted to acquisition time order; one per photon',
              'isolated': {k: summary(m[k] for m in isolated_metrics if m[k] is not None) for k in isolated_metrics[0] if k != 'event_id'},
              'cases': []}
    for spacing in (10000, 3000, 1500, 500):
        offsets = {e: first+i*spacing for i, e in enumerate(arrivals)}
        end = max(offsets.values())+6000
        sources = [offsets[e]+source_time for e in arrivals]
        timeline = {'schema_version': 1, 'provenance': 'Controlled equal-spacing source timing ablation',
                    'transport_identity': identity, 'state_start_ns': 0, 'window_start_ns': 0, 'window_end_ns': end,
                    'event_offsets': [{'event_id': e, 'offset_ns': t} for e, t in offsets.items()]}
        target = a.output_dir/f'spacing_{spacing}ns'
        target.mkdir()
        (target/'timeline.json').write_text(json.dumps(timeline, indent=2)+'\n')
        ordered, _, _, _ = prepare_acquisition(config, arrivals, timeline, (identity['dataset_id'], identity['run_id']))
        if any(t >= end for t, *_ in ordered):
            raise ValueError('Acquisition clips photon arrivals')
        def stream():
            return DrawStream(draws[e, track] for _, e, track, _, _ in ordered)
        replay = [{'event_id': e, 'track_id': h.track_id, 'root_event_id': e, 'cause': 'photon',
                   'time_ns': offsets[e]+h.time_ns, 'charge_pC': h.charge_pC} for e in arrivals for h in isolated[e]]
        history = []
        clean_rng, noise_rng = stream(), stream()
        responses, excluded, _ = simulate_acquisition(config, arrivals, clean_rng, timeline,
                                                      (identity['dataset_id'], identity['run_id']), history)
        _, noise_excluded, _, noise_history, details = simulate_noise(config, arrivals, noise_rng, timeline,
                                                    (identity['dataset_id'], identity['run_id']), noise, seed)
        if clean_rng.used != len(draws) or noise_rng.used != len(draws):
            raise ValueError('PDE draw correspondence lost')
        if any(v['after_window'] or v['before_window'] for v in [*excluded.values(), *noise_excluded.values()]):
            raise ValueError('Acquisition clips photon inputs')
        entry = {'spacing_ns': spacing, 'input_rate_hz': 1e9/spacing, 'modes': [],
                 'shared_cell_charge_loss_fraction': 1-math.fsum(h['charge_pC'] for h in history)/reference_charge,
                 'noiseless_unavailable_photons': sum(r.n_unavailable for r in responses.values()),
                 'noise_details': details}
        histories = [('isolated_pulses_replayed', replay), ('shared_cells_no_noise', history), ('full_noise', noise_history)]
        if spacing == 10000:
            # Conditional readout ablation: preserve realized signal response, remove dark-rooted avalanches.
            histories.append(('full_noise_without_dark_lineage', [h for h in noise_history if h['root_event_id'] is not None]))
        mode_events = {}
        for label, h in histories:
            metrics, event_metrics = record_trace(target, label, h, sources, end, adc, gate)
            entry['modes'].append(metrics)
            mode_events[label] = event_metrics
        if spacing == 10000:
            entry['dark_lineage_ablation'] = {
                'blocked_to_unblocked': sum(x['blocked_at_source'] and not y['blocked_at_source'] for x, y in zip(mode_events['full_noise'], mode_events['full_noise_without_dark_lineage'])),
                'unblocked_to_blocked': sum(not x['blocked_at_source'] and y['blocked_at_source'] for x, y in zip(mode_events['full_noise'], mode_events['full_noise_without_dark_lineage']))}
        report['cases'].append(entry)
        (a.output_dir/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        print(spacing, [(m['label'], m['blocked_events'], m['prompt_occupied_events']) for m in entry['modes']], flush=True)
    report['complete'] = True
    (a.output_dir/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
