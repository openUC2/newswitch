# Vendored copy of the optikit design reader (originally ~/Code/testing/optikit_dsn.py).
# Part of newswitch now: change it here. Needs numpy and PyYAML; simplify() needs pyvista.
"""optikit designs (``*.dsn``) as models a scene blok can move, and the blok that moves them.

An optikit design is a folder with an ``optikit-design.yml``: components (static CAD parts
or other designs), an assembly tree that poses them, and inputs that the poses read
through expressions (``offset-mm: {x: ~ inputs['x-stage'].value}``). optikit's own glTF
export flattens each design's assembly, so a stage carriage and the plates riding on it
come out as siblings, and nothing says which input moves what. This module evaluates the
design itself, the way optikit does (``exp/designs`` in the optikit repository):

* an input starts at the zero value of its kind; ``min``/``max`` are metadata;
* a pose is ``T(offset-grid * {50, 50, 55} + offset-mm) * R`` in millimeters, ``R`` from
  ``grid``/``uc2`` (columns ``X, Z x X, Z``), ``euler`` (``Rz * Rx * Ry``, degrees) or a
  ``quaternion`` (``[x, y, z, w]``);
* an ``affine`` child composes onto its parent; a ``relative-position`` child adds its
  offset to the parent's translation and keeps its own rotation; base ``assembly``/``mate``
  poses are relative to the design's root; a subdesign's assembly sits in its component.

Then every numeric input of the top design is nudged: where a pose follows one, the model
gets a joint node there (named after the input, ``sample-x`` -> ``sample_x``), and the
parts it carries hang below it. Translations become prismatic joints, a single varying
rotation a revolute one; anything else is refused with the input and component named.

``build(dsn)`` returns the GLB (the parts' meshes merged, Z-up turned to glTF's Y-up, every
node named ``[a-z0-9_]+`` after its component path, the joint table in
``extras.arkitekt.joints``) together with what can be bound. ``scene(model, ...)`` turns
an app's bindings (a state value per input, a glow or a click per component) into the
blok's component tree:

    model = optikit_dsn.build("fluorescence.dsn")
    MODEL.write_bytes(model.glb)
    app.register_asset("microscope", MODEL.name)
    app.blok("microscope-3d", optikit_dsn.scene(
        model, asset="microscope",
        joints={"sample-x": optikit_dsn.Bind("self.Stage.x", unit="um")},
        glow={"blue-laser": "self.Laser.on"},
        open={"camera": "microscope-camera"},
    ))

``simplify(model.glb, keep=0.05)`` cuts the meshes down for a viewer (CAD exports are
millions of triangles) and leaves everything a blok binds as it was.

Also a command: ``python optikit_dsn.py <dsn> --out model.glb [-i name:value] [--simplify 0.05]``
writes the model and lists the joints and components an app can bind.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

#: optikit's UC2 grid, in millimeters per cube (``exp/designs/geometry.go``).
GRID_MM = np.array([50.0, 50.0, 55.0])
#: Turns optikit's Z-up into glTF's Y-up: -90 degrees about X, as [x, y, z, w].
Y_UP = [-math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5)]
#: Parts without a material of their own get this one (optikit's parts mostly have none).
DEFAULT_MATERIAL = {
    "name": "optikit_default",
    "pbrMetallicRoughness": {
        "baseColorFactor": [0.82, 0.83, 0.85, 1.0],
        "metallicFactor": 0.0,
        "roughnessFactor": 0.65,
    },
}
#: Millimeters per unit, and degrees per unit, for unit conversion in bindings.
LENGTH_UNITS = {"nm": 1e-6, "um": 1e-3, "µm": 1e-3, "mm": 1.0, "cm": 10.0, "m": 1000.0}
ANGLE_UNITS = {"deg": 1.0, "rad": 180.0 / math.pi}
ZERO_VALUES: dict[str, Any] = {
    "bool": False,
    "int": 0,
    "float64": 0.0,
    "string": "",
    "quaternion": [0.0, 0.0, 0.0, 1.0],
}
NUMERIC_KINDS = {"int", "float64"}
NODE_NAME = re.compile(r"[a-z0-9_]+")


class DesignError(ValueError):
    """The design cannot be read, or cannot be turned into a model with joints."""


# ====================
# Expressions (the expr-lang subset optikit designs use)
# ====================

_TOKEN = re.compile(
    r"\s*(?:(?P<number>\d+\.\d*|\.\d+|\d+)|(?P<string>'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<op>==|!=|<=|>=|&&|\|\||[-+*/%?:.,\[\](){}<>!]))"
)


def _tokens(text: str) -> list[tuple[str, Any]]:
    tokens, position = [], 0
    text = text.strip()
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match or match.end() == position:
            raise DesignError(f"cannot read the expression {text!r} at {text[position:]!r}")
        position = match.end()
        kind = match.lastgroup
        value = match.group(kind)
        if kind == "number":
            tokens.append(("value", float(value) if "." in value else int(value)))
        elif kind == "string":
            tokens.append(("value", re.sub(r"\\(.)", r"\1", value[1:-1])))
        elif kind == "name" and value in ("true", "false", "nil"):
            tokens.append(("value", {"true": True, "false": False, "nil": None}[value]))
        elif kind == "name" and value in ("and", "or", "not"):
            tokens.append(("op", {"and": "&&", "or": "||", "not": "!"}[value]))
        else:
            tokens.append((kind, value))
    return tokens


class _Parser:
    """A Pratt parser that evaluates as it reads (expressions here have no side effects)."""

    BINARY = {
        "||": (1, lambda a, b: a or b),
        "&&": (2, lambda a, b: a and b),
        "==": (3, lambda a, b: a == b),
        "!=": (3, lambda a, b: a != b),
        "<": (4, lambda a, b: a < b),
        ">": (4, lambda a, b: a > b),
        "<=": (4, lambda a, b: a <= b),
        ">=": (4, lambda a, b: a >= b),
        "+": (5, lambda a, b: a + b),
        "-": (5, lambda a, b: a - b),
        "*": (6, lambda a, b: a * b),
        "/": (6, lambda a, b: a / b),
        "%": (6, lambda a, b: a % b),
    }

    def __init__(self, text: str, env: dict[str, Any]):
        self.text, self.env, self.tokens, self.at = text, env, _tokens(text), 0

    def peek(self) -> tuple[str, Any] | None:
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def take(self, op: str | None = None) -> tuple[str, Any]:
        token = self.peek()
        if token is None or (op is not None and token != ("op", op)):
            raise DesignError(
                f"in {self.text!r}: expected {op or 'more'}, found {token[1] if token else 'the end'}"
            )
        self.at += 1
        return token

    def parse(self) -> Any:
        value = self.expression()
        if self.peek() is not None:
            raise DesignError(f"in {self.text!r}: unexpected {self.peek()[1]!r}")
        return value

    def expression(self) -> Any:
        condition = self.binary(0)
        if self.peek() == ("op", "?"):
            self.take("?")
            when_true = self.expression()
            self.take(":")
            when_false = self.expression()
            return when_true if condition else when_false
        return condition

    def binary(self, floor: int) -> Any:
        left = self.unary()
        while (
            (token := self.peek())
            and token[0] == "op"
            and token[1] in self.BINARY
            and self.BINARY[token[1]][0] > floor
        ):
            self.take()
            strength, apply = self.BINARY[token[1]]
            left = apply(left, self.binary(strength))
        return left

    def unary(self) -> Any:
        if self.peek() == ("op", "-"):
            self.take()
            return -self.unary()
        if self.peek() == ("op", "+"):
            self.take()
            return +self.unary()
        if self.peek() == ("op", "!"):
            self.take()
            return not self.unary()
        return self.postfix(self.primary())

    def primary(self) -> Any:
        kind, value = self.take()
        if kind == "value":
            return value
        if kind == "name":
            if value not in self.env:
                raise DesignError(f"in {self.text!r}: unknown name {value!r}")
            return self.env[value]
        if value == "(":
            inner = self.expression()
            self.take(")")
            return inner
        if value == "[":
            items = []
            while self.peek() != ("op", "]"):
                items.append(self.expression())
                if self.peek() == ("op", ","):
                    self.take(",")
            self.take("]")
            return items
        if value == "{":
            entries = {}
            while self.peek() != ("op", "}"):
                key_kind, key = self.take()
                if key_kind not in ("name", "value"):
                    raise DesignError(f"in {self.text!r}: a map key is a name or a string")
                self.take(":")
                entries[key] = self.expression()
                if self.peek() == ("op", ","):
                    self.take(",")
            self.take("}")
            return entries
        raise DesignError(f"in {self.text!r}: unexpected {value!r}")

    def postfix(self, value: Any) -> Any:
        while (token := self.peek()) in (("op", "."), ("op", "[")):
            self.take()
            if token[1] == ".":
                _, key = self.take()
            else:
                key = self.expression()
                self.take("]")
            try:
                value = value[key]
            except (KeyError, IndexError, TypeError):
                raise DesignError(f"in {self.text!r}: nothing at {key!r}") from None
        return value


def evaluate(text: str, env: dict[str, Any]) -> Any:
    """The value of an expr-lang expression (without its ``~ `` marker)."""
    return _Parser(text, env).parse()


def _always(value: Any, env: dict[str, Any], default: Any) -> Any:
    """A field optikit always compiles: offsets, euler angles, ``disabled``. ``~ `` is optional."""
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return evaluate(value[2:] if value.startswith("~ ") else value, env)
    return value


def _marked(value: Any, env: dict[str, Any]) -> Any:
    """A field that is an expression only with the ``~ `` marker: instantiation inputs, ``assembly``."""
    if isinstance(value, str) and value.startswith("~ "):
        return evaluate(value[2:], env)
    return value


def _coerce(value: Any, kind: str, where: str) -> Any:
    """optikit's ``convertTo``: an instantiation value as the subdesign declares its input."""
    try:
        if kind == "float64":
            return float(value)
        if kind == "int":
            return int(value) if not isinstance(value, str) else int(value.strip())
        if kind == "bool":
            if isinstance(value, bool):
                return value
            return {"true": True, "1": True, "false": False, "0": False}[str(value).strip().lower()]
        if kind == "string":
            return value if isinstance(value, str) else str(value)
        return value
    except (KeyError, ValueError, TypeError):
        raise DesignError(f"{where}: {value!r} is not a {kind}") from None


