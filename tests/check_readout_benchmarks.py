"""Analytical time-walk and finite-gate charge oracles, plus pileup characterization."""
import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from readout import ReadoutConfig, extract_singles, shape


def cdf(age, c):
    if age <= 0:
        return 0.
    r, f = c.rise_time_ns, c.fall_time_ns
    return 1-(f*math.exp(-age/f)-r*math.exp(-age/r))/(f-r)


def voltage(age, q, c):
    return q*c.transimpedance_ohm*(math.exp(-age/c.fall_time_ns)-math.exp(-age/c.rise_time_ns))/(c.fall_time_ns-c.rise_time_ns)


def crossing(q, c):
    r, f = c.rise_time_ns, c.fall_time_ns
    peak_time = math.log(f/r)/(1/r-1/f)
    if voltage(peak_time, q, c) < c.threshold_mV:
        return None
    low, high = 0., peak_time
    for _ in range(90):
        mid = (low+high)/2
        if voltage(mid, q, c) < c.threshold_mV:
            low = mid
        else:
            high = mid
    return (low+high)/2


def gate_check(pulses, singles, c):
    exact, measured, duration = 0., 0., 0.
    last = -math.inf
    for s in singles:
        a, b = s['gate_start_ns'], s['gate_end_ns']
        assert a >= last, 'Gates double-count samples'
        last = b
        exact += sum(q*(cdf(b-t, c)-cdf(a-t, c)) for t,q in pulses)
        measured += s['charge_pC']
        duration += b-a
    tolerance = .5*c.adc_lsb_mV*duration/c.transimpedance_ohm + 1e-10
    if not any(s['n_saturated'] for s in singles):
        assert abs(measured-exact) <= tolerance, (measured, exact, tolerance)
    return {'measured_charge_pC': measured, 'analytic_gate_charge_pC': exact,
            'quantization_bound_pC': tolerance, 'fraction_of_input_charge': measured/sum(q for _,q in pulses)}


def benchmark():
    c = ReadoutConfig.from_dict(json.loads((ROOT/'examples/single_channel_readout.json').read_text()))
    timing, pileup, gates = [], [], []
    charges = (.04, .08, .16, .32, .64)
    for phase in (0., .25, .5, .75):
        previous = math.inf
        for q in charges:
            t0 = 50+phase
            analog = crossing(q, c)
            singles = extract_singles(shape([(t0,q)], 0, 400, c), c)
            if analog is None:
                assert not singles, 'Subthreshold pulse unexpectedly detected'
                timing.append({'charge_pC': q, 'phase_ns': phase, 'detected': False})
                continue
            assert len(singles) == 1 and not singles[0]['truncated']
            measured = singles[0]['time_ns']-t0
            assert abs(measured-analog) <= 1.05, (q, phase, measured, analog)
            assert measured < previous, 'Leading-edge time should decrease with amplitude in this fixture'
            previous = measured
            row = {'charge_pC': q, 'phase_ns': phase, 'detected': True,
                   'analog_delay_ns': analog, 'measured_delay_ns': measured,
                   'timing_error_ns': measured-analog}
            row.update(gate_check([(t0,q)], singles, c)); timing.append(row)
    # Refined sampling/ADC must approach the instantaneous analytic crossing.
    fine = replace(c, sample_interval_ns=.02, adc_lsb_mV=.0001, adc_bits=24,
                   pre_samples=200, post_samples=2000)
    fine_errors = []
    for q in charges[1:]:
        t0 = 10.007
        singles = extract_singles(shape([(t0,q)], 0, 40, fine), fine)
        error = singles[0]['time_ns']-t0-crossing(q, fine)
        assert abs(error) <= .025, error
        fine_errors.append({'charge_pC': q, 'error_ns': error})
    for delay in (0,5,20,40,60,80,100,140):
        pulses = [(50.25,.16),(50.25+delay,.16)]
        singles = extract_singles(shape(pulses,0,500,c),c)
        assert len(singles) == (2 if delay >= 100 else 1), (delay, singles)
        row = {'separation_ns': delay, 'n_candidates': len(singles),
               'n_crossings': sum(s['n_crossings'] for s in singles),
               'candidate_times_ns': [s['time_ns'] for s in singles]}
        row.update(gate_check(pulses,singles,c)); pileup.append(row)
    for post in (0,10,40,100):
        settings = replace(c, post_samples=post)
        pulses = [(50.25,.16)]
        singles = extract_singles(shape(pulses,0,400,settings),settings)
        row = {'post_samples': post}; row.update(gate_check(pulses,singles,settings)); gates.append(row)
    assert all(a['analytic_gate_charge_pC'] < b['analytic_gate_charge_pC'] for a,b in zip(gates,gates[1:]))
    clipped = replace(c, adc_bits=8, adc_lsb_mV=1)
    pulses = [(50.25,100.)]
    singles = extract_singles(shape(pulses,0,500,clipped),clipped)
    assert singles and sum(s['n_saturated'] for s in singles) > 0
    saturation = gate_check(pulses,singles,clipped)
    assert saturation['measured_charge_pC'] < saturation['analytic_gate_charge_pC']
    saturation['n_rail_samples'] = sum(s['n_saturated'] for s in singles)
    return {'timing_default_tolerance_ns': 1.05, 'timing_refined_tolerance_ns': .025,
            'timing': timing, 'fine_sampling': fine_errors, 'pileup': pileup,
            'gate_scan': gates, 'saturation': saturation, 'configuration': c.__dict__}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report', type=Path)
    a = p.parse_args()
    if a.report and a.report.exists():
        raise FileExistsError(a.report)
    result = benchmark()
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        with a.report.open('x') as f:
            json.dump(result,f,indent=2); f.write('\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
