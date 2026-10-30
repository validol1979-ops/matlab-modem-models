#!/usr/bin/env python3
"""Sum the stream_cover lines (rtl/tb/stream_cover.sv) of the last Questa runs into one table.

Reads normal scenario logs declared by the latest completed regression result, adds the counters
per stream name and prints a Markdown table; a bin that no run hit is marked with "**0**".
--require-mode-bins fails (exit 1) if some mode bin was never transferred.
"""
import argparse,json,re,sys
from pathlib import Path
from regression_evidence import require_pass
ROOT=Path(__file__).resolve().parents[1]
BLOCKS=['fft','ofdm','stft','pfb','fir','oset','fsk','beam','sync','lms','ldpc','mmse','mmse3','mmse_n','rls','omlsa','oqpsk']
LINE=re.compile(r'COVER (.+?) group=([\d.]+) xfer=(\d+) stall=(\d+) last=(\d+) pos=(\d+) neg=(\d+) zero=(\d+) modes=([\d,]*)')
FIELDS=('xfer','stall','last','pos','neg','zero')
NORMAL_LOGS={'stream.log','gaps.log','stalled.log','midreset.log','outreset.log','cfgreset.log',
             'loopback.log','backpressure.log','minimum.log','maximum.log','tailcut.log'}

def scenario_logs(block):
    reports=[]
    for suite in ('all','hdl'):
        path=ROOT/'build/rtl'/block/f'{suite}_results.json'
        if path.is_file():
            data=json.loads(path.read_text())
            reports.append((data.get('started_at_utc',''),data))
    if not reports:raise RuntimeError(f'{block}: no completed RTL regression report')
    _,data=max(reports,key=lambda pair:pair[0])
    require_pass(data,ROOT)
    return sorted(ROOT/name for name in data.get('artifact_hashes',{})
                  if Path(name).name in NORMAL_LOGS)

def collect(blocks):
    table={}
    for block in blocks:
        for log in scenario_logs(block):
            for match in LINE.finditer(log.read_text(errors='replace')):
                name=match.group(1);row=table.setdefault(name,dict(block=block,runs=0,group=0.0,modes=None,**{f:0 for f in FIELDS}))
                row['runs']+=1;row['group']=max(row['group'],float(match.group(2)))
                for index,field in enumerate(FIELDS):row[field]+=int(match.group(3+index))
                modes=[int(x) for x in match.group(9).split(',') if x]
                if row['modes'] is not None and len(row['modes'])!=len(modes):
                    raise RuntimeError(f'{name}: inconsistent mode bin count in {log}')
                row['modes']=modes if row['modes'] is None else [a+b for a,b in zip(row['modes'],modes)]
    return table

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('blocks',nargs='*',default=BLOCKS)
    parser.add_argument('--require-mode-bins',action='store_true');args=parser.parse_args()
    table=collect(args.blocks)
    if not table:print('no COVER lines found (run the hdl suites first)');return 1
    mark=lambda n:f'**0**' if n==0 else str(n)
    print('| stream | block | runs | max group % | transfers | stalls | last | +full scale | -full scale | zero | modes |')
    print('|---|---|---|---|---|---|---|---|---|---|---|')
    missing=[]
    for name,row in table.items():
        modes=','.join(mark(n) for n in row['modes'])
        if any(n==0 for n in row['modes']):missing.append(name)
        print(f"| {name} | {row['block']} | {row['runs']} | {row['group']:.1f} | "+' | '.join(mark(row[f]) for f in FIELDS)+f' | {modes} |')
    if args.require_mode_bins and missing:print('mode bins never hit: '+', '.join(missing));return 1
    return 0

if __name__=='__main__':sys.exit(main())