# ====================
# Designs and poses
# ====================


@dataclass
class Design:
    """One ``optikit-design.yml`` and the folder its paths are relative to."""

    folder: Path
    inputs: dict[str, dict[str, Any]]
    components: dict[str, dict[str, Any]]
    assemblies: dict[str, dict[str, Any]]


_designs: dict[Path, Design] = {}


def load_design(folder: str | Path) -> Design:
    folder = Path(folder)
    key = folder.resolve()
    if key not in _designs:
        path = folder / "optikit-design.yml"
        if not path.is_file():
            raise DesignError(f"{folder} has no optikit-design.yml")
        declared = yaml.safe_load(path.read_text()) or {}
        _designs[key] = Design(
            folder=folder,
            inputs=declared.get("inputs") or {},
            components=declared.get("components") or {},
            assemblies=declared.get("assemblies") or {},
        )
    return _designs[key]


def _axis(text: str) -> np.ndarray:
    match = re.fullmatch(r"([+-]?)([xyz])", str(text).strip())
    if not match:
        raise DesignError(f"{text!r} is not a grid axis like +x or -z")
    vector = np.zeros(3)
    vector["xyz".index(match.group(2))] = -1.0 if match.group(1) == "-" else 1.0
    return vector


def _rotation(spec: dict[str, Any] | None, env: dict[str, Any]) -> np.ndarray:
    spec = spec or {}
    kind = spec.get("kind") or ""
    if kind == "":
        return np.eye(3)
    if kind in ("grid", "uc2"):
        grid = spec.get("grid") or {}
        z, x = _axis(grid.get("z", "+z")), _axis(grid.get("x", "+x"))
        if abs(np.dot(z, x)) > 0.5:
            raise DesignError(f"grid rotation {grid} has coaxial z and x")
        return np.column_stack([x, np.cross(z, x), z])
    if kind == "euler":
        angles = spec.get("euler") or {}
        x, y, z = (math.radians(float(_always(angles.get(name), env, 0.0))) for name in "xyz")
        return _rz(z) @ _rx(x) @ _ry(y)
    if kind == "quaternion":
        return _quaternion_matrix(_always(spec.get("quaternion"), env, [0.0, 0.0, 0.0, 1.0]))
    raise DesignError(f"unknown rotation kind {kind!r}")


