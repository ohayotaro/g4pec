#!/usr/bin/env python3
"""Truth-independent, all-pairs coincidence selection from acquisition singles."""
import argparse
from bisect import bisect_left
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path

from digitize_cells import csv_rows, unique_json, reject_constant
from sipm_cells import keys, number


FIELDS = ('coincidence_id', 'detector_a', 'single_id_a', 'channel_a', 'time_a_ns', 'charge_a_pC',
          'detector_b', 'single_id_b', 'channel_b', 'time_b_ns', 'charge_b_pC', 'delta_ns',
          'matches_a', 'matches_b', 'ambiguous')


def parse_json(data):
    return json.loads(data, object_pairs_hook=unique_json, parse_constant=reject_constant)


def nonempty(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')
    return value


def validate_config(config):
    keys(config, ('schema_version', 'provenance', 'clock_id', 'half_window_ns', 'detector_pairs',
                  'min_charge_pC', 'max_charge_pC', 'reject_truncated', 'reject_saturated',
                  'max_pairs', 'inputs'), 'coincidence config')
    if type(config['schema_version']) is not int or config['schema_version'] != 1:
        raise ValueError('Unsupported coincidence schema')
    for k in ('provenance', 'clock_id'):
        nonempty(config[k], k)
    number(config['half_window_ns'], 'half_window_ns', strictly_positive=True)
    low = number(config['min_charge_pC'], 'min_charge_pC', minimum=0)
    if config['max_charge_pC'] is not None and number(config['max_charge_pC'], 'max_charge_pC', minimum=0) < low:
        raise ValueError('max_charge_pC must be >= min_charge_pC')
    for k in ('reject_truncated', 'reject_saturated'):
        if type(config[k]) is not bool:
            raise ValueError(f'{k} must be boolean')
    if type(config['max_pairs']) is not int or not 1 <= config['max_pairs'] <= 2_000_000:
        raise ValueError('max_pairs must be an integer in [1, 2000000]')
    if not isinstance(config['inputs'], list) or len(config['inputs']) < 2:
        raise ValueError('At least two detector input streams are required')
    detectors = set()
    for item in config['inputs']:
        keys(item, ('detector_id', 'singles', 'manifest', 'time_offset_ns'), 'input stream')
        for k in ('detector_id', 'singles', 'manifest'):
            nonempty(item[k], k)
        if item['detector_id'] in detectors:
            raise ValueError('One input stream per detector is required; aggregate channels upstream')
        detectors.add(item['detector_id'])
        number(item['time_offset_ns'], 'time_offset_ns')
    if not isinstance(config['detector_pairs'], list) or not config['detector_pairs']:
        raise ValueError('At least one allowed detector pair is required')
    pairs = set()
    for pair in config['detector_pairs']:
        if not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(d, str) or d not in detectors for d in pair) or pair[0] == pair[1]:
            raise ValueError('Pairs must name two different configured detectors')
        key = tuple(sorted(pair))
        if key in pairs:
            raise ValueError('Duplicate/reversed detector pair')
        pairs.add(key)
    return config


def match_pairs(streams, detector_pairs, half_window_ns, max_pairs):
    """Keep every allowed pair with -W <= t_b-t_a < W; IDs are stream-local."""
    result = []
    ordered = {d: sorted(rows, key=lambda r: (r['time_ns'], r['single_id'])) for d, rows in streams.items()}
    for detector_a, detector_b in sorted(detector_pairs):
        right = ordered[detector_b]
        times = [r['time_ns'] for r in right]
        for a in ordered[detector_a]:
            lower, upper = a['time_ns']-half_window_ns, a['time_ns']+half_window_ns
            if not math.isfinite(lower) or not math.isfinite(upper) or lower == a['time_ns'] or upper == a['time_ns']:
                raise ValueError('Coincidence window overflows or is below clock precision')
            for index in range(bisect_left(times, math.nextafter(lower, -math.inf)),
                               bisect_left(times, math.nextafter(upper, math.inf))):
                b = right[index]
                if not -half_window_ns <= b['time_ns']-a['time_ns'] < half_window_ns:
                    continue
                if len(result) >= max_pairs:
                    raise ValueError('Coincidence pair budget exceeded; no partial output is valid')
                result.append({'detector_a': detector_a, 'single_id_a': a['single_id'], 'channel_a': a['channel_path'],
                               'time_a_ns': a['time_ns'], 'charge_a_pC': a['charge_pC'],
                               'detector_b': detector_b, 'single_id_b': b['single_id'], 'channel_b': b['channel_path'],
                               'time_b_ns': b['time_ns'], 'charge_b_pC': b['charge_pC'],
                               'delta_ns': b['time_ns']-a['time_ns']})
    result.sort(key=lambda r: (r['time_a_ns'], r['time_b_ns'], r['detector_a'], r['detector_b'], r['single_id_a'], r['single_id_b']))
    counts = Counter((r['detector_'+s], r['single_id_'+s]) for r in result for s in ('a','b'))
    for i, row in enumerate(result, 1):
        row['coincidence_id'] = i
        row['matches_a'] = counts[row['detector_a'], row['single_id_a']]
        row['matches_b'] = counts[row['detector_b'], row['single_id_b']]
        row['ambiguous'] = row['matches_a'] > 1 or row['matches_b'] > 1
    return result


