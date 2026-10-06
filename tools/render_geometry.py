#!/usr/bin/env python3
"""Render the explicitly placed, unrotated boxes of the single-detector GDML."""
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Patch
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('gdml', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
root = ET.parse(args.gdml).getroot()
world_name = root.find('./setup/world').get('ref')
volumes = {v.get('name'): v for v in root.findall('./structure/volume')}
boxes = {b.get('name'): b for b in root.findall('./solids/box')}
parts = []
colors = {'Crystal': '#469dbf', 'Coupling': '#efb64c', 'Sensor': '#cc5272'}
labels = {'Crystal': 'BGO crystal', 'Coupling': 'Optical coupling (glass)', 'Sensor': 'SiPM collector / channel 0'}
for placement in volumes[world_name].findall('physvol'):
    name = placement.find('volumeref').get('ref')
    volume = volumes[name]
    if placement.find('rotation') is not None or placement.find('rotationref') is not None or volume.findall('physvol'):
        raise ValueError('This preview supports only flat, unrotated box placements')
    box = boxes[volume.find('solidref').get('ref')]
    pos = placement.find('position')
    if box.get('lunit') != 'mm' or pos.get('unit') != 'mm':
        raise ValueError('Preview expects explicit mm units')
    size = [float(box.get(a)) for a in ('x', 'y', 'z')]
    center = [float(pos.get(a, '0')) for a in ('x', 'y', 'z')]
    parts.append((name, size, center))
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.spines.top': False,
                     'axes.spines.right': False, 'axes.labelcolor': '#334155', 'text.color': '#172b40'})
fig = plt.figure(figsize=(14, 8.3), facecolor='#f8fafc')
gs = fig.add_gridspec(2, 2, width_ratios=[1.18, 1], left=.045, right=.96, bottom=.16,
                      top=.85, hspace=.48, wspace=.24)
ax = fig.add_subplot(gs[:, 0], projection='3d', computed_zorder=False, facecolor='#f8fafc')
plan = fig.add_subplot(gs[0, 1], facecolor='white')
section = fig.add_subplot(gs[1, 1], facecolor='white')
for name, size, center in parts:
    x,y,z = [[c-d/2,c+d/2] for c,d in zip(center,size)]
    faces = [ [(x[i],y[j],z[k]) for j,k in [(0,0),(1,0),(1,1),(0,1)]] for i in (0,1)]
    faces += [[(x[i],y[j],z[k]) for i,k in [(0,0),(1,0),(1,1),(0,1)]] for j in (0,1)]
    faces += [[(x[i],y[j],z[k]) for i,j in [(0,0),(1,0),(1,1),(0,1)]] for k in (0,1)]
    ax.add_collection3d(Poly3DCollection(faces, facecolors=colors[name], edgecolors=colors[name],
                                        linewidths=.65, zorder={'Crystal': 1, 'Coupling': 2, 'Sensor': 3}[name], alpha=.22 if name=='Crystal' else .85))
    plan.add_patch(Rectangle((x[0],y[0]),size[0],size[1],facecolor=colors[name],
                             edgecolor=colors[name],alpha=.8 if name=='Sensor' else .4))
    section.add_patch(Rectangle((x[0],z[0]),size[0],size[2],facecolor=colors[name],
                                edgecolor=colors[name],alpha=.8))
ax.set(xlim=(-7,7), ylim=(-7,7), zlim=(-6,6), xlabel='X [mm]', ylabel='Y [mm]', zlabel='Z [mm]')
ax.set_box_aspect((14,14,12))
ax.view_init(elev=26, azim=-55)
fig.text(.055,.825,'ASSEMBLED GEOMETRY / True proportions',fontsize=11)
plan.set(xlim=(-7,7),ylim=(-6.7,6.7),xlabel='X [mm]',ylabel='Y [mm]')
plan.set_aspect('equal')
plan.set_title('SENSOR-SIDE VIEW  /  looking along −Z',loc='left',fontsize=11,pad=12)
plan.text(0,0,'SiPM\n5.8 × 5.8 mm',ha='center',va='center',color='white',weight='bold',fontsize=10)
section.set(xlim=(-7,7),ylim=(4.85,5.3),xlabel='X [mm]',ylabel='Z [mm]')
section.set_yticks([4.9,5.,5.1,5.2,5.3])
section.set_title('INTERFACE SECTION  /  Y = 0\nZ axis expanded to show the 0.1 mm layers',loc='left',fontsize=11,pad=10)
section.text(0,4.925,'BGO crystal',ha='center',va='center',color='white',weight='bold')
section.text(0,5.05,'Glass coupling  ·  0.1 mm',ha='center',va='center',fontsize=9)
section.text(0,5.15,'SiPM  ·  0.1 mm',ha='center',va='center',fontsize=9,color='white',weight='bold')
for a in (plan,section):
    a.set_axisbelow(True)
    a.grid(alpha=.15)
fig.text(.045,.95,'Single crystal + single-channel SiPM',fontsize=23,weight='bold')
fig.text(.045,.905,'GDML geometry preview  |  BGO: 12 × 12 × 10 mm  |  SiPM centered on the +Z face',fontsize=12,color='#52647a')
fig.legend(handles=[Patch(facecolor=colors[n],label=labels[n]) for n,_,_ in parts],
           loc='lower center',bbox_to_anchor=(.5,.07),ncol=3,frameon=False)
fig.text(.045,.037,f'Source: {args.gdml.name}  •  Air world omitted  •  No package or microcell structure in this model',
         fontsize=9,color='#64748b')
args.output.parent.mkdir(parents=True,exist_ok=True)
fig.savefig(args.output,dpi=160,facecolor=fig.get_facecolor())
print(args.output.resolve())