def _rx(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rz(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _quaternion_matrix(q: list[float]) -> np.ndarray:
    x, y, z, w = (float(v) for v in q)
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def _matrix_quaternion(r: np.ndarray) -> list[float]:
    """[x, y, z, w] of a rotation matrix, with w >= 0."""
    trace = r[0, 0] + r[1, 1] + r[2, 2]
    if trace > 0:
        s = 2.0 * math.sqrt(trace + 1.0)
        q = [(r[2, 1] - r[1, 2]) / s, (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s, 0.25 * s]
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = 2.0 * math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2])
        q = [0.25 * s, (r[0, 1] + r[1, 0]) / s, (r[0, 2] + r[2, 0]) / s, (r[2, 1] - r[1, 2]) / s]
    elif r[1, 1] > r[2, 2]:
        s = 2.0 * math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2])
        q = [(r[0, 1] + r[1, 0]) / s, 0.25 * s, (r[1, 2] + r[2, 1]) / s, (r[0, 2] - r[2, 0]) / s]
    else:
        s = 2.0 * math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1])
        q = [(r[0, 2] + r[2, 0]) / s, (r[1, 2] + r[2, 1]) / s, 0.25 * s, (r[1, 0] - r[0, 1]) / s]
    if q[3] < 0:
        q = [-v for v in q]
    n = math.sqrt(sum(v * v for v in q))
    return [v / n for v in q]


