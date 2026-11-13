"""The workbench draws its own constraint icons, so none of its code imports
the Sketcher's GUI module (sh-048's Advice)."""

import ast
from pathlib import Path

_PACKAGE = Path(__file__).resolve().parent.parent / "freecad" / "Shelving"


def _imports_sketcher_gui(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules = [node.module]
        else:
            continue
        if any(module.split(".")[0] == "SketcherGui" for module in modules):
            return True
    return False


def test_no_workbench_module_imports_sketcher_gui() -> None:
    offenders = [
        str(path.relative_to(_PACKAGE))
        for path in sorted(_PACKAGE.rglob("*.py"))
        if _imports_sketcher_gui(ast.parse(path.read_text()))
    ]
    assert not offenders, f"{offenders} import SketcherGui"


def test_the_check_catches_both_import_forms() -> None:
    assert _imports_sketcher_gui(ast.parse("import SketcherGui"))
    assert _imports_sketcher_gui(ast.parse("def f():\n    from SketcherGui import x"))
    assert not _imports_sketcher_gui(ast.parse("import Sketcher"))
