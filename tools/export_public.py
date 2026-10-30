#!/usr/bin/env python3
"""Build a clean public copy of the project without third-party material.

The copy contains tracked and new (not ignored) files except historical archives,
extracted third-party sources, `original/` model copies, downloaded research code and
verbatim book excerpts (see THIRD_PARTY.md). Absolute local paths in text files are
rewritten to neutral forms. The local repository and its history are not modified;
the copy is meant to become a new repository with fresh history.

    python3 tools/export_public.py ../modems-public [--git-init]
"""
import argparse
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# Корневые каталоги сторонних материалов и локальных артефактов.
EXCLUDED_TOP = {'arxiv', 'sources', 'matlab', 'work', 'build', 'slprj', '.Xil', '.claude', '.pytest_cache'}
# Скачанный сторонний код внутри research/<набор>/.
EXCLUDED_RESEARCH = {'archives', 'sources', 'models', 'support'}
EXCLUDED_NAMES = {'transcript', 'rag_evidence.json'}
HISTORICAL_MODEL = re.compile(r'^modems/[^/]+/matlab/[^/]+\.(mdl|slx)$')
# Локальные пути заменяются нейтральными; порядок важен (длинные префиксы раньше).
PATH_RULES = [
    (re.compile(re.escape(str(ROOT)) + r'/?'), ''),
    (re.compile(r'/home/[A-Za-z0-9_.-]+'), '~'),
    (re.compile(r'/mnt/sda1/'), 'local-library/'),
    (re.compile(r'/mnt/nvme1/[^\s"\'`)<>,;\]]*'), '<local-path>'),
]
# Временные пути убираются только из документов и журналов: в коде и тестах /tmp бывает данными.
DOC_RULES = [(re.compile(r'/tmp/[^\s"\'`)<>,;\]]+'), '<local-tmp>')]
DOC_SUFFIXES = {'.md', '.json', '.log', '.txt', '.diff', '.csv', '.html'}
# Сам экспортёр содержит шаблоны путей и не очищается.
SELF = 'tools/export_public.py'
MD_LINK = re.compile(r'(!?)\[([^\]\n]*)\]\((<[^>\n]*>|[^)\s]+)\)')
# Дополнительные локальные правила «регулярное выражение<TAB>замена»; файл в .gitignore и не публикуется.
LOCAL_RULES = ROOT/'tools/export_scrub.local.tsv'
TEXT_SUFFIXES = {'.md', '.txt', '.json', '.csv', '.py', '.m', '.sv', '.svh', '.sh', '.log', '.diff',
                 '.yaml', '.yml', '.ini', '.html', '.js', '.css', '.tcl', '.xdc', '.sdc', '.svg'}


def excluded(name):
    parts = PurePosixPath(name).parts
    if parts[0] in EXCLUDED_TOP or parts[-1] in EXCLUDED_NAMES or parts[-1].endswith('.slxc'):
        return True
    if parts[0] in ('modems', 'algorithms') and 'original' in parts:
        return True
    if parts[0] == 'research' and len(parts) > 2 and parts[2] in EXCLUDED_RESEARCH:
        return True
    return bool(HISTORICAL_MODEL.match(name))


def candidates():
    listing = lambda *args: subprocess.run(['git', 'ls-files', '-z', *args], cwd=ROOT, check=True,
                                           capture_output=True).stdout.decode().split('\0')
    names = set(listing()) | set(listing('--others', '--exclude-standard'))
    return sorted(n for n in names if n and (ROOT/n).is_file())


def local_rules():
    if not LOCAL_RULES.is_file():
        return []
    rows = [line.split('\t', 1) for line in LOCAL_RULES.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.startswith('#')]
    return [(re.compile(pattern), replacement) for pattern, replacement in rows]


def scrub(text, rules=None):
    for pattern, replacement in PATH_RULES + (rules or []):
        text = pattern.sub(replacement, text)
    return text


def unlink_missing(text, name, target):
    """Ссылки Markdown на файлы, которых нет в копии, превращаются в обычный текст."""
    base = (target/name).parent
    def fix(match):
        bang, label, href = match.groups()
        href = href[1:-1] if href.startswith('<') else href
        path = href.split('#', 1)[0]
        if not path or re.match(r'^[a-z][a-z0-9+.-]*:', path):
            return match.group(0)
        if not path.startswith('<') and (base/path).exists():
            return match.group(0)
        return f'{label} (не входит в публичную копию)' if not bang else f'*{label or "изображение"} (не входит в публичную копию)*'
    return MD_LINK.sub(fix, text)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('target', type=Path, help='new directory; must not exist')
    parser.add_argument('--git-init', action='store_true', help='initialise an empty git repository (no commit)')
    args = parser.parse_args()
    target = args.target.resolve()
    if target.exists():
        raise SystemExit(f'Target already exists: {target}')
    if ROOT == target or ROOT in target.parents:
        raise SystemExit('Target must be outside the project')
    kept = skipped = scrubbed = 0
    rules = local_rules()
    for name in candidates():
        if excluded(name):
            skipped += 1
            continue
        source, dest = ROOT/name, target/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in TEXT_SUFFIXES:
            try:
                text = source.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                text = None
            if text is not None:
                extra = rules + (DOC_RULES if source.suffix.lower() in DOC_SUFFIXES else [])
                clean = text if name == SELF else scrub(text, extra)
                scrubbed += clean != text
                dest.write_text(clean, encoding='utf-8')
                shutil.copymode(source, dest)
                kept += 1
                continue
        shutil.copy2(source, dest)
        kept += 1
    # Второй проход: ссылки проверяются по уже собранной копии.
    unlinked = 0
    for md in target.rglob('*.md'):
        name = str(md.relative_to(target)); text = md.read_text(encoding='utf-8')
        clean = unlink_missing(text, name, target)
        if clean != text:
            md.write_text(clean, encoding='utf-8'); unlinked += 1
    if args.git_init:
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(target)], check=True)
    print(f'{kept} files copied ({scrubbed} with local paths rewritten, {unlinked} with dead links unlinked), '
          f'{skipped} excluded -> {target}')


if __name__ == '__main__':
    sys.exit(main())
