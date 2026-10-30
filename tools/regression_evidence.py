"""Привязываем результаты к исходникам до запуска, проверяем неизменность после."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes(root=ROOT):
    files = []
    for folder in ('common', 'tools', 'tests', 'modems', 'algorithms', 'research', 'rtl'):
        for p in (root/folder).rglob('*'):
            if (p.is_file() and not {'__pycache__'} & set(p.relative_to(root).parts)
                    and (p.suffix in ('.py', '.m', '.mdl', '.slx', '.sv', '.svh', '.sh', '.hex', '.mem', '.xdc', '.sdc', '.tcl', '.yaml') or p.name in ('config.json', 'model.json', 'catalog.json', 'warnings.json'))):
                files.append(p)
    for folder in ('tools/visual_report_assets', 'tools/typed_visual_assets'):
        files.extend(p for p in (root/folder).rglob('*') if p.is_file())
    if (root/'docs/matlab_audit_expectations.json').is_file(): files.append(root/'docs/matlab_audit_expectations.json')
    return {str(p.relative_to(root)): digest(p) for p in sorted(files)}


def begin(root=ROOT):
    return {'started_at_utc': datetime.now(timezone.utc).isoformat(), 'source_hashes': source_hashes(root)}


def verify(evidence, root=ROOT):
    if not evidence.get('source_hashes') or evidence['source_hashes'] != source_hashes(root):
        raise RuntimeError('Stale regression evidence: source files changed or evidence is missing')
    for name, expected in evidence.get('artifact_hashes', {}).items():
        if not (root/name).is_file() or digest(root/name) != expected:
            raise RuntimeError(f'Stale regression artifact: {name}')


def require_unoptimized():
    if not __debug__:
        raise RuntimeError('Run verification without Python optimization (-O)')


def require_pass(evidence, root=ROOT):
    """A source snapshot alone is not evidence of a completed successful run."""
    if not isinstance(evidence, dict):
        raise RuntimeError('Complete passing regression results are required')
    verify(evidence, root)
    if evidence.get('status') != 'PASS' or not evidence.get('completed_at_utc'):
        raise RuntimeError('Complete passing regression results are required')


def finish(evidence, artifacts=(), root=ROOT):
    verify(evidence, root)
    return dict(evidence, completed_at_utc=datetime.now(timezone.utc).isoformat(),
                artifact_hashes={str(Path(p).resolve().relative_to(root.resolve()))
                                if Path(p).resolve().is_relative_to(root.resolve())
                                else str(Path(p).resolve()): digest(p) for p in artifacts})


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def questa_paths():
    configured = os.environ.get('QUESTA_HOME')
    executable = shutil.which('vsim')
    if configured:
        home = Path(configured).resolve()
    elif executable:
        # Resolve symlinks: PATH may hold a vsim symlink, and the vendor's own
        # bin/vsim may point into a nested vco/bin. Take the shallowest ancestor
        # that still owns bin/vsim so the nested link is not mistaken for the home.
        candidates = [parent for parent in Path(executable).resolve().parents
                      if (parent/'bin/vsim').is_file()]
        home = candidates[-1] if candidates else Path.home()/'questasim'
    else:
        home = Path.home()/'questasim'
    if not (home/'bin/vsim').is_file():
        raise RuntimeError('Questa not found: set QUESTA_HOME or add vsim to PATH')
    return home/'bin', Path(os.environ.get('UVM_HOME', home/'verilog_src/uvm-1.2'))


def require_numeric_failure(output):
    # Проверяем сообщение отказа и ненулевой счётчик, а не заголовок сводки.
    if not re.search(r'UVM_FATAL[^\n]*\[NUMERIC\]', output) or not re.search(r'UVM_FATAL\s*:\s*[1-9]\d*', output):
        raise RuntimeError('Injected numeric mismatch was not detected by the UVM scoreboard')


def mquote(path):
    return str(path).replace("'", "''")