def _transform(rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = rotation
    m[:3, 3] = translation
    return m


@dataclass
class Placed:
    """A component as the design places it, for one set of input values."""

    path: str  # "sample-stage/z-plate"
    kind: str  # design | primitive | location | results | mate
    owner: str  # the design component it belongs to, "" for the top design
    frame: str  # the component its pose is relative to ("" = the top design's root)
    world: np.ndarray  # 4x4, millimeters, in the top design's frame
    relative: bool = False  # a relative-position pose: the frame's translation, not its rotation
    gltf: Path | None = None


def _environment(design: Design, values: dict[str, Any], where: str) -> dict[str, Any]:
    """``inputs`` as expressions see them: every declared input, given or at its zero value."""
    inputs = {}
    for name, declaration in design.inputs.items():
        declaration = declaration or {}
        kind = declaration.get("kind", "float64")
        value = values[name] if name in values else ZERO_VALUES.get(kind)
        inputs[name] = {
            "value": _coerce(value, kind, f"{where}: input {name}") if value is not None else None,
            "kind": kind,
            "units": declaration.get("units"),
            "min": declaration.get("min"),
            "max": declaration.get("max"),
        }
    return {"inputs": inputs}


def place(dsn: str | Path, values: dict[str, Any] | None = None) -> dict[str, Placed]:
    """Every component of the design's default assembly, posed for these top-level input values."""
    design = load_design(dsn)
    placed: dict[str, Placed] = {}
    unknown = set(values or {}) - set(design.inputs)
    if unknown:
        raise DesignError(
            f"the design has no inputs {sorted(unknown)}; it has {sorted(design.inputs)}"
        )
    _place_design(design, "", values or {}, "", np.eye(4), placed)
    return placed


def _place_design(
    design: Design,
    assembly: str,
    values: dict[str, Any],
    owner: str,
    owner_world: np.ndarray,
    placed: dict[str, Placed],
) -> None:
    where = owner or str(design.folder)
    env = _environment(design, values, where)
    if assembly not in design.assemblies:
        raise DesignError(
            f"{where}: {design.folder} has no assembly {assembly!r} (has {sorted(design.assemblies)})"
        )

    def walk(children: dict[str, Any] | None, parent: str | None, parent_local: np.ndarray) -> None:
        for cid in sorted(children or {}):
            spec = (children or {})[cid] or {}
            if _always(spec.get("disabled"), env, False):
                continue
            if cid not in design.components:
                raise DesignError(f"{where}: the assembly places {cid!r}, which is not a component")
            component = design.components[cid] or {}
            path = f"{owner}/{cid}" if owner else cid
            pose = spec.get("pose") or {}
            translation_spec = pose.get("translation") or {}
            grid = translation_spec.get("offset-grid") or {}
            mm = translation_spec.get("offset-mm") or {}
            offset = np.array([float(int(_always(grid.get(a), env, 0))) for a in "xyz"]) * GRID_MM
            offset += np.array([float(_always(mm.get(a), env, 0.0)) for a in "xyz"])
            rotation = _rotation(pose.get("rotation"), env)
            pose_kind = pose.get("kind") or "affine"
            base = (pose.get("base") or {}).get("kind") or "parent"
            if pose_kind not in ("affine", "relative-position"):
                raise DesignError(f"{path}: unknown pose kind {pose_kind!r}")
            if base not in ("parent", "assembly", "mate"):
                raise DesignError(f"{path}: unknown pose base {base!r}")

            if parent is None or base in ("assembly", "mate"):
                local, frame = _transform(rotation, offset), owner
            elif pose_kind == "relative-position":
                local, frame = _transform(rotation, parent_local[:3, 3] + offset), parent
            else:
                local, frame = parent_local @ _transform(rotation, offset), parent
            world = owner_world @ local

            kind = component.get("kind")
            relative = frame == parent and pose_kind == "relative-position"
            entry = Placed(
                path=path, kind=kind, owner=owner, frame=frame, world=world, relative=relative
            )
            placed[path] = entry
            if kind == "design":
                sub_folder = design.folder / component["design"]
                sub = load_design(sub_folder)
                given = ((component.get("instantiation") or {}).get("inputs")) or {}
                sub_values = {
                    name: _marked(value, env) for name, value in given.items() if name in sub.inputs
                }
                sub_assembly = _marked(spec.get("assembly"), env) or ""
                _place_design(sub, str(sub_assembly), sub_values, path, world, placed)
            elif kind == "primitive":
                primitive = component.get("primitive") or {}
                if (primitive.get("kind") or "static") != "static":
                    raise DesignError(
                        f"{path}: primitive kind {primitive.get('kind')!r} is not supported"
                    )
                model = (primitive.get("static-models") or {}).get("gltf")
                entry.gltf = design.folder / model if model else None
            elif kind not in ("location", "results", "mate"):
                raise DesignError(f"{path}: unknown component kind {kind!r}")
            walk(spec.get("children"), path, local)

    walk(design.assemblies[assembly].get("children"), None, np.eye(4))


# ====================
# Devices (what newswitch would control)
# ====================

#: The input tag that marks a design input as naming the top-level input an axis follows.
BINDING_TAG = "config/newswitch/input-variable-binding"
BINDING_PREFIX = "newswitch-input-variable-"


@dataclass
class Device:
    """A part the design says newswitch controls, with its device config.

    A primitive with ``static-models: {newswitch-device: <file>}`` and
    ``results: {newswitch-device-id: ...}`` is one. Its config is that file, with
    ``results['newswitch-device-config']`` merged over it: what optikit's own
    ``tools/examples/newswitch/settings.py`` writes into ``_newswitch-config.yml``,
    read here from the designs themselves.
    """

    id: str
    type: str  # camera | laser | stage | controller | ...
    path: str  # the primitive: "sample-stage/stage-drivers"
    component: str  # the top design's component it is part of: "sample-stage"
    config: dict[str, Any]
    #: axis label -> the top-level input it follows (``{"x": "sample-x"}``), from the
    #: inputs of the device's design tagged ``config/newswitch/input-variable-binding``
    bindings: dict[str, str] = field(default_factory=dict)


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in over.items():
        merged[key] = (
            _merge(merged[key], value)
            if isinstance(value, dict) and isinstance(merged.get(key), dict)
            else value
        )
    return merged


def devices(dsn: str | Path, values: dict[str, Any] | None = None) -> list[Device]:
    """Every device in the design, in component order.

    Components are walked whether or not an assembly places them: a stage's
    drivers have no geometry and sit in no assembly, yet they are what moves it.
    """
    found: list[Device] = []

    def walk(design: Design, given: dict[str, Any], owner: str) -> None:
        where = owner or str(design.folder)
        env = _environment(design, given, where)
        for cid in design.components:
            component = design.components[cid] or {}
            path = f"{owner}/{cid}" if owner else cid
            kind = component.get("kind")
            if kind == "design":
                sub = load_design(design.folder / component["design"])
                inputs = ((component.get("instantiation") or {}).get("inputs")) or {}
                walk(
                    sub,
                    {
                        name: _marked(value, env)
                        for name, value in inputs.items()
                        if name in sub.inputs
                    },
                    path,
                )
                continue
            models = ((component.get("primitive") or {}).get("static-models")) or {}
            results = {
                name: _marked(value, env)
                for name, value in (component.get("results") or {}).items()
            }
            if (
                kind != "primitive"
                or "newswitch-device" not in models
                or not results.get("newswitch-device-id")
            ):
                continue
            file = design.folder / models["newswitch-device"]
            if not file.is_file():
                raise DesignError(f"{path}: its newswitch device file {file} does not exist")
            config = yaml.safe_load(file.read_text()) or {}
            config = _merge(config, results.get("newswitch-device-config") or {})
            config.pop("newswitch-version", None)
            if not config.get("type"):
                raise DesignError(f"{path}: its newswitch device file {file} names no type")
            bindings = {
                name.removeprefix(BINDING_PREFIX): env["inputs"][name]["value"]
                for name, declaration in design.inputs.items()
                if BINDING_TAG in ((declaration or {}).get("tags") or [])
                and env["inputs"][name]["value"]
            }
            found.append(
                Device(
                    id=str(results["newswitch-device-id"]),
                    type=str(config["type"]),
                    path=path,
                    component=path.split("/")[0],
                    config=config,
                    bindings=bindings,
                )
            )

    design = load_design(dsn)
    unknown = set(values or {}) - set(design.inputs)
    if unknown:
        raise DesignError(
            f"the design has no inputs {sorted(unknown)}; it has {sorted(design.inputs)}"
        )
    walk(design, values or {}, "")
    return found


# ====================
# Joints
# ====================


@dataclass
class Joint:
    """A node of the model that one input moves: along ``axis`` (prismatic) or about it (revolute).

    ``per_unit`` is meters (or radians) per unit of the input; ``axis`` is in the node's own
    frame; at ``rest`` (the input's value the model was built at) the node is where the
    design puts it.
    """

    input: str
    node: str
    kind: str  # prismatic | revolute
    axis: tuple[float, float, float]
    per_unit: float
    rest: float
    units: str | None
    min: float | None
    max: float | None


def _step(placed: dict[str, Placed], path: str) -> np.ndarray:
    """A component's pose relative to the component its pose is relative to."""
    entry = placed[path]
    frame = placed[entry.frame].world if entry.frame else np.eye(4)
    return np.linalg.inv(frame) @ entry.world


def _rotation_vector(r: np.ndarray) -> np.ndarray:
    """Axis times angle of a rotation matrix."""
    angle = math.acos(max(-1.0, min(1.0, (np.trace(r) - 1.0) / 2.0)))
    if angle < 1e-9:
        return np.zeros(3)
    axis = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]])
    if np.linalg.norm(axis) < 1e-9:  # 180 degrees
        w, v = np.linalg.eigh((r + np.eye(3)) / 2.0)
        axis = v[:, np.argmax(w)]
    return axis / np.linalg.norm(axis) * angle


