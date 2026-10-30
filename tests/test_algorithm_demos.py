"""Статические проверки исторических демо без запуска MATLAB и Octave."""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKSPACES = sorted(p for p in (ROOT / "algorithms").glob("*/*") if p.is_dir()) + [
    ROOT / "modems" / name
    for name in ("qpsk_script_basic", "qpsk_script_costas", "fsk_text")
]
HEADINGS = (
    "Что это", "Как работает", "Структура каталога",
    "Как запустить", "Что смотреть", "Ограничения",
)


@pytest.mark.parametrize("workspace", WORKSPACES,
                         ids=lambda p: p.relative_to(ROOT).as_posix())
def test_demo_layout(workspace):
    demo = workspace / "run_demo.m"
    readme = workspace / "README.md"
    assert demo.is_file(), f"Missing demo: {demo}"
    assert readme.is_file(), f"Missing README: {readme}"
    description = readme.read_text(encoding="utf-8")
    assert "run_demo" in description
    assert "THIRD_PARTY.md" in description
    for heading in HEADINGS:
        assert f"## {heading}\n" in description
    code = demo.read_text(encoding="utf-8")
    assert re.search(r"function\b[^\n]*\brun_demo\s*\(", code)
    assert "'original'" in code
    assert "исходные скрипты не входят в публичный репозиторий, см. THIRD_PARTY.md" in code
    if "addpath(" in code:
        assert code.index("modems:MissingOriginal") < code.index("addpath(")


@pytest.mark.parametrize("workspace", WORKSPACES,
                         ids=lambda p: p.relative_to(ROOT).as_posix())
def test_demo_original_sources(workspace):
    code = (workspace / "run_demo.m").read_text(encoding="utf-8")
    # Это исполняемый список проверки комплекта в обёртке, а не комментарий.
    manifest = re.search(r"sourceFiles\s*=\s*\{(.*?)\};", code, re.DOTALL)
    assert manifest, "Demo must declare its original source files"
    sources = re.findall(r"'([^']+)'", manifest.group(1))
    assert sources and len(sources) == len(set(sources))
    assert any(name.endswith(".m") for name in sources)
    assert "fullfile(original, sourceFiles{sourceIndex})" in code

    # Литеральные имена запускаемых скриптов (в том числе examples/filename)
    # должны быть охвачены проверкой комплекта. Остальные имена — вызовы функций.
    filenames = re.findall(r"'([^'\n]+\.m)'", code)
    declared_names = {Path(name).name for name in sources}
    for name in filenames:
        assert name in sources or Path(name).name in declared_names, name

    original = workspace / "original"
    if not original.is_dir():
        pytest.skip("Historical sources are excluded from the public repository")
    for name in sources:
        source = original / name
        assert source.is_file(), f"Missing original source referenced by {workspace}: {name}"

    # Прямые вызовы исходных функций также сверяем с манифестом. Общий список
    # берётся из локальных original/, включая зависимости соседних модулей.
    calls = set(re.findall(r"\b([A-Za-z]\w*)\s*\(", code))
    source_roots = [p / "original" for p in WORKSPACES if (p / "original").is_dir()]
    original_functions = {p.stem for root in source_roots for p in root.rglob("*.m")}
    # Вспомогательные функции, определённые в самой обёртке, не требуют original/.
    local_functions = set(re.findall(
        r"^function\s+(?:(?:\[[^\]]+\]|\w+)\s*=\s*)?(\w+)\s*\(",
        code, re.MULTILINE,
    ))
    declared_functions = {Path(name).stem for name in sources if name.endswith(".m")}
    for name in (calls & original_functions) - local_functions:
        assert name in declared_functions, f"Undeclared original function: {name}"
