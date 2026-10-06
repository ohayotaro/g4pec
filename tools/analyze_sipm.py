#!/usr/bin/env python3
"""Replay one channel of a portable SiPM dataset without geometry or truth input."""
import argparse
import json
from pathlib import Path
from readout import readout
from sipm_dataset import load_channel


def analyze(dataset, channel_id, prefix, config, gate=None):
    _, _, files = load_channel(dataset,channel_id)
    return readout(files['history'],files['response'],config,prefix,gate)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('dataset',type=Path); p.add_argument('channel_id'); p.add_argument('output_prefix',type=Path)
    p.add_argument('--config',required=True,type=Path); p.add_argument('--gate-config',type=Path)
    a=p.parse_args()
    try:
        r=analyze(a.dataset,a.channel_id,a.output_prefix,a.config,a.gate_config)
    except (ValueError,OSError,KeyError,TypeError,OverflowError) as e:
        p.exit(1,f'Post analysis failed: {e}\n')
    print(json.dumps({'channel_id':a.channel_id,'n_singles':r['n_singles']}))


if __name__ == '__main__': main()
