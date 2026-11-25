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


# --- runtime | simulation | calibration ------------------------------------------------------------
#
# The design (`newswitch.instrument`) is pure: what follows from the description. The runtime
# (services, drivers, routines, actions) runs it. The simulation pretends to be the microscope, and
# hides how its copy differs from the design (``truth.yml``); the calibration measures how a copy
# differs. Only the composition root (`newswitch.microscope`) chooses between them, and simulation
# and calibration never meet in code: only in a test that calibrates the twin.


def _module_of(path: Path) -> str:
    parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imports_of(prefix: str, importers: tuple[str, ...]) -> set[str]:
    """``module -> imported`` for every module of `importers` (prefixes) that imports `prefix`."""
    found: set[str] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        module = _module_of(path)
        if not any(module == p or module.startswith(f"{p}.") for p in importers):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for _, name in _runtime_imports(tree):
            if name == prefix or name.startswith(f"{prefix}."):
                found.add(f"{module} -> {prefix}")
    return found


def _everything_but(*allowed: str) -> tuple[str, ...]:
    """The subpackages of newswitch (and its own modules) other than `allowed`."""
    modules = {_module_of(path) for path in PACKAGE.rglob("*.py")}
    tops = {".".join(m.split(".")[:2]) for m in modules if m != "newswitch"}
    return tuple(sorted(t for t in tops if t not in allowed))


#: What still breaks a rule, and goes in the step that cuts it (docs: the split's plan). A rule that
#: holds where this says it breaks fails too: strike it off here.
PENDING: dict[str, set[str]] = {
    "design": set(),
    "simulation": set(),
    "calibration": {
        "newswitch.protocols.calibration -> newswitch.calibration",
        "newswitch.protocols.optics -> newswitch.calibration",
        "newswitch.services.optics -> newswitch.calibration",
    },
    "apart": set(),
}

RULES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # The design imports nothing that runs it, pretends to be it or measures it.
    "design": (
        ("newswitch.instrument",),
        (
            "newswitch.simulation",
            "newswitch.calibration",
            "newswitch.services",
            "newswitch.drivers",
            "newswitch.routines",
            "newswitch.actions",
            "newswitch.microscope",
            "newswitch.settings",
        ),
    ),
    # Only the root picks the simulation (and the tools, the reference and what serves it use it).
    "simulation": (
        _everything_but(
            "newswitch.simulation",
            "newswitch.microscope",
            "newswitch.tools",
            "newswitch.infra",
            "newswitch.reference",
        ),
        ("newswitch.simulation",),
    ),
    # Only the root registers the calibration; the runtime reads it through its protocol.
    "calibration": (
        _everything_but("newswitch.calibration", "newswitch.microscope", "newswitch.tools"),
        ("newswitch.calibration",),
    ),
    # The twin's hidden deviation and the measured one never meet in code.
    "apart": (("newswitch.simulation", "newswitch.calibration"), ()),
}


#: What a rule allows: the description has a ``settings`` section, whose schema is `Settings`.
ALLOWED: set[str] = {"newswitch.instrument.spec -> newswitch.settings"}


def _violations(rule: str) -> set[str]:
    importers, forbidden = RULES[rule]
    if rule == "apart":
        return _imports_of("newswitch.calibration", ("newswitch.simulation",)) | _imports_of(
            "newswitch.simulation", ("newswitch.calibration",)
        )
    return set().union(*(_imports_of(prefix, importers) for prefix in forbidden)) - ALLOWED


@pytest.mark.parametrize("rule", sorted(RULES))
def test_runtime_simulation_and_calibration_stay_apart(rule: str) -> None:
    """Each rule breaks exactly where `PENDING` says it still does."""
    assert _violations(rule) == PENDING[rule]


def test_only_the_simulation_and_the_root_read_the_simulation_mode() -> None:
    """``settings.simulate`` decides at the root; nothing else asks which mode it runs in."""
    readers = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        module = _module_of(path)
        if module.startswith(("newswitch.microscope", "newswitch.tools")) or module in (
            "newswitch.settings",
        ):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == "simulate") or (
                isinstance(node, (ast.Name, ast.alias))
                and getattr(node, "id", getattr(node, "name", None)) == "SIMULATED"
            ):
                readers.add(module)
    # the mount calibration asks so as not to write a twin's mount into the description: it goes
    # when what is calibrated is kept in the calibration's own store
    assert readers == {"newswitch.calibration.mount"}


def test_only_the_simulation_reads_the_truth() -> None:
    """``truth.yml``, how a copy differs from its design, is the simulation's alone."""
    readers = {
        _module_of(path)
        for path in PACKAGE.rglob("*.py")
        if "truth.yml" in path.read_text() or "simulation.truth" in path.read_text()
    }
    assert {r for r in readers if not r.startswith("newswitch.simulation")} == set()


#: What a description says of what the simulator draws on a sample: its schema stays in the
#: description (`newswitch.instrument.spec`), and only the simulation reads it.
SAMPLE_SIMULATION_NAMES = {"Simulation", "Fluorophore", "Pattern", "Stain", "Electrical", "SimulatedSlide"}
SAMPLE_SIMULATION_FIELDS = {"simulation", "simulations", "fluorophore", "pattern", "stains", "electrical"}


def test_only_the_simulation_reads_what_is_simulated_on_a_sample() -> None:
    """The optics predict from the design alone: what a simulated sample emits, reflects or looks
    like is the simulator's (`newswitch.simulation`), never what the runtime publishes."""
    readers: set[str] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        module = _module_of(path)
        if module.startswith(("newswitch.simulation", "newswitch.tools")) or module == (
            "newswitch.instrument.spec"
        ):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in SAMPLE_SIMULATION_FIELDS:
                readers.add(f"{module}: .{node.attr}")
            elif isinstance(node, ast.alias) and node.name in SAMPLE_SIMULATION_NAMES:
                readers.add(f"{module}: {node.name}")
    assert readers == set()
