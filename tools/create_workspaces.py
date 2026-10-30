#!/usr/bin/env python3
"""Создание каталогов модемов и извлечение параметров с указанием источника."""
from pathlib import Path
import hashlib
import json
import math
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]

def write_readme(path, text):
    """README ведутся вручную: генератор создаёт только отсутствующий файл."""
    if not path.exists():
        path.write_text(text)

EXCLUDED = {'DPD_Example', 'Modems', 'adaptdemos', 'ams_r2006a_2007a',
            'petrov_modems_electronix', 'polar_code',
            'graphic_equalizer_16_band_2011_05_17', 'milewski_sequence_2011_05_19'}


def source_blocks(path):
    # Склеиваем продолжения строк; выражения MATLAB не исполняются.
    original = path.read_text(errors='replace')
    locations = [original[:m.start()].count('\n')+1 for m in re.finditer(r'\bBlock\s*\{', original)]
    text = re.sub(r'"\s*\n\s*"', '', original)
    blocks = []
    for number, match in enumerate(re.finditer(r'\bBlock\s*\{', text)):
        head = re.split(r'[{}]', text[match.end():], maxsplit=1)[0]
        fields = dict(re.findall(r'^\s*(\w+)\s+"([^"\n]*)"', head, re.M))
        if fields:
            fields['source_line'] = locations[number]
            blocks.append(fields)
    return blocks


def vector(value):
    return [complex(x.replace('i', 'j')) for x in value.strip('[] ').split()]


def config_for(name, blocks):
    family, order, diff, offset = 'psk', 4, 'psk', 0.0
    if name.startswith('bpsk'): order, offset = 2, math.pi / 4
    if name.startswith(('psk8', 'dqpsk_19')): order = 8
    if name.startswith('dqpsk_19'): offset = math.pi / 8
    if name.startswith('qam'): family, order, diff = 'qam', 16, 'quadrant'
    if name.startswith('QAM64'): family, order, diff = 'qam', 64, 'quadrant'
    if name.startswith('pi4'): family, diff = 'pi4', 'pi4'
    if name.startswith('msk'): family, order, diff = 'msk', 2, 'none'
    if name.startswith('gmsk'): family, order, diff = 'gmsk', 2, 'none'
    if name.startswith('qpsk_demod'): diff = 'none'
    if name.startswith(('qpsk_fb', 'simo')): offset = math.pi / 4
    if family == 'pi4':
        table = [complex(math.cos(k * math.pi / 4), math.sin(k * math.pi / 4)) for k in range(8)]
    elif family in {'msk', 'gmsk'}:
        table = [-1 + 0j, 1 + 0j]
    else:
        table = [complex(math.cos(2 * math.pi * k / order + offset),
                         math.sin(2 * math.pi * k / order + offset)) for k in range(order)]
    evidence = 'Analytic phase constellation; see source_parameters.json for block evidence.'
    for b in blocks:
        if b.get('Name') == 'data_mapper' and 'OutputValues' in b:
            table = vector(b['OutputValues'])
            evidence = 'Exact data_mapper OutputValues from the original model.'
        if b.get('SourceType') == 'M-PSK Modulator Baseband':
            offset = {'0': 0, 'pi/8': math.pi / 8, 'pi/4': math.pi / 4}.get(b.get('Ph'), offset)
            table = [complex(math.cos(2 * math.pi * k / order + offset),
                             math.sin(2 * math.pi * k / order + offset)) for k in range(order)]
            evidence = 'Analytic M-PSK mapping using original M and Ph parameters.'
    if order == 64:
        real = next(vector(b['MapVec']) for b in blocks if b.get('Name') == 'Data Mapper RE')
        imag = next(vector(b['MapVec']) for b in blocks if b.get('Name') == 'Data Mapper IM')
        table = [a + 1j * b for a, b in zip(real, imag)]
        evidence = 'Exact Data Mapper RE and IM MapVec arrays from the original model.'
    carrier = 'feedforward' if any(x in name for x in ('_ff_', '_fast_', 'phase_noise_phase_sync', 'feedforward')) else 'feedback'
    if name.startswith('bpsk') or name.startswith('qpsk_demod'): carrier = 'costas'
    timing = 'feedforward' if carrier == 'feedforward' or name.startswith('dqpsk_19') else 'gardner'
    notes = []
    if name.startswith('dqpsk_19'):
        notes.append('Despite its archive name, the original mapper is 8-PSK with M=8 and Ph=pi/8; this configuration preserves it.')
    if family == 'msk': notes.append('The original is a modulator only; a discriminator receiver is added for loopback verification.')
    if family == 'gmsk': notes.append('The original coherent Mengali/Costas receiver is replaced by a Gaussian pulse discriminator receiver in the portable model.')
    if order == 64: notes.append('The original quadrant coder uses a custom table; the portable quadrant differential coder uses the documented Gray convention, not a verified block-exact transcription.')
    return dict(name=name, family=family, order=order, differential=diff,
                sps=8, rrc_order=32, rolloff=1.0, gaussian_bt=0.3,
                constellation=[[z.real, z.imag] for z in table],
                mapping_evidence=evidence, timing=timing, carrier=carrier,
                equalizer='dfe' if '_dfe_' in name else ('linear' if '_eq_' in name else 'none'),
                diversity_branches=2 if name.startswith('simo') else 1,
                variable_delay='var_ch_delay' in name,
                phase_noise='phase_noise' in name, notes=notes,
                abstraction='Portable algorithm model with a training preamble; original Simulink transients are not reproduced.')