def _motions(
    dsn: Path, rest: dict[str, Any], movable: list[str], placed: dict[str, Placed]
) -> dict[str, list[tuple[str, str, np.ndarray, float]]]:
    """Per component path: (input, kind, axis in the frame's axes, mm-or-rad per unit) for each input its pose follows."""
    motions: dict[str, list[tuple[str, str, np.ndarray, float]]] = {}
    for name in movable:
        nudged = [place(dsn, {**rest, name: rest[name] + step}) for step in (1, 2)]
        for other in nudged:
            if set(other) != set(placed):
                changed = sorted(set(other) ^ set(placed))
                raise DesignError(
                    f"input {name!r} changes which components the design has ({changed[:5]}); pass it as a fixed input"
                )
        for path in placed:
            before, once, twice = (
                _step(placed, path),
                _step(nudged[0], path),
                _step(nudged[1], path),
            )
            turn = _rotation_vector(once[:3, :3] @ before[:3, :3].T)
            shift = once[:3, 3] - before[:3, 3]
            if np.linalg.norm(turn) < 1e-9 and np.linalg.norm(shift) < 1e-9:
                continue
            entry = placed[path]
            if entry.relative and not np.allclose(
                nudged[0][entry.frame].world[:3, :3], placed[entry.frame].world[:3, :3]
            ):
                # optikit keeps a relative-position pose unturned when its parent turns; a node
                # hanging below the turning one would turn with it.
                raise DesignError(
                    f"{path}: input {name!r} turns {entry.frame!r}, which it is placed relative to; "
                    "a relative-position pose under a part that turns is not supported"
                )
            if np.linalg.norm(turn) >= 1e-9:
                if np.linalg.norm(shift) > 1e-6:
                    raise DesignError(
                        f"{path}: input {name!r} both turns and shifts it; only one of them can be a joint"
                    )
                if (
                    np.linalg.norm(_rotation_vector(twice[:3, :3] @ before[:3, :3].T) - 2 * turn)
                    > 1e-6
                ):
                    raise DesignError(
                        f"{path}: input {name!r} turns it, but not in proportion to the input"
                    )
                motion = (
                    name,
                    "revolute",
                    turn / np.linalg.norm(turn),
                    float(np.linalg.norm(turn)),
                )
            else:
                if np.linalg.norm((twice[:3, 3] - before[:3, 3]) - 2 * shift) > 1e-6:
                    raise DesignError(
                        f"{path}: input {name!r} moves it, but not in proportion to the input"
                    )
                motion = (
                    name,
                    "prismatic",
                    shift / np.linalg.norm(shift),
                    float(np.linalg.norm(shift)),
                )
            motions.setdefault(path, []).append(motion)
    for path, found in motions.items():
        if len(found) > 1 and any(kind == "revolute" for _, kind, _, _ in found):
            raise DesignError(
                f"{path}: inputs {[n for n, *_ in found]} all move it, and one of them turns it"
            )
    return motions


# ====================
# The model
# ====================


def node_name(path: str) -> str:
    """``sample-stage/z-plate`` -> ``sample_stage__z_plate``."""
    return "__".join(
        re.sub(r"[^a-z0-9]+", "_", part.lower()).strip("_") for part in path.split("/")
    )


@dataclass
class Model:
    """A design as a GLB, and what of it a blok can bind."""

    glb: bytes
    #: input name -> the joints it moves (usually one)
    joints: dict[str, list[Joint]]
    #: component path -> its node in the GLB (components with geometry or subcomponents)
    components: dict[str, str]
    #: the top design's inputs as declared, with the value the model was built at
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def report(self) -> str:
        lines = ["joints (bind with joints={input: Bind(...)}):"]
        for name, joints in self.joints.items():
            for joint in joints:
                unit = joint.units or ("rad" if joint.kind == "revolute" else "mm")
                lines.append(
                    f"  {name:24} {joint.kind:9} node {joint.node}, rest {joint.rest:g} {unit}, range {joint.min}..{joint.max}"
                )
        lines.append("components (glow=/open=/click= by path):")
        lines.extend(f"  {path:40} node {node}" for path, node in self.components.items())
        return "\n".join(lines)


