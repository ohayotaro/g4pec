#!/usr/bin/env python3
"""Replay existing ADC traces with fixed integration and non-extending holdoff."""
import argparse
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'studies'))
from readout import ReadoutConfig
from fixed_gate import ADCTrace, GateConfig
from bgo_response import FIRST, SPACING, SOURCE_TIME, ROI_LENGTH, rows, summary


def evaluate(singles,case,reference,gate):
    events=[]
    for e in range(case['events']):
        source=FIRST+e*SPACING+SOURCE_TIME
        selected=[s for s in singles if source-1 <= s['time_ns'] < source+ROI_LENGTH]
        blocked=any(s['time_ns'] < source-1 and s['time_ns']+gate.holdoff_ns > source for s in singles)
        first=min(selected,key=lambda s:s['time_ns']) if selected else None
        events.append({'event_id':e,'n_candidates':len(selected),'blocked_at_source':blocked,
                       'first_delay_ns':first['time_ns']-source if first else None,
                       'first_charge_pC':first['charge_pC'] if first else None,
                       'prompt_candidate':bool(first and first['time_ns'] < source+100),
                       'first_gate_fraction_of_3us_charge':first['charge_pC']/float(reference[e]['adc_roi_charge_pC']) if first else None})
    clean=[e for e in events if not e['blocked_at_source'] and e['n_candidates']]
    return {'n_candidates_per_source_roi':summary(e['n_candidates'] for e in events),
            'multi_candidate_events':sum(e['n_candidates']>1 for e in events),
            'zero_candidate_events':sum(e['n_candidates']==0 for e in events),
            'blocked_at_source_events':sum(e['blocked_at_source'] for e in events),
            'prompt_candidate_events':sum(e['prompt_candidate'] for e in events),
            'conditional_first_charge_pC':summary(e['first_charge_pC'] for e in clean),
            'conditional_first_gate_fraction':summary(e['first_gate_fraction_of_3us_charge'] for e in clean),
            'conditional_first_delay_ns':summary(e['first_delay_ns'] for e in clean)},events


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('study',type=Path);p.add_argument('--output-dir',type=Path,required=True)
    a=p.parse_args(); base=json.loads((a.study/'report.json').read_text())
    if not base.get('complete'): raise ValueError('Input study incomplete')
    a.output_dir.mkdir(parents=True,exist_ok=False)
    result={'schema_version':1,'source_report_sha256':hashlib.sha256((a.study/'report.json').read_bytes()).hexdigest(),
            'integration_ns':[100,300,600,1000,1500,2000],'additional_holdoff_ns':[0,500,1500],
            'pretrigger_ns':4,'holdoff_definition':'integration + pretrigger + additional; non-extending',
            'cases':[]}
    for case in base['cases']:
        for mode in ('noiseless','noise'):
            directory=a.study/case['label']
            manifest=json.loads((directory/f'{mode}_readout_readout.json').read_text())
            config=ReadoutConfig.from_dict(manifest['parameters'])
            waveform=directory/f'{mode}_readout_waveform.csv'
            samples=[]
            with waveform.open() as stream:
                for s in csv.DictReader(stream):
                    samples.append({k:float(s[k]) for k in ('bin_start_ns','bin_end_ns','time_ns')}
                                   | {'adc_code':int(s['adc_code'])})
            trace=ADCTrace(samples,config)
            reference=sorted(rows(directory/f'{mode}_evaluation.csv'),key=lambda e:int(e['event_id']))
            record={'label':case['label'],'mode':mode,'events':case['events'],
                    'waveform_sha256':hashlib.sha256(waveform.read_bytes()).hexdigest(),
                    'readout_parameters':manifest['parameters'],'settings':[]}
            target=a.output_dir/(case['label']+'_'+mode);target.mkdir()
            for width in result['integration_ns']:
                for extra in result['additional_holdoff_ns']:
                    gate=GateConfig(1,'Literature-informed exploration, not calibrated',width,4,width+4+extra)
                    singles=trace.extract(gate)
                    metrics,events=evaluate(singles,case,reference,gate)
                    label=f'gate{width}_extra{extra}'
                    for suffix,data,header in (
                        ('singles',singles,('single_id','time_ns','gate_start_ns','gate_end_ns','charge_pC','peak_mV','n_crossings','n_saturated','truncated')),
                        ('evaluation',events,events[0].keys())):
                        with (target/f'{label}_{suffix}.csv').open('x',newline='') as stream:
                            writer=csv.DictWriter(stream,fieldnames=header);writer.writeheader();writer.writerows(data)
                    (target/f'{label}.json').write_text(json.dumps(asdict(gate),indent=2)+'\n')
                    record['settings'].append({'gate':asdict(gate),'n_total_candidates':len(singles),**metrics})
            result['cases'].append(record)
            (a.output_dir/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
            print(case['label'],mode,'18 settings complete',flush=True)
            del trace,samples
    result['complete']=True
    (a.output_dir/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':main()
