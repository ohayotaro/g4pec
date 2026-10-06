#!/usr/bin/env python3
"""Area-normalized pulse shaping, bin-average ADC sampling and truth-free singles."""
import argparse
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

from digitize_cells import csv_rows, reject_constant, unique_json
from sipm_cells import keys, number
from fixed_gate import ADCTrace, GateConfig


@dataclass(frozen=True)
class ReadoutConfig:
    schema_version: int
    provenance: str
    rise_time_ns: float
    fall_time_ns: float
    transimpedance_ohm: float
    sample_interval_ns: float
    baseline_mV: float
    adc_lsb_mV: float
    adc_bits: int
    threshold_mV: float
    release_mV: float
    pre_samples: int
    post_samples: int
    max_samples: int

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Unsupported readout schema")
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            raise ValueError("Readout provenance is required")
        for name in ('rise_time_ns', 'fall_time_ns', 'transimpedance_ohm', 'sample_interval_ns',
                     'baseline_mV', 'adc_lsb_mV', 'threshold_mV', 'release_mV'):
            object.__setattr__(self, name, number(getattr(self, name), name, minimum=0,
                strictly_positive=name not in ('baseline_mV', 'release_mV')))
        if self.fall_time_ns < 1.01*self.rise_time_ns:
            raise ValueError("Require fall_time_ns >= 1.01 * rise_time_ns for stable shaping")
        for name in ('adc_bits', 'pre_samples', 'post_samples', 'max_samples'):
            if type(getattr(self, name)) is not int:
                raise ValueError(f'{name} must be an integer')
        if not 1 <= self.adc_bits <= 24 or min(self.pre_samples, self.post_samples) < 0 or not 1 <= self.max_samples <= 2_000_000:
            raise ValueError("Invalid ADC bits, gate padding or sample limit")
        full_scale = ((1 << self.adc_bits)-1)*self.adc_lsb_mV
        if not math.isfinite(full_scale) or not self.release_mV < self.threshold_mV < full_scale-self.baseline_mV:
            raise ValueError("Require release < threshold < ADC headroom")

    @classmethod
    def from_dict(cls, data):
        keys(data, cls.__dataclass_fields__, 'readout configuration')
        return cls(**data)


def shape(pulses, start, end, config):
    """Pulses are only (time_ns, charge_pC), including pre-window history."""
    start, end = number(start, 'start', minimum=0), number(end, 'end', minimum=0)
    if end <= start:
        raise ValueError('Empty waveform window')
    count_float = (end-start)/config.sample_interval_ns
    if not math.isfinite(count_float) or count_float > config.max_samples:
        raise ValueError('Waveform sample budget exceeded')
    count = math.ceil(count_float)
    pulses = sorted((number(t, 'pulse time', minimum=0), number(q, 'charge', strictly_positive=True))
                    for t, q in pulses)
    if any(t >= end for t, _ in pulses):
        raise ValueError('Pulse history must end before the acquisition window end')
    rise, fall = config.rise_time_ns, config.fall_time_ns
    states, cursor = [0., 0.], 0
    while cursor < len(pulses) and pulses[cursor][0] < start:
        t, q = pulses[cursor]
        for j, tau in enumerate((rise, fall)):
            states[j] += q*math.exp(-(start-t)/tau)
        cursor += 1
    samples = []
    for i in range(count):
        left = start+i*config.sample_interval_ns
        right = min(end, start+(i+1)*config.sample_interval_ns)
        dt = right-left
        if dt <= 0:
            raise ValueError('Sampling interval lost to floating-point precision')
        areas = [states[j]*tau*(-math.expm1(-dt/tau)) for j, tau in enumerate((rise, fall))]
        states = [states[j]*math.exp(-dt/tau) for j, tau in enumerate((rise, fall))]
        while cursor < len(pulses) and pulses[cursor][0] < right:
            t, q = pulses[cursor]
            delta = right-t
            for j, tau in enumerate((rise, fall)):
                areas[j] += q*tau*(-math.expm1(-delta/tau))
                states[j] += q*math.exp(-delta/tau)
            cursor += 1
        signal = config.transimpedance_ohm*(areas[1]-areas[0])/(fall-rise)/dt
        if not math.isfinite(signal) or signal < -1e-9:
            raise ValueError('Invalid shaped waveform value')
        analog = config.baseline_mV+max(0, signal)
        if not math.isfinite(analog):
            raise ValueError('Analog voltage overflow')
        high = (1 << config.adc_bits)-1
        scaled = analog/config.adc_lsb_mV
        if not math.isfinite(scaled):
            raise ValueError('ADC conversion overflow')
        code = min(high, max(0, math.floor(scaled+.5)))
        samples.append({'sample_id': i, 'bin_start_ns': left, 'bin_end_ns': right,
                        'time_ns': left+dt/2, 'analog_mV': analog, 'adc_code': code,
                        'digitized_mV': code*config.adc_lsb_mV, 'saturated': code in (0, high)})
    return samples