class _GlbWriter:
    """The output document: parts merged in, meshes shared between copies of one file."""

    def __init__(self) -> None:
        self.doc: dict[str, Any] = {
            "asset": {"version": "2.0", "generator": "optikit_dsn"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [],
            "meshes": [],
            "materials": [DEFAULT_MATERIAL],
            "accessors": [],
            "bufferViews": [],
            "buffers": [{"byteLength": 0}],
        }
        self.bin = bytearray()
        self.parts: dict[
            str, tuple[dict[str, Any], dict[int, int]]
        ] = {}  # sha256 -> (part doc, mesh map)
        self.names: set[str] = set()

    def node(
        self, name: str, matrix: np.ndarray | None = None, parent: int | None = None, **extra: Any
    ) -> int:
        if not NODE_NAME.fullmatch(name):
            raise DesignError(f"node name {name!r} is not [a-z0-9_]+")
        if name in self.names:
            raise DesignError(f"two nodes would be called {name!r}")
        self.names.add(name)
        entry: dict[str, Any] = {"name": name, **extra}
        if matrix is not None:
            translation = (matrix[:3, 3] * 0.001).tolist()
            rotation = _matrix_quaternion(matrix[:3, :3])
            if any(abs(v) > 1e-12 for v in translation):
                entry["translation"] = [round(v, 9) for v in translation]
            if abs(rotation[3] - 1.0) > 1e-12:
                entry["rotation"] = [round(v, 9) for v in rotation]
        self.doc["nodes"].append(entry)
        index = len(self.doc["nodes"]) - 1
        if parent is not None:
            self.doc["nodes"][parent].setdefault("children", []).append(index)
        return index

    def part(self, path: Path) -> tuple[dict[str, Any], dict[int, int]]:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in self.parts:
            return self.parts[digest]
        part, binary = _read_glb(data, str(path))

        views = {}
        for index, view in enumerate(part.get("bufferViews", [])):
            if view.get("buffer", 0) != 0:
                raise DesignError(f"{path}: only one embedded buffer is supported")
            while len(self.bin) % 4:
                self.bin.append(0)
            start = view.get("byteOffset", 0)
            copied = {k: v for k, v in view.items() if k in ("byteLength", "byteStride", "target")}
            copied.update(buffer=0, byteOffset=len(self.bin))
            self.bin.extend(binary[start : start + view["byteLength"]])
            self.doc["bufferViews"].append(copied)
            views[index] = len(self.doc["bufferViews"]) - 1
        accessors = {}
        for index, accessor in enumerate(part.get("accessors", [])):
            if "sparse" in accessor:
                raise DesignError(f"{path}: sparse accessors are not supported")
            copied = {k: v for k, v in accessor.items() if k != "extensions"}
            if "bufferView" in copied:
                copied["bufferView"] = views[copied["bufferView"]]
            self.doc["accessors"].append(copied)
            accessors[index] = len(self.doc["accessors"]) - 1
        materials = {}
        for index, material in enumerate(part.get("materials", [])):
            copied = {
                k: v
                for k, v in material.items()
                if k not in ("extensions", "normalTexture", "occlusionTexture", "emissiveTexture")
            }
            if "pbrMetallicRoughness" in copied:
                copied["pbrMetallicRoughness"] = {
                    k: v
                    for k, v in copied["pbrMetallicRoughness"].items()
                    if not k.endswith("Texture")
                }
            self.doc["materials"].append(copied)
            materials[index] = len(self.doc["materials"]) - 1
        meshes = {}
        for index, mesh in enumerate(part.get("meshes", [])):
            primitives = []
            for primitive in mesh["primitives"]:
                copied = {
                    "attributes": {k: accessors[v] for k, v in primitive["attributes"].items()},
                    "material": materials.get(primitive.get("material"), 0)
                    if "material" in primitive
                    else 0,
                }
                if "indices" in primitive:
                    copied["indices"] = accessors[primitive["indices"]]
                if "mode" in primitive:
                    copied["mode"] = primitive["mode"]
                primitives.append(copied)
            self.doc["meshes"].append({"primitives": primitives})
            meshes[index] = len(self.doc["meshes"]) - 1
        self.parts[digest] = (part, meshes)
        return self.parts[digest]

    def attach(self, path: Path, name: str, parent: int) -> None:
        """The part file's scene under ``parent``, its nodes named after the component."""
        part, meshes = self.part(path)
        scene = part.get("scenes", [{}])[part.get("scene", 0)]
        counter = iter(range(1_000_000))

        def copy(index: int, under: int) -> None:
            source = part["nodes"][index]
            number = next(counter)
            extra = {
                k: source[k] for k in ("translation", "rotation", "scale", "matrix") if k in source
            }
            if "mesh" in source:
                extra["mesh"] = meshes[source["mesh"]]
            created = self.node(
                f"{name}__part" if number == 0 else f"{name}__part_{number}", parent=under, **extra
            )
            for child in source.get("children", []):
                copy(child, created)

        for root in scene.get("nodes", []):
            copy(root, parent)

    def encode(self) -> bytes:
        return _encode_glb(self.doc, self.bin)


def _read_glb(data: bytes, where: str) -> tuple[dict[str, Any], bytes]:
    """A GLB's JSON document and its binary chunk."""
    if data[:4] != b"glTF":
        raise DesignError(f"{where} is not a GLB")
    (json_length,) = struct.unpack_from("<I", data, 12)
    doc = json.loads(data[20 : 20 + json_length])
    chunk = 20 + json_length
    binary = b""
    if chunk < len(data):
        (bin_length,) = struct.unpack_from("<I", data, chunk)
        binary = data[chunk + 8 : chunk + 8 + bin_length]
    return doc, binary


def _encode_glb(doc: dict[str, Any], binary: bytearray) -> bytes:
    while len(binary) % 4:
        binary.append(0)
    doc["buffers"][0]["byteLength"] = len(binary)
    text = json.dumps(doc, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(text), b"JSON")
        + text
        + struct.pack("<I4s", len(binary), b"BIN\x00")
        + bytes(binary)
    )


def build(
    dsn: str | Path, inputs: dict[str, Any] | None = None, fixed: list[str] | None = None
) -> Model:
    """The design as a model with joints.

    ``inputs`` sets top-level inputs (the model's rest pose); ``fixed`` names numeric inputs
    that must not become joints (an input that switches parts in or out has to be fixed).
    """
    dsn = Path(dsn)
    design = load_design(dsn)
    rest: dict[str, Any] = {}
    for name, declaration in design.inputs.items():
        kind = (declaration or {}).get("kind", "float64")
        value = (inputs or {}).get(name, ZERO_VALUES.get(kind))
        rest[name] = _coerce(value, kind, f"input {name}") if value is not None else None
    placed = place(dsn, rest)
    movable = [
        name
        for name, declaration in design.inputs.items()
        if (declaration or {}).get("kind", "float64") in NUMERIC_KINDS and name not in (fixed or [])
    ]
    motions = _motions(dsn, rest, movable, placed)

    writer = _GlbWriter()
    root_name = node_name(dsn.resolve().name.removesuffix(".dsn"))
    root = writer.node(root_name, rotation=Y_UP)
    nodes: dict[str, int] = {"": root}  # component path -> node index (only those with a node)
    worlds: dict[int, np.ndarray] = {root: np.eye(4)}  # node index -> world (top design frame)
    context: dict[str, int] = {
        "": root
    }  # component path -> node its same-design children hang under
    joints: dict[str, list[Joint]] = {}

    def add(name: str, world: np.ndarray, parent: int, **extra: Any) -> int:
        index = writer.node(name, np.linalg.inv(worlds[parent]) @ world, parent, **extra)
        worlds[index] = world
        return index

    for path, entry in placed.items():  # parents come before their children
        frame_world = placed[entry.frame].world if entry.frame else np.eye(4)
        under = nodes[entry.frame] if entry.frame == entry.owner else context[entry.frame]
        step = np.linalg.inv(frame_world) @ entry.world
        for name, kind, axis, per_unit in motions.get(path, []):
            # The joint sits in the frame's axes at the component's origin; it moves the component.
            existing = joints.setdefault(name, [])
            joint_node = (
                node_name(name) if not existing else f"{node_name(name)}_{len(existing) + 1}"
            )
            under = add(joint_node, frame_world @ _transform(np.eye(3), step[:3, 3]), under)
            declaration = design.inputs[name] or {}
            existing.append(
                Joint(
                    input=name,
                    node=joint_node,
                    kind=kind,
                    axis=tuple(round(float(v), 12) for v in axis),
                    per_unit=per_unit * (0.001 if kind == "prismatic" else 1.0),
                    rest=float(rest[name]),
                    units=declaration.get("units"),
                    min=declaration.get("min"),
                    max=declaration.get("max"),
                )
            )
        context[path] = under
        if entry.kind in ("design", "primitive"):
            nodes[path] = add(node_name(path), entry.world, under)
            if entry.gltf is not None:
                writer.attach(entry.gltf, node_name(path), nodes[path])
        # A design component's own children (in its parent's assembly) hang where it does;
        # its subdesign's components hang under its node (see `under` above).

    table = []
    for name, found in joints.items():
        first = found[0]
        for joint in found:
            entry: dict[str, Any] = {
                "name": joint.node,
                "node": joint.node,
                "type": joint.kind,
                "axis": list(joint.axis),
            }
            if joint.min is not None and joint.max is not None:
                ends = sorted(
                    (
                        (float(joint.min) - joint.rest) * joint.per_unit,
                        (float(joint.max) - joint.rest) * joint.per_unit,
                    )
                )
            else:
                ends = [-1.0, 1.0] if joint.kind == "prismatic" else [-math.pi, math.pi]
            entry["limit"] = {"lower": ends[0], "upper": ends[1]}
            if joint is not first:
                entry["mimic"] = {
                    "joint": first.node,
                    "multiplier": joint.per_unit / first.per_unit,
                    "offset": 0.0,
                }
            table.append(entry)
    if table:
        writer.doc["extras"] = {"arkitekt": {"version": 1, "joints": table}}

    declared = {
        name: {**(declaration or {}), "value": rest[name]}
        for name, declaration in design.inputs.items()
    }
    components = {path: writer.doc["nodes"][index]["name"] for path, index in nodes.items() if path}
    return Model(glb=writer.encode(), joints=joints, components=components, inputs=declared)