def select(config_path, prefix):
    config_path, prefix = Path(config_path), Path(prefix)
    outputs = [Path(str(prefix)+'_coincidences.csv'), Path(str(prefix)+'_coincidences.json')]
    if any(p.exists() or p.is_symlink() for p in outputs):
        raise FileExistsError('Coincidence output already exists')
    raw_config = config_path.read_bytes()
    config = validate_config(parse_json(raw_config))
    streams, inputs, used_paths = {}, {}, set()
    shared_context, context_mode = None, None
    for item in config['inputs']:
        detector = item['detector_id']
        files = {k: (config_path.parent/item[k]).resolve() for k in ('singles', 'manifest')}
        if any(path in used_paths for path in files.values()):
            raise ValueError('An input file cannot be reused as another detector')
        used_paths.update(files.values())
        data = {k: path.read_bytes() for k, path in files.items()}
        manifest = parse_json(data['manifest'])
        if not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1 or manifest.get('time_basis') != 'acquisition_relative_ns':
            raise ValueError('Require schema-1 acquisition readout manifests')
        is_head = manifest.get('model') == 'two_sipm_head_singles_v1'
        context_key = 'response_head' if is_head else 'response_dataset'
        if ('response_head' in manifest) != is_head or (is_head and 'response_dataset' in manifest):
            raise ValueError('Invalid head stream context')
        context = manifest.get(context_key)
        mode = 'head' if is_head else ('channel' if context is not None else 'legacy')
        if context_mode is not None and context_mode != mode:
            raise ValueError('Cannot mix portable-dataset, head and legacy input streams')
        context_mode = mode
        if is_head and context is None:
            raise ValueError('Head stream requires dataset context')
        if context is not None:
            keys(context, ('dataset_id','channel_ids' if is_head else 'channel_id','detector_id','geometry_sha256','clock_id'), 'response dataset context')
            if is_head:
                ids=context['channel_ids']
                if not isinstance(ids,list) or len(ids)!=2 or any(not isinstance(c,str) or not c.strip() for c in ids) or len(set(ids))!=2:
                    raise ValueError('Invalid head channel IDs')
                if any(set(ids) & set(v.get('response_head',{}).get('channel_ids',[])) for v in inputs.values()):
                    raise ValueError('Heads cannot reuse SiPM channels')
            if context['detector_id'] != detector or context['clock_id'] != config['clock_id']:
                raise ValueError('Configured detector/clock does not match response dataset')
            signature = tuple(context[k] for k in ('dataset_id','geometry_sha256','clock_id'))
            if shared_context is not None and shared_context != signature:
                raise ValueError('Coincidence streams must share response dataset, geometry and clock')
            shared_context = signature
        channel = nonempty(manifest.get('channel_path'), 'manifest channel_path')
        start, end = (number(manifest.get(k), k, **({} if is_head else {'minimum':0})) for k in ('window_start_ns', 'window_end_ns'))
        if start >= end or type(manifest.get('n_singles')) is not int or manifest['n_singles'] < 0:
            raise ValueError('Invalid readout window or n_singles')
        digest = hashlib.sha256(data['singles']).hexdigest()
        expected = manifest.get('output_hashes', {}).get('singles_sha256')
        if is_head and expected is None:
            raise ValueError('Head singles require a content hash')
        if expected is not None and digest != expected:
            raise ValueError('Singles hash disagrees with readout manifest')
        accepted, seen, rejected = [], set(), Counter()
        required = ('single_id', 'channel_path', 'time_ns', 'charge_pC', 'n_saturated', 'truncated')
        for row in csv_rows(data['singles'], required, 'singles'):
            sid = int(row['single_id'])
            t = number(float(row['time_ns']), 'single time')
            q = number(float(row['charge_pC']), 'single charge')
            saturated = int(row['n_saturated'])
            if sid <= 0 or sid in seen or row['channel_path'] != channel or not start <= t < end or saturated < 0 or row['truncated'] not in ('True','False'):
                raise ValueError('Invalid/duplicate single ID, channel, time or quality fields')
            seen.add(sid)
            corrected = t+item['time_offset_ns']
            if not math.isfinite(corrected):
                raise ValueError('Corrected time overflow')
            failures = []
            if q < config['min_charge_pC'] or (config['max_charge_pC'] is not None and q > config['max_charge_pC']):
                failures.append('charge')
            if config['reject_truncated'] and row['truncated'] == 'True':
                failures.append('truncated')
            if config['reject_saturated'] and saturated:
                failures.append('saturated')
            if failures:
                rejected.update(failures)
                continue
            accepted.append({'single_id': sid, 'channel_path': channel, 'time_ns': corrected, 'charge_pC': q})
        if len(seen) != manifest['n_singles']:
            raise ValueError('Singles count disagrees with readout manifest')
        streams[detector] = accepted
        inputs[detector] = {'files': {k: {'path': str(files[k]), 'sha256': hashlib.sha256(data[k]).hexdigest()} for k in files},
                            'transport_identity': manifest.get('transport_identity'), 'channel_path': channel,
                            'time_offset_ns': item['time_offset_ns'], 'n_input': len(seen), 'n_accepted': len(accepted),
                            'n_rejected': len(seen)-len(accepted), 'rejection_reasons_nonexclusive': dict(rejected),
                            'singles_hash_verified': expected is not None}
        if context is not None:
            inputs[detector][context_key] = context
    pairs = match_pairs(streams, config['detector_pairs'], config['half_window_ns'], config['max_pairs'])
    report = {'schema_version': 1, 'model': 'all_pairs_coincidence_v1', 'parameters': config,
              'config_sha256': hashlib.sha256(raw_config).hexdigest(), 'inputs': inputs,
              'clock_contract': 'User-declared common clock; corrected time = input time + time_offset_ns',
              'window_convention': '-half_window_ns <= time_b_ns - time_a_ns < half_window_ns; orientation from detector_pairs',
              'charge_convention': 'Inclusive bounds in pC; no energy calibration is inferred',
              'multiplicity_policy': 'Keep all pairs; matches count across all allowed detector pairs',
              'member_key': '(detector_id, single_id) scoped to the recorded input file hashes',
              'truth_policy': 'Event IDs, track IDs, ancestry and transport identity are not selection criteria',
              'n_coincidences': len(pairs), 'n_ambiguous_pairs': sum(r['ambiguous'] for r in pairs)}
    prefix.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        with outputs[0].open('x', newline='') as f:
            created.append(outputs[0])
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader(); writer.writerows(pairs)
        report['output_hashes'] = {'coincidences_sha256': hashlib.sha256(outputs[0].read_bytes()).hexdigest()}
        with outputs[1].open('x') as f:
            created.append(outputs[1])
            json.dump(report, f, indent=2, allow_nan=False); f.write('\n')
    except Exception:
        for path in created:
            path.unlink()
        raise
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config', type=Path); p.add_argument('output_prefix', type=Path)
    a = p.parse_args()
    try:
        result = select(a.config, a.output_prefix)
    except (ValueError, OSError, OverflowError) as error:
        p.exit(1, f'Coincidence selection failed: {error}\n')
    print(json.dumps({'n_coincidences': result['n_coincidences'], 'n_ambiguous_pairs': result['n_ambiguous_pairs']}))


if __name__ == '__main__':
    main()