def extract_singles(samples, config):
    """Consumes ADC samples only; no avalanche, event, cause or ancestry input."""
    if not samples:
        return []
    signals = [s['adc_code']*config.adc_lsb_mV-config.baseline_mV for s in samples]
    intervals, active = [], None
    for i, value in enumerate(signals):
        if active is None and value >= config.threshold_mV:
            if i == 0:
                trigger = samples[i]['time_ns']
                left_clipped = True
            else:
                fraction = (config.threshold_mV-signals[i-1])/(value-signals[i-1])
                trigger = samples[i-1]['time_ns'] + fraction*(samples[i]['time_ns']-samples[i-1]['time_ns'])
                left_clipped = False
            active = (i, trigger, left_clipped)
        if active is not None and value <= config.release_mV:
            intervals.append((*active, i, False))
            active = None
    if active is not None:
        intervals.append((*active, len(samples)-1, True))
    gates = []
    for first, trigger, left_clipped, last, right_clipped in intervals:
        low, high = max(0, first-config.pre_samples), min(len(samples)-1, last+config.post_samples)
        truncated = left_clipped or right_clipped or first-config.pre_samples < 0 or last+config.post_samples >= len(samples)
        if gates and low <= gates[-1]['high']:
            gate = gates[-1]
            gate['high'] = max(gate['high'], high)
            gate['n_crossings'] += 1
            gate['truncated'] |= truncated
        else:
            gates.append({'low': low, 'high': high, 'time_ns': trigger, 'n_crossings': 1, 'truncated': truncated})
    result = []
    for gate in gates:
        low, high = gate['low'], gate['high']
        charge = math.fsum(signals[i]*(samples[i]['bin_end_ns']-samples[i]['bin_start_ns'])
                           for i in range(low, high+1))/config.transimpedance_ohm
        if not math.isfinite(charge):
            raise ValueError('Integrated charge overflow')
        result.append({'single_id': len(result)+1, 'time_ns': gate['time_ns'],
                       'gate_start_ns': samples[low]['bin_start_ns'],
                       'gate_end_ns': samples[high]['bin_end_ns'], 'charge_pC': charge,
                       'peak_mV': max(signals[low:high+1]), 'n_crossings': gate['n_crossings'],
                       'n_saturated': sum(s['saturated'] for s in samples[low:high+1]),
                       'truncated': gate['truncated']})
    return result


