"""Plot a completed BGO study report (optional matplotlib dependency)."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('report', type=Path); p.add_argument('output', type=Path)
a = p.parse_args()
if a.output.exists(): raise FileExistsError(a.output)
r = json.loads(a.report.read_text())
if not r.get('complete'): raise ValueError('Incomplete study')
depth = sorted([c for c in r['cases'] if c['energy_keV']==100], key=lambda c:c['source_local_z_mm'])
energy = sorted([c for c in r['cases'] if c['source_local_z_mm']==0], key=lambda c:c['energy_keV'])
fig, axes = plt.subplots(2,2,figsize=(10,7),layout='constrained')
ax=axes[0,0]
ax.errorbar([c['source_local_z_mm'] for c in depth],[c['arrivals_per_event']['mean'] for c in depth],
            yerr=[c['arrivals_per_event']['se'] for c in depth],fmt='o-',capsize=4,color='#287896')
ax.set(xlabel='Source local z [mm] (+z toward sensor)',ylabel='Mean arrivals per event',title='Depth scan: 100 keV electrons')
for ax, cases, xkey, metric, title, ylabel in (
    (axes[0,1],depth,'source_local_z_mm','adc_roi_charge_pC','Depth: fixed 3 us charge ROI','Mean ROI charge [pC]'),
    (axes[1,0],energy,'energy_keV','adc_roi_charge_pC','Energy: fixed 3 us charge ROI','Mean ROI charge [pC]'),
    (axes[1,1],energy,'energy_keV','unambiguous_first_delay_ns','Timing: exclude pre-existing gates','Mean first candidate delay [ns]')):
    for mode,label,color in [('noiseless','Noise off','#287896'),('noise','Noise on','#d9792a')]:
        stats=[c['modes'][mode][metric] for c in cases]
        ax.errorbar([c[xkey] for c in cases],[s['mean'] for s in stats],yerr=[s['se'] for s in stats],fmt='o-',capsize=4,label=label,color=color)
    ax.set(title=title,ylabel=ylabel,xlabel='Source local z [mm]' if xkey=='source_local_z_mm' else 'Electron energy [keV]')
    ax.legend()
for ax in axes.flat: ax.grid(alpha=.2)
fig.suptitle('Illustrative BGO end-to-end study | 32 events/condition | error bars: SE\nFixed geometry and parameters; not calibrated detector performance',fontsize=11)
fig.savefig(a.output,dpi=180)
