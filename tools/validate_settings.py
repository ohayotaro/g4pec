#!/usr/bin/env python3
"""Validate user JSON settings with the same rules as the simulation/readout CLIs."""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from acquisition import prepare_acquisition
from digitize_cells import csv_rows, reject_constant, unique_json, validate_geometry
from fixed_gate import GateConfig
from readout import ReadoutConfig
from sipm_cells import CellConfig
from sipm_noise import NoiseConfig


def validate_settings(cells=None, noise=None, readout=None, gate=None, timeline=None, events=None, geometry=None):
    paths = dict(cells=cells, noise=noise, readout=readout, gate=gate, timeline=timeline)
    if not any(paths.values()):
        raise ValueError('Specify at least one JSON configuration')
    parsed = {key: json.loads(Path(path).read_bytes(), object_pairs_hook=unique_json,
                              parse_constant=reject_constant) for key,path in paths.items() if path is not None}
    models = {}
    for key, cls in (('cells',CellConfig),('noise',NoiseConfig),('readout',ReadoutConfig),('gate',GateConfig)):
        if key in parsed:
            models[key] = cls.from_dict(parsed[key])
    if gate is not None and readout is None:
        raise ValueError('--gate-config requires --readout for combined validation')
    if geometry is not None and cells is None:
        raise ValueError('--geometry requires --cells')
    if events is not None and timeline is None:
        raise ValueError('--events requires --timeline')
    result = {'valid': True, 'settings': {k:asdict(v) for k,v in models.items()},
              'checks': ['JSON schema, units encoded in field names, numeric ranges and model constraints'],
              'scope': 'Configuration validation only; no physical calibration or simulated performance claim'}
    if geometry is not None:
        result['geometry_footprint'] = validate_geometry(models['cells'], Path(geometry).read_bytes())
        result['checks'].append('Single-channel geometry footprint')
    if timeline is not None:
        if cells is None or events is None:
            raise ValueError('--timeline requires --cells and --events to verify event coverage and identity')
        arrival_keys, identity = {}, None
        for row in csv_rows(Path(events).read_bytes(), ('event_id','n_arrivals','n_active_channels','dataset_id','run_id'), 'events'):
            event, count, active, run = (int(row[k]) for k in ('event_id','n_arrivals','n_active_channels','run_id'))
            candidate = (row['dataset_id'], str(run))
            if event < 0 or event in arrival_keys or count < 0 or active != int(count > 0) or run < 0 or (identity and identity != candidate):
                raise ValueError('Invalid single-run event accounting/identity')
            identity = candidate
            arrival_keys[event] = []
        prepare_acquisition(models['cells'], arrival_keys, parsed['timeline'], identity)
        result['settings']['timeline'] = parsed['timeline']
        result['checks'].append('Timeline boundaries, event identity and complete event coverage; photon rows not checked')
        if readout is not None:
            duration = parsed['timeline']['window_end_ns']-parsed['timeline']['window_start_ns']
            n = duration/models['readout'].sample_interval_ns
            if not math.isfinite(n) or n > models['readout'].max_samples:
                raise ValueError('Acquisition window exceeds readout max_samples at this sample interval')
            result['waveform_samples'] = math.ceil(n)
    if readout is not None:
        result['readout_mode'] = 'fixed_gate' if gate is not None else 'release_based_merged_gates'
        result['trigger_rule'] = 'ADC leading-edge threshold with hysteretic release'
        result['inactive_readout_fields'] = ['pre_samples','post_samples'] if gate is not None else []
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('cells','noise','readout','timeline','events','geometry'):
        p.add_argument('--'+flag,type=Path)
    p.add_argument('--gate-config',dest='gate',type=Path)
    a = p.parse_args()
    try:
        result = validate_settings(**vars(a))
    except (ValueError,OSError,OverflowError,ET.ParseError) as error:
        p.exit(1,f'Settings validation failed: {error}\n')
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__ == '__main__': main()
