#!/usr/bin/env python3
"""Generate equivalent XDC/SDC timing contracts from a single YAML input."""
import argparse
import math
from pathlib import Path
import re
import yaml


def load(path):
    value=yaml.safe_load(Path(path).read_text())
    name=value['clock']['port']
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',name):
        raise ValueError('Invalid clock port')
    frequency=float(value['clock']['frequency_mhz'])
    numbers=[frequency,float(value['clock']['uncertainty_ns']),float(value['io']['input_delay_ns']),float(value['io']['output_delay_ns']),float(value['io']['output_load_pf'])]
    if not all(math.isfinite(x) and x>=0 for x in numbers) or frequency<=0:
        raise ValueError('Invalid timing specification')
    for name in ('xilinx','altera'):
        if not re.fullmatch(r'[A-Za-z0-9_-]+',value['targets'][name]):raise ValueError('Invalid FPGA part')
    for name,threshold in value['acceptance'].items():
        if not math.isfinite(float(threshold)) or float(threshold)<0:raise ValueError('Invalid slack threshold')
    return value


def generate(source,destination):
    spec=load(source);destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    clk=spec['clock']['port'];period=1000/float(spec['clock']['frequency_mhz'])
    lines=[f'create_clock -name core_clk -period {period:.9f} [get_ports {{{clk}}}]',
           f"set_clock_uncertainty -from [get_clocks core_clk] -to [get_clocks core_clk] {float(spec['clock']['uncertainty_ns']):.9f}",
           f'set input_ports [remove_from_collection [all_inputs] [get_ports {{{clk}}}]]',
           f"set_input_delay -clock core_clk -max {float(spec['io']['input_delay_ns']):.9f} $input_ports",
           'set_input_delay -clock core_clk -min 0.0 $input_ports',
           f"set_output_delay -clock core_clk -max {float(spec['io']['output_delay_ns']):.9f} [all_outputs]",
           'set_output_delay -clock core_clk -min 0.0 [all_outputs]']
    # No false paths: every port is timed. CDC needs explicit per-instance paths
    # once clock domains are integrated; broad exceptions are deliberately absent.
    for suffix in ('xdc','sdc'):
        vendor_lines=list(lines)
        if suffix=='xdc':
            vendor_lines[2]=f'set input_ports [get_ports -filter {{DIRECTION == IN && NAME != {clk}}}]'
            vendor_lines.append(f"set_load {float(spec['io']['output_load_pf']):.9f} [all_outputs]")
        (destination/f'timing.{suffix}').write_text('\n'.join(vendor_lines)+'\n')
    return spec


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,default=Path('rtl/constraints/common.yaml'));parser.add_argument('--output',type=Path,default=Path('build/rtl/constraints'))
    args=parser.parse_args();generate(args.source,args.output)
