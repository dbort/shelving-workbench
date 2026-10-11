"""The rules that keep the QA wizard small and keep production code free of
it (`.claude/docs/qa-wizard.md`). Each failure message names its rule."""

import ast
from pathlib import Path

import pytest

from freecad.Shelving.qa.model import CaseFileError, parse_cases

_PACKAGE = Path(__file__).resolve().parent.parent / "freecad" / "Shelving"
_QA = _PACKAGE / "qa"
# Raising this is the user's decision when a task is planned, never during
# /work (.claude/docs/qa-wizard.md).
QA_LINE_BUDGET = 1200
_ALLOWED_IMPORTERS = {
    _PACKAGE / "commands" / "qa_wizard.py",
    _PACKAGE / "init_gui.py",
}


def _imported_modules(tree: ast.Module) -> list[tuple[str, list[str]]]:
    """Each import as (module, names): ``import a.b`` gives ("a.b", []),
    ``from a import b, c`` gives ("a", ["b", "c"])."""
    found: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, []) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.append((node.module, [alias.name for alias in node.names]))
    return found


def _imports_qa(module: str, names: list[str]) -> bool:
    if module == "freecad.Shelving.qa" or module.startswith("freecad.Shelving.qa."):
        return True
    return module == "freecad.Shelving" and "qa" in names


def test_production_code_never_imports_the_wizard() -> None:
    offenders = [
        str(path.relative_to(_PACKAGE))
        for path in sorted(_PACKAGE.rglob("*.py"))
        if _QA not in path.parents and path not in _ALLOWED_IMPORTERS
        if any(
            _imports_qa(module, names)
            for module, names in _imported_modules(ast.parse(path.read_text()))
        )
    ]
    assert not offenders, (
        "production never depends on the QA wizard: only commands/qa_wizard.py "
        f"and init_gui.py may import freecad.Shelving.qa, but {offenders} do"
    )


def test_the_wizard_uses_public_api_only() -> None:
    offenders: list[str] = []
    for path in sorted(_QA.rglob("*.py")):
        tree = ast.parse(path.read_text())
        name = path.relative_to(_PACKAGE)
        for module, names in _imported_modules(tree):
            if module.startswith("freecad.Shelving") and not _imports_qa(module, []):
                if any(part.startswith("_") for part in module.split(".")):
                    offenders.append(f"{name}: imports private module {module}")
                offenders.extend(
                    f"{name}: imports {n} from {module}"
                    for n in names
                    if n.startswith("_")
                )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr.startswith("_")
                and not node.attr.startswith("__")
                and not (isinstance(node.value, ast.Name) and node.value.id == "self")
            ):
                offenders.append(f"{name}:{node.lineno}: reads .{node.attr}")
    assert not offenders, (
        "the QA wizard uses public API only: no underscore names from other "
        f"modules, no underscore attributes but its own self's: {offenders}"
    )


def test_the_wizard_stays_within_its_line_budget() -> None:
    lines = sum(len(path.read_text().splitlines()) for path in _QA.rglob("*.py"))
    assert lines <= QA_LINE_BUDGET, (
        f"the QA wizard's Python is {lines} lines, over its {QA_LINE_BUDGET}-line "
        "budget; raising the budget is the user's decision when a task is "
        "planned, never during /work"
    )


def test_case_files_are_closed_data() -> None:
    data: dict[str, object] = {
        "case": [
            {
                "id": "c",
                "title": "C",
                "step": [
                    {
                        "id": "s",
                        "instruction": ["Do."],
                        "expected": "Done.",
                        "code": "x",
                    }
                ],
            }
        ]
    }
    with pytest.raises(CaseFileError) as refused:
        parse_cases(data, "x.toml")
        pytest.fail(
            "case files are closed data: the loader must refuse a key it does "
            "not know, but accepted 'code'"
        )
    assert "x.toml" in str(refused.value) and "'code'" in str(refused.value)