def readout(history_path, response_path, config_path, prefix, gate_path=None):
    paths = [Path(str(prefix)+suffix) for suffix in ('_waveform.csv', '_singles.csv', '_readout.json')]
    if any(p.exists() or p.is_symlink() for p in paths):
        raise FileExistsError('Readout output exists')
    inputs = {k: Path(v) for k, v in (('history', history_path), ('response', response_path), ('config', config_path))}
    if gate_path is not None:
        inputs['gate'] = Path(gate_path)
    data = {k: p.read_bytes() for k, p in inputs.items()}
    def parse(key):
        return json.loads(data[key], object_pairs_hook=unique_json, parse_constant=reject_constant)
    config = ReadoutConfig.from_dict(parse('config'))
    response = parse('response')
    if response.get('schema_version') != 1 or response.get('time_basis') != 'acquisition_relative_ns':
        raise ValueError('Readout requires an acquisition response manifest')
    recorded_hash = response.get('output_hashes', {}).get('history_sha256')
    if recorded_hash is not None and recorded_hash != hashlib.sha256(data['history']).hexdigest():
        raise ValueError('History hash disagrees with response manifest')
    acquisition = response['acquisition']
    state_start, start, end = (number(acquisition[k], k, minimum=0) for k in
                              ('state_start_ns', 'window_start_ns', 'window_end_ns'))
    if not state_start <= start < end:
        raise ValueError('Invalid acquisition window')
    channel = response['parameters']['channel_path']
    pulses, ids, observed_count = [], set(), 0
    for row in csv_rows(data['history'], ('avalanche_id', 'time_ns', 'charge_pC', 'observed'), 'history'):
        aid = int(row['avalanche_id'])
        t, q = number(float(row['time_ns']), 'time_ns', minimum=state_start), number(float(row['charge_pC']), 'charge_pC', strictly_positive=True)
        if aid <= 0 or aid in ids or t >= end or row['observed'] not in ('True', 'False'):
            raise ValueError('Invalid or duplicate avalanche history row')
        if (row['observed'] == 'True') != (start <= t < end):
            raise ValueError('History observation flag disagrees with acquisition window')
        ids.add(aid); pulses.append((t, q)); observed_count += t >= start
    if observed_count != response['totals']['avalanches']:
        raise ValueError('History observed count disagrees with response manifest')
    expected_history = (sum(c['detected'] for c in response['noise']['counts_including_warmup'].values())
                        if 'noise' in response else observed_count+response['warmup_counts']['detected'])
    if len(pulses) != expected_history:
        raise ValueError('Incomplete warmup history')
    samples = shape(pulses, start, end, config)
    gate = GateConfig.from_dict(parse('gate')) if gate_path is not None else None
    singles = ADCTrace(samples,config).extract(gate) if gate is not None else extract_singles(samples, config)
    for s in singles:
        s['channel_path'] = channel
    manifest = {'schema_version': 1, 'model': 'double_exponential_bin_average_adc_v1',
                'parameters': asdict(config), 'channel_path': channel,
                'transport_identity': response.get('transport_identity'),
                'time_basis': 'acquisition_relative_ns', 'window_start_ns': start, 'window_end_ns': end,
                'pulse_history_count': len(pulses), 'n_samples': len(samples), 'n_singles': len(singles),
                'n_saturated_samples': sum(s['saturated'] for s in samples),
                'charge_definition': 'baseline-subtracted ADC gate area divided by transimpedance; finite gates',
                'trigger_definition': 'hysteretic leading edge, interpolated between bin centers',
                'inputs': {k: {'path': str(p.resolve()), 'sha256': hashlib.sha256(data[k]).hexdigest()} for k,p in inputs.items()}}
    if 'response_dataset' in response:
        manifest['response_dataset'] = response['response_dataset']
    if gate is not None:
        manifest['fixed_gate'] = asdict(gate)
        manifest['trigger_definition'] = 'hysteretic crossings; fixed non-extending holdoff from accepted trigger'
        manifest['charge_definition'] = 'ADC area over [trigger-pretrigger, trigger+integration), clipped to acquisition'
    Path(prefix).parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for path, header, rows in (
            (paths[0], ('sample_id','bin_start_ns','bin_end_ns','time_ns','analog_mV','adc_code','digitized_mV','saturated'), samples),
            (paths[1], ('single_id','channel_path','time_ns','gate_start_ns','gate_end_ns','charge_pC','peak_mV','n_crossings','n_saturated','truncated'), singles)):
            with path.open('x', newline='', encoding='utf-8') as stream:
                created.append(path)
                writer = csv.DictWriter(stream, fieldnames=header)
                writer.writeheader(); writer.writerows(rows)
        manifest['output_hashes'] = {'singles_sha256': hashlib.sha256(paths[1].read_bytes()).hexdigest()}
        with paths[2].open('x', encoding='utf-8') as stream:
            created.append(paths[2]); json.dump(manifest, stream, indent=2, allow_nan=False); stream.write('\n')
    except Exception:
        for path in created:
            path.unlink()
        raise
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('history', type=Path); p.add_argument('response', type=Path); p.add_argument('output_prefix', type=Path)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--gate-config', type=Path, help='Optional fixed integration/holdoff configuration')
    a = p.parse_args()
    try:
        result = readout(a.history, a.response, a.config, a.output_prefix, a.gate_config)
    except (ValueError, OSError, KeyError, TypeError, OverflowError) as error:
        p.exit(1, f'Readout failed: {error}\n')
    print(json.dumps({k: result[k] for k in ('n_samples','n_singles','n_saturated_samples')}))


if __name__ == '__main__':
    main()
