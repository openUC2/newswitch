"""The microscope never imports what serves it: `newswitch.infra` and the entry files that put it
together (``app.py``, ``main_fastapi.py``, ``main.py``) import the rest, not the reverse.

Only imports that run count: one under ``if TYPE_CHECKING:`` names a type and loads nothing.
"""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "newswitch"
INFRA = PACKAGE / "infra"
#: What serves the microscope: the package, and the entry files beside it.
SERVING = ("newswitch.infra", "app", "main", "main_fastapi")


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _runtime_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Every module `tree` imports outside ``if TYPE_CHECKING:``, with its line."""
    found: list[tuple[int, str]] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            for child in node.orelse:
                visit(child)
            return
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.extend((node.lineno, f"{node.module}.{alias.name}") for alias in node.names)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return found


def _microscope_modules() -> list[Path]:
    return sorted(path for path in PACKAGE.rglob("*.py") if INFRA not in path.parents)


@pytest.mark.parametrize("path", _microscope_modules(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_the_microscope_does_not_import_infra(path: Path) -> None:
    """No module outside `newswitch.infra` imports it, or an entry file, when it runs."""
    tree = ast.parse(path.read_text(), filename=str(path))
    offending = [
        f"{path.relative_to(PACKAGE.parent)}:{line} imports {name}"
        for line, name in _runtime_imports(tree)
        if any(name == serving or name.startswith(f"{serving}.") for serving in SERVING)
    ]
    assert not offending, "\n".join(offending)


def test_the_check_sees_an_import_of_infra() -> None:
    """The check finds what it looks for, and leaves out what only names a type."""
    tree = ast.parse(
        "from typing import TYPE_CHECKING\n"
        "from newswitch.infra.http import running_context\n"
        "import main_fastapi\n"
        "if TYPE_CHECKING:\n"
        "    from newswitch.infra.mikro.connection import MikroConnection\n"
    )
    assert [name for _, name in _runtime_imports(tree)] == [
        "typing.TYPE_CHECKING",
        "newswitch.infra.http.running_context",
        "main_fastapi",
    ]


@pytest.mark.parametrize("old", ["accounts", "routes", "bloks", "broadcasters"])
def test_what_moved_to_infra_is_gone(old: str) -> None:
    """The packages that moved into `newswitch.infra` left nothing behind to import by mistake."""
    assert not (PACKAGE / old).exists()