# ====================
# Simplifying
# ====================

COMPONENT_TYPES = {
    5120: np.int8,
    5121: np.uint8,
    5122: np.int16,
    5123: np.uint16,
    5125: np.uint32,
    5126: np.float32,
}
TYPE_WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
WELD_M = 1e-6  # part GLBs are in meters: vertices closer than a micrometer are one


def _accessor(doc: dict[str, Any], binary: bytes, index: int) -> np.ndarray:
    accessor = doc["accessors"][index]
    view = doc["bufferViews"][accessor["bufferView"]]
    dtype = np.dtype(COMPONENT_TYPES[accessor["componentType"]])
    width = TYPE_WIDTHS[accessor["type"]]
    stride = view.get("byteStride", dtype.itemsize * width)
    offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    shape, strides = (accessor["count"], width), (stride, dtype.itemsize)
    return np.ndarray(shape, dtype=dtype, buffer=binary, offset=offset, strides=strides).copy()


def _decimate(
    points: np.ndarray, faces: np.ndarray, keep: float, min_triangles: int
) -> tuple[np.ndarray, np.ndarray]:
    """One mesh welded and cut down to ``keep`` of its triangles (no fewer than ``min_triangles``).

    CAD exports split a part into one primitive per face, which share no vertices: welded
    first, or no edge between two faces could collapse.
    """
    import pyvista as pv

    mesh = pv.PolyData(
        points.astype(np.float64), np.column_stack([np.full(len(faces), 3), faces]).ravel()
    )
    mesh = mesh.clean(tolerance=WELD_M, absolute=True)
    mesh = pv.PolyData(
        mesh.points, mesh.faces
    )  # without the lines and points clean made of degenerate triangles
    if mesh.n_cells == 0:
        return points.astype(np.float32), faces
    target = max(keep, min_triangles / mesh.n_cells)
    if target < 1.0:
        mesh = mesh.decimate(1.0 - target, volume_preservation=True)
    faces = np.asarray(mesh.regular_faces)
    used, faces = np.unique(faces, return_inverse=True)
    return np.asarray(mesh.points)[used].astype(np.float32), faces.reshape(-1, 3)


def simplify(glb: bytes, keep: float = 0.05, min_triangles: int = 100) -> bytes:
    """The model with every mesh cut down to ``keep`` of its triangles, for a viewer.

    Only the meshes change: nodes, their names, materials and the joint table stay, so a
    blok built for ``build(dsn)`` binds the simplified model just the same. Each mesh
    becomes one primitive per material with positions and indices only: the writer strips
    textures, so the UVs were dead weight, and a mesh without normals is drawn flat-shaded
    (glTF's rule, three.js's GLTFLoader), which keeps a decimated CAD part's edges crisp.
    """
    doc, binary = _read_glb(glb, "the model")
    out = bytearray()
    views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []

    def add(array: np.ndarray, kind: str, target: int, **extra: Any) -> int:
        while len(out) % 4:
            out.append(0)
        views.append(
            {"buffer": 0, "byteOffset": len(out), "byteLength": array.nbytes, "target": target}
        )
        out.extend(array.tobytes())
        component = next(
            code for code, dtype in COMPONENT_TYPES.items() if np.dtype(dtype) == array.dtype
        )
        accessors.append(
            {
                "bufferView": len(views) - 1,
                "componentType": component,
                "count": len(array),
                "type": kind,
                **extra,
            }
        )
        return len(accessors) - 1

    meshes = []
    for index, mesh in enumerate(doc.get("meshes", [])):
        by_material: dict[int, list[tuple[np.ndarray, np.ndarray]]] = {}
        for primitive in mesh["primitives"]:
            if primitive.get("mode", 4) != 4:
                raise DesignError(f"mesh {index}: only triangle meshes can be simplified")
            points = _accessor(doc, binary, primitive["attributes"]["POSITION"])
            if "indices" in primitive:
                faces = _accessor(doc, binary, primitive["indices"]).reshape(-1, 3).astype(np.int64)
            else:
                faces = np.arange(len(points)).reshape(-1, 3)
            by_material.setdefault(primitive.get("material", 0), []).append((points, faces))
        primitives = []
        for material, parts in sorted(by_material.items()):
            offsets = np.cumsum([0] + [len(points) for points, _ in parts])
            points, faces = _decimate(
                np.concatenate([points for points, _ in parts]),
                np.concatenate([faces + offset for (_, faces), offset in zip(parts, offsets)]),
                keep,
                min_triangles,
            )
            positions = add(
                points,
                "VEC3",
                34962,
                min=points.min(axis=0).tolist(),
                max=points.max(axis=0).tolist(),
            )
            indices = add(
                faces.ravel().astype(np.uint16 if len(points) <= 65535 else np.uint32),
                "SCALAR",
                34963,
            )
            primitives.append(
                {"attributes": {"POSITION": positions}, "indices": indices, "material": material}
            )
        meshes.append(
            {**{k: v for k, v in mesh.items() if k != "primitives"}, "primitives": primitives}
        )

    doc.update(meshes=meshes, accessors=accessors, bufferViews=views, buffers=[{"byteLength": 0}])
    return _encode_glb(doc, out)


