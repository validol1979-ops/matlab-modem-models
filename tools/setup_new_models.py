#!/usr/bin/env python3
"""Create typed workspaces while preserving every downloaded source byte."""
import hashlib
import json
import math
from pathlib import Path
import shutil
from create_workspaces import source_blocks, config_for

ROOT = Path(__file__).resolve().parents[1]

def write_readme(path, text):
    """README ведутся вручную: генератор создаёт только отсутствующий файл."""
    if not path.exists():
        path.write_text(text)

NEW_MODEMS = {
    'oqpsk_2_sps_timing_recovery_2019_12_05': ('oqpsk', 'research/electronix_20260930/models/oqpsk_2_sps_timing_recovery_2019_12_05.mdl'),
    'qpsk_8_sps_fb_sync_2020_11_25': ('psk', 'research/electronix_20260930/models/qpsk_8_sps_fb_sync_2020_11_25.mdl'),
    'qpsk_script_basic': ('psk', 'research/dsp_global_20260930/sources/china_qpsk/matlab/qpsk_modem_basic.m'),
    'qpsk_script_costas': ('psk', 'research/dsp_global_20260930/sources/china_qpsk/matlab/qpsk_modem_costas.m'),
}

RTL_SECTION='''
## Fixed point RTL

The streaming RTL is the BPSK pilot core with `ORDER=4`: `bpsk_tx`/`bpsk_rx` in `rtl/modems/bpsk_costas_2008_08_25/`. The integer reference is the `QPSK` profile in `common/python/psk_fixed.py`; `qpsk_8_sps_fb_sync_2020_11_25`, `qpsk_script_basic` and `qpsk_script_costas` share it because their configurations are identical. Labels are two bits without differential coding; run `python3 tools/run_bpsk.py --suite all`. [Interfaces, formats, latency and limits](../../docs/BPSK_RTL.md#qpsk-order4).
'''


def main():
    template = ROOT/'modems/qpsk_fb_symbol_sync_fb_phase_sync_agc_2008_05_15'
    for name,(family,source_name) in NEW_MODEMS.items():
        source=ROOT/source_name; dest=ROOT/'modems'/name
        for folder in ('original','octave','python','sv','tb','tests','matlab'):
            (dest/folder).mkdir(parents=True,exist_ok=True)
        if source.suffix=='.m':
            for p in source.parent.glob('*.m'): shutil.copy2(p,dest/'original'/p.name)
        else: shutil.copy2(source,dest/'original'/source.name)
        blocks=source_blocks(source) if source.suffix=='.mdl' else []
        cfg=config_for(name,blocks)
        cfg.update(family=family,differential='none',carrier='costas',timing='feedforward' if family=='oqpsk' else 'gardner',
            constellation=[[math.cos(math.pi/4+k*math.pi/2),math.sin(math.pi/4+k*math.pi/2)] for k in range(4)],
            mapping_evidence='Portable unit-energy QPSK quadrant table; original mapping and scrambling equivalence are not claimed.',
            source=source_name,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            notes=['Eight samples per portable symbol; original multirate scheduling and fixed-point filter arithmetic are not reproduced.'],
            category='modems',research_addition=True)
        (dest/'config.json').write_text(json.dumps(cfg,indent=2)+'\n')
        (dest/'source_parameters.json').write_text(json.dumps(blocks,indent=2,ensure_ascii=False)+'\n')
        for relative in ('python/modem.py','octave/run_modem.m','octave/test_modem.m','sv/modem.sv','tb/testbench.sv','tb/run.sh','tests/test_modem.py'):
            shutil.copy2(template/relative,dest/relative)
        if source.suffix=='.mdl':
            (dest/'matlab/test_original.m').write_text(f"function test_original()\n% Отдельная проверка новых оригиналов без изменения архивных файлов.\nroot = fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));\naddpath(fullfile(root,'tools'));\nmatlab_check_research(16384,'{name}');\nend\n")
        write_readme(dest / 'README.md', f'''# {name}

Generated workspace: rerunning `setup_new_models.py` overwrites configuration and execution entry points; an existing README is kept.

Category: **Modems**. Original source: [{source.name}](original/{source.name}).

This is a portable algorithm analogue with Python, Octave/MATLAB and behavioral SystemVerilog/UVM implementations. It uses a known training preamble, unit-energy quadrant mapping and eight samples per symbol. The original blind loops, scramblers, fixed-point rounding and multirate scheduling are not reproduced. Full original-model equivalence is not claimed.

{'OQPSK delays the Q branch by half a symbol. The receiver estimates carrier and delay from the preamble, then samples I and Q at their distinct instants.' if family=='oqpsk' else 'The receiver performs preamble acquisition, matched filtering and decision-directed carrier/gain tracking.'}
{RTL_SECTION if family=='psk' else ''}
## Execute

```bash
python3 modems/{name}/tests/test_modem.py
python3 tools/run_tests.py --suite cross --modem {name}
./tools/run_questa.sh --modem {name}
```

The shared Octave implementation also runs in MATLAB. Original MATLAB evidence is reported separately from portable tests. Original script sources retain their author encoding and comments.

[Typed visual report](../../docs/typed_visual/index.html) · [Model configuration](config.json) · [Source fields](source_parameters.json)

## Test preview

![Verified test scenario](../../docs/typed_visual/modems/{name}/case_0.png)
''')
    catalog=[]
    for p in sorted((ROOT/'modems').glob('*/config.json')):
        cfg=json.loads(p.read_text());catalog.append(dict(name=cfg['name'],family=cfg['family'],order=cfg['order'],config=str(p.relative_to(ROOT))))
    (ROOT/'modems/catalog.json').write_text(json.dumps(catalog,indent=2)+'\n')
    print(f'Created {len(NEW_MODEMS)} new modem workspaces; total {len(catalog)}')


if __name__=='__main__': main()