def main():
    catalog = []
    for directory in sorted((ROOT / 'sources').iterdir()):
        if directory.name in EXCLUDED: continue
        models = list(directory.glob('*.mdl'))
        if not models: continue
        assert len(models) == 1, directory
        source = models[0]
        blocks = source_blocks(source)
        cfg = config_for(directory.name, blocks)
        dest = ROOT / 'modems' / directory.name
        for folder in ('original', 'octave', 'python', 'sv', 'tb', 'tests'):
            (dest / folder).mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest / 'original' / source.name)
        cfg['source'] = str(source.relative_to(ROOT))
        cfg['source_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        (dest / 'config.json').write_text(json.dumps(cfg, indent=2) + '\n')
        (dest / 'source_parameters.json').write_text(json.dumps(blocks, indent=2, ensure_ascii=False) + '\n')
        (dest / 'python' / 'modem.py').write_text('''from pathlib import Path
import sys

# Общая реализация получает параметры именно этого исходного модема.
DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DIRECTORY.parents[1] / "common" / "python"))
from modem_core import load_config, transmit, receive, run_demo

CONFIG = load_config(DIRECTORY / "config.json")

if __name__ == "__main__":
    run_demo(CONFIG)
''')
        (dest / 'octave' / 'run_modem.m').write_text('''function result = run_modem()
  % Путь определяется по файлу, а не по текущему рабочему каталогу.
  here = fileparts(mfilename('fullpath'));
  root = fileparts(fileparts(fileparts(here)));
  addpath(fullfile(root, 'common', 'octave'));
  cfg = jsondecode(fileread(fullfile(fileparts(here), 'config.json')));
  result = modem_demo(cfg);
end
''')
        (dest / 'tests' / 'test_modem.py').write_text('''from pathlib import Path
import sys
import unittest

# Один контракт применяется ко всем вариантам с их собственными параметрами.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "common" / "python"))
from modem_checks import ModemContract


class TestModem(ModemContract, unittest.TestCase):
    config_path = Path(__file__).resolve().parents[1] / "config.json"


if __name__ == "__main__":
    unittest.main(verbosity=2)
''')
        (dest / 'octave' / 'test_modem.m').write_text('''function test_modem()
  % Проверяем перенос независимо от рабочего каталога.
  here = fileparts(mfilename('fullpath'));
  addpath(fullfile(fileparts(fileparts(fileparts(here))), 'common', 'octave'));
  cfg = jsondecode(fileread(fullfile(fileparts(here), 'config.json')));
  modem_test(cfg);
end
''')
        (dest / 'tb' / 'run.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
# Скрипт запускается из любого каталога.
modem_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
project_dir="$(cd -- "$modem_dir/../.." && pwd)"
exec python3 "$project_dir/tools/run_hdl.py" --modem "$(basename -- "$modem_dir")" "$@"
''')
        (dest / 'tb' / 'run.sh').chmod(0o755)
        (dest / 'sv' / 'modem.sv').write_text('''// Поведенческая модель кадра с отдельной конфигурацией модема.
module modem_variant(modem_if bus);
  modem_model core(bus);
endmodule
''')
        (dest / 'tb' / 'testbench.sv').write_text('''// Полный UVM testbench: sequence, driver, monitor, scoreboard и проверка сброса.
`include "tb_top.sv"
''')
        write_readme(dest / 'README.md', f'''# {directory.name.replace('_',' ')}

This workspace provides an executable portable algorithm model of the archived modem in Octave, Python and SystemVerilog. The original Simulink model is preserved in [original](original/). Full equivalence to the historical Simulink simulation has not been established.

## Configuration and source evidence

| Property | Portable configuration |
| --- | --- |
| Modulation | {cfg['family'].upper()} |
| Input alphabet | {cfg['order']} integer labels |
| Differential coding | {cfg['differential']} |
| Samples per symbol | {cfg['sps']} |
| Timing | {cfg['timing']} |
| Carrier tracking | {cfg['carrier']} |
| Equalizer | {cfg['equalizer']} |
| Diversity branches | {cfg['diversity_branches']} |

{cfg['mapping_evidence']} Configuration is stored in [config.json](config.json). Extracted block fields and original line numbers are in [source_parameters.json](source_parameters.json).

{' '.join(cfg['notes'])}

The receiver uses a known training preamble for frame timing, carrier frequency, phase and gain estimation. Historical blind acquisition, scramblers, internal CIC stages, original loop coefficients and exact block scheduling are not reproduced. See [the porting contract](../../docs/PORTING_CONTRACT.md) for the complete abstraction and tested channel range.

## Run from the project root

```bash
python3 modems/{directory.name}/python/modem.py
python3 modems/{directory.name}/tests/test_modem.py
octave-cli --quiet --eval "addpath('modems/{directory.name}/octave'); test_modem; run_modem;"
python3 tools/run_tests.py --suite cross --modem {directory.name}
./tools/run_questa.sh --modem {directory.name}
```

The Octave entry point is [octave/run_modem.m](octave/run_modem.m). Python exposes `CONFIG`, `transmit` and `receive` in [python/modem.py](python/modem.py). Shared DSP code is under [common](../../common/); changes there apply to every workspace.

## Original MATLAB verification

The [MATLAB test](matlab/test_original.m) checks simulation and exact repeatability of the prepared R2020b copy. [Migration details](matlab/migration.json) and [verification results](matlab/verification.json) distinguish compatibility adjustments from the unchanged original. Run `./tools/matlab.sh -nodisplay -batch "addpath('modems/{directory.name}/matlab'); test_original;"` from the project root. See [the reference report](../../docs/MATLAB_MODEM_VERIFICATION.md) for numerical comparisons and limits; successful execution does not establish full receiver equivalence.

## Visual tests

Open this modem in the [interactive report](../../docs/visual/index.html#section=explorer&model={directory.name}) to switch between three portable channel cases and the original MATLAB capture. The [original MATLAB plots](../../docs/visual/matlab/{directory.name}.png) and [complete PDF](../../docs/visual/modem_test_report.pdf) are also available. See [plot conventions](../../docs/VISUAL_TESTS.md) for units and verification limits.

![Portable test: impaired channel](../../docs/visual/portable/{directory.name}/case_1.png)

## SystemVerilog and verification

[sv/modem.sv](sv/modem.sv) instantiates the shared behavioral frame model. It computes transmit samples and receives an impaired waveform using real arithmetic. It is not synthesizable fixed point RTL. [tb/testbench.sv](tb/testbench.sv) selects the UVM testbench; [tb/run.sh](tb/run.sh) can be invoked from any directory.

The UVM sequence sends clean, noisy and variant specific channel cases, then repeats the first frame after reset. A passive monitor captures actual outputs. The scoreboard checks every transmit sample, receive symbol, decoded label, payload label and synchronization estimate against independent Python execution. New code comments are Russian; diagnostics are English.
''')
        catalog.append(dict(name=directory.name, family=cfg['family'], order=cfg['order'],
                            config=str((dest / 'config.json').relative_to(ROOT))))
    # Новые рабочие каталоги имеют собственный генератор; сохраняем их в общем индексе.
    known = {entry['name'] for entry in catalog}
    for path in sorted((ROOT / 'modems').glob('*/config.json')):
        if path.parent.name not in known:
            cfg = json.loads(path.read_text())
            catalog.append(dict(name=cfg['name'], family=cfg['family'], order=cfg['order'],
                                config=str(path.relative_to(ROOT))))
    catalog.sort(key=lambda entry: entry['name'])
    (ROOT / 'modems' / 'catalog.json').write_text(json.dumps(catalog, indent=2) + '\n')
    print(f'Created {len(catalog)} modem workspaces')


if __name__ == '__main__': main()