def triangles(glb: bytes) -> int:
    """How many triangles the model's meshes hold (each mesh once, however many nodes show it)."""
    doc, _ = _read_glb(glb, "the model")
    return sum(
        doc["accessors"][primitive["indices"]]["count"] // 3
        if "indices" in primitive
        else doc["accessors"][primitive["attributes"]["POSITION"]]["count"] // 3
        for mesh in doc.get("meshes", [])
        for primitive in mesh["primitives"]
    )


# ====================
# The blok
# ====================


@dataclass
class Bind:
    """A state value that drives an input: ``value`` is a blok expression (``self.Stage.x``).

    ``unit`` is the unit the state holds the value in (``um``, ``mm``, ``deg``, ``rad`` ...);
    without it the value is taken to be in the input's own units. ``gain`` exaggerates
    the motion on screen only.
    """

    value: str
    unit: str | None = None
    gain: float | None = None


@dataclass
class Glow:
    """A component that glows while ``on`` (a blok expression) is true, in ``color`` (a colour role)."""

    on: str
    color: str | None = None
    intensity: float | None = None


def _attribute(value: str, what: str) -> str:
    """A literal attribute value (``attr="..."``): it cannot hold a double quote."""
    if '"' in value:
        raise ValueError(f"{what}: {value!r} cannot contain a double quote")
    return value


def _factor(unit: str | None, joint: Joint) -> float:
    """Input units per unit of the bound state value."""
    if unit is None or unit == joint.units:
        return 1.0
    table = ANGLE_UNITS if joint.kind == "revolute" else LENGTH_UNITS
    own = joint.units or ("rad" if joint.kind == "revolute" else "mm")
    if unit not in table or own not in table:
        raise ValueError(
            f"cannot convert {unit!r} to {own!r} for input {joint.input!r}; known units are {sorted(table)}"
        )
    return table[unit] / table[own]


def _number(value: float) -> str:
    """A prop value: the renderer reads static props as JSON, which ``1e-06`` is."""
    return f"{value + 0.0:.9g}"  # + 0.0 makes -0.0 a plain 0


def scene(
    model: Model,
    asset: str,
    joints: dict[str, Bind | str] | None = None,
    glow: dict[str, Glow | str] | None = None,
    open: dict[str, str] | None = None,
    click: dict[str, str] | None = None,
    children: str = "",
    camera: str = "iso",
    height: str = "100%",
) -> str:
    """The scene blok's component tree (BSX) for a model, with the app's bindings.

    * ``joints``: input name -> ``Bind`` (or just a blok expression) that drives it;
    * ``glow``: component path -> ``Glow`` (or just a blok expression true while it glows);
    * ``open``: component path -> a blok of this app that a click on it opens, in a popout that is a card
      already (so the blok should not be one);
    * ``click``: component path -> an action call (``self.toggle_laser()``) a click runs;
    * ``children``: more components for inside the ``Model`` (beams, popouts, ...).
    """
    if not asset.isidentifier():
        raise ValueError(f"an asset's name is an identifier, {asset!r} is not one")
    parts: list[str] = []
    for name, binding in (joints or {}).items():
        if name not in model.joints:
            raise ValueError(
                f"the model has no joint for input {name!r}; it has {sorted(model.joints)}"
            )
        binding = Bind(binding) if isinstance(binding, str) else binding
        value = binding.value
        for joint in model.joints[name]:
            tag = "Move" if joint.kind == "prismatic" else "Rotate"
            scale = _factor(binding.unit, joint) * joint.per_unit
            offset = -joint.rest * joint.per_unit
            gain = f" gain={{{_number(binding.gain)}}}" if binding.gain is not None else ""
            parts.append(
                f'<{tag} node="{joint.node}" axis="{" ".join(_number(v) for v in joint.axis)}" value={{{value}}} '
                f"scale={{{_number(scale)}}} offset={{{_number(offset)}}}{gain} />"
            )

    def component(path: str, what: str) -> str:
        if path not in model.components:
            raise ValueError(
                f"{what}: the model has no component {path!r}; it has {sorted(model.components)}"
            )
        return model.components[path]

    for path, binding in (glow or {}).items():
        binding = Glow(binding) if isinstance(binding, str) else binding
        extra = f' color="{_attribute(binding.color, path)}"' if binding.color else ""
        extra += (
            f" intensity={{{_number(binding.intensity)}}}" if binding.intensity is not None else ""
        )
        parts.append(f'<Glow node="{component(path, "glow")}" on={{{binding.on}}}{extra} />')
    both = set(open or {}) & set(click or {})
    if both:
        raise ValueError(
            f"a node takes one click handler: {sorted(both)} are in both open= and click="
        )
    for path, blok in (open or {}).items():
        parts.append(
            f'<OnClick node="{component(path, "open")}" open="{_attribute(blok, path)}" />'
        )
    for path, call in (click or {}).items():
        parts.append(f'<OnClick node="{component(path, "click")}" onClick={{{call}}} />')

    inner = "".join(f"\n        {part}" for part in parts) + (
        f"\n        {children.strip()}" if children.strip() else ""
    )
    return f"""
<Scene camera="{camera}" height="{height}">
    <Model src={{self.assets.{asset}}}>{inner}
    </Model>
</Scene>"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Turn an optikit design into a GLB with joints.")
    parser.add_argument("dsn", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "-i",
        "--input",
        action="append",
        default=[],
        metavar="NAME:VALUE",
        help="a top-level input's rest value",
    )
    parser.add_argument(
        "--fixed",
        action="append",
        default=[],
        metavar="NAME",
        help="a numeric input that must not become a joint",
    )
    parser.add_argument(
        "--simplify",
        type=float,
        metavar="KEEP",
        help="keep this fraction of the triangles (0.05: a twentieth)",
    )
    args = parser.parse_args(argv)
    inputs = dict(item.split(":", 1) for item in args.input)
    model = build(args.dsn, inputs, args.fixed)
    glb = simplify(model.glb, keep=args.simplify) if args.simplify is not None else model.glb
    args.out.write_bytes(glb)
    print(f"wrote {args.out} ({len(glb) / 1e6:.1f} MB, {triangles(glb)} triangles)")
    print(model.report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
