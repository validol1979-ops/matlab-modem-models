"""Verilator adapter for the existing macro-only integer scoreboards (no UVM claim)."""
from pathlib import Path
import subprocess
from run_rtl import ROOT, SOURCES

PILOT = ROOT / 'rtl/modems/bpsk_costas_2008_08_25'


def command(args, cwd, log, *, negative=False):
    p = subprocess.run(list(map(str, args)), cwd=cwd, capture_output=True, text=True, errors='replace', timeout=600)
    text = p.stdout + p.stderr
    log.write_text(text)
    if negative:
        if p.returncode not in (1,-6,134) or '%Fatal:' not in text or '[NUMERIC]' not in text or any(
                marker in text for marker in ('PASS BPSK receiver:', 'PASS BPSK direct acquisition:',
                                              'PASS ACQUIRE SCENARIO', 'PASS BPSK divider modes:', 'PASS DIVIDE BOUNDARIES')):
            raise RuntimeError(f'Invalid numeric negative control: {log}')
    elif p.returncode or '%Error' in text:
        raise RuntimeError(f'Verilator command failed: {log}\n{text[-3000:]}')
    return text


def build(out, top, benches, parameters=None):
    """Copy benches only; keep every scoreboard expression and enable assertions."""
    out.mkdir(parents=True, exist_ok=False)
    (out / 'uvm_macros.svh').write_text('`define uvm_fatal(ID,MSG) $fatal(1,"[%s] %s",ID,MSG);\n')
    copies = []
    for bench in benches:
        path = out / Path(bench).name
        path.write_text(Path(bench).read_text().replace('import uvm_pkg::*;', ''))
        copies.append(path)
    args = ['verilator', '--binary', '--timing', '--assert', '-j', '4', '-Wno-fatal',
            '--top-module', top, '--Mdir', out / 'obj', '-o', 'sim',
            f'-I{out}', f'-I{PILOT}', *[f'-G{k}={v}' for k, v in (parameters or {}).items()],
            *SOURCES, *copies]
    command(args, ROOT, out / 'compile.log')
    return out / 'obj/sim'
