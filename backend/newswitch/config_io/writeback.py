"""Merge runtime and firmware values back into the round-trip YAML tree.

Only fields that carry an ``x_unit`` or ``x_firmware`` marker are ever written (see
`devices.field_markers`); everything else in the file is left untouched, including
comments and key order. The rules, per marked field:

* A field whose value changed since loading is written.
* A physical value is written as a mapping: ``value`` whenever it is set, the other members
  only when they differ from their default or were already present. A physical value that is still
  a scalar or ``null`` in the file is turned into such a mapping even when unchanged.
* A field missing from the file is added only when it now carries information, so plain
  defaults are never written.

All inputs are plain dicts produced by ``TypeAdapter(...).dump_python`` -- no dynamic
attribute access on the dataclasses.
"""

from __future__ import annotations

from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .document import to_plain
from .values import PHYS_VAL_DEFAULTS

PHYS_MEMBERS = ("value", "min", "max", "inc", "unit", "preset_vals")


def to_yaml_node(value: Any) -> Any:  # noqa: ANN401 - mirrors the input
    """Turn a dumped field value into something ruamel can write nicely.

    Tuples become flow-style sequences (``[1920, 1200]``); lists of scalars likewise.

    Args:
        value: A plain value from ``dump_python``.

    Returns:
        A ruamel-compatible node.
    """
    if isinstance(value, dict):
        node = CommentedMap()
        for key, item in value.items():
            node[key] = to_yaml_node(item)
        return node
    if isinstance(value, (tuple, list)):
        seq = CommentedSeq(to_yaml_node(item) for item in value)
        if all(not isinstance(item, (dict, list, tuple)) for item in value):
            seq.fa.set_flow_style()
        return seq
    return value


def _pop_trailing_comment(node: Any) -> Any:  # noqa: ANN401 - ruamel internals
    """Detach the comment/blank lines that follow the last entry of a block collection.

    ruamel stores the blank line separating two devices as a comment on the deepest
    last entry. Appending a key would leave that separator *above* the new key.

    Args:
        node: A mapping or sequence of the tree.

    Returns:
        The detached comment token, or None when there was none.
    """
    if not isinstance(node, (CommentedMap, CommentedSeq)) or len(node) == 0:
        return None
    if node.fa.flow_style():
        return None
    last = list(node.keys())[-1] if isinstance(node, CommentedMap) else len(node) - 1
    token = _pop_trailing_comment(node[last])
    if token is not None:
        return token
    slots = node.ca.items.get(last)
    index = 2 if isinstance(node, CommentedMap) else 0
    if slots is None or len(slots) <= index or slots[index] is None:
        return None
    token, slots[index] = slots[index], None
    return token


def _attach_trailing_comment(node: CommentedMap, key: str, token: Any) -> None:  # noqa: ANN401
    """Attach a detached trailing comment after `key` (or inside its block value).

    Args:
        node: The mapping `key` lives in.
        key: The key that is now last.
        token: Output of `_pop_trailing_comment`.
    """
    value = node[key]
    if isinstance(value, CommentedMap) and len(value) and not value.fa.flow_style():
        _attach_trailing_comment(value, list(value.keys())[-1], token)
        return
    node.ca.items.setdefault(key, [None, None, None, None])[2] = token


def set_key(node: CommentedMap, key: str, value: Any) -> None:  # noqa: ANN401 - YAML node
    """Set `key` in a tree mapping; a new key keeps the separator lines below it.

    Args:
        node: Mapping of the tree; modified in place.
        key: Key to set.
        value: New node.
    """
    if key in node:
        node[key] = value
        return
    token = _pop_trailing_comment(node)
    node[key] = value
    if token is not None:
        _attach_trailing_comment(node, key, token)


def phys_carries_information(phys: dict[str, Any] | None) -> bool:
    """True when a dumped physical value says anything beyond its defaults.

    Args:
        phys: Dumped `PhysVal`, or None.

    Returns:
        Whether writing it would add information to the file.
    """
    if phys is None:
        return False
    if phys.get("value") is not None:
        return True
    return any(
        phys.get(member) != default
        for member, default in PHYS_VAL_DEFAULTS.items()
        if member != "unit"
    )


def _write_phys(node: CommentedMap, name: str, old: Any, new: Any) -> None:  # noqa: ANN401
    """Write one physical-value field into `node` following the module rules.

    Args:
        node: Mapping of the device or axis in the tree.
        name: Field name.
        old: Dumped value at load time (dict or None).
        new: Dumped current value (dict or None).
    """
    present = name in node
    current = node[name] if present else None
    is_mapping = isinstance(current, dict)

    if new is None:
        return  # nothing to say; a dropped or absent value never removes what is written
    if not present and not phys_carries_information(new):
        return
    if is_mapping and new == old:
        return  # already a mapping and unchanged

    target: CommentedMap = current if is_mapping else CommentedMap()
    for member in PHYS_MEMBERS:
        value = new.get(member)
        if member == "value":
            wanted = value is not None or member in target
        else:
            wanted = member in target or value != PHYS_VAL_DEFAULTS[member]
        if wanted and (member not in target or to_plain(target[member]) != value):
            target[member] = to_yaml_node(value)
    if not is_mapping:
        set_key(node, name, target)


def _write_plain(node: CommentedMap, name: str, old: Any, new: Any) -> None:  # noqa: ANN401
    """Write one non-physical marked field when it changed since loading.

    Args:
        node: Mapping of the device or axis in the tree.
        name: Field name.
        old: Dumped value at load time.
        new: Dumped current value.
    """
    if new == old:
        return
    if name not in node and new is None:
        return
    if name in node and to_plain(node[name]) == to_plain(to_yaml_node(new)):
        return
    set_key(node, name, to_yaml_node(new))


def merge_fields(
    node: CommentedMap,
    markers: dict[str, dict[str, Any]],
    old: dict[str, Any],
    new: dict[str, Any],
) -> None:
    """Merge every marked field of one device (or axis) into its tree node.

    Args:
        node: Mapping of the device or axis in the tree; modified in place.
        markers: Output of `devices.field_markers` for its class.
        old: Dumped device/axis at load time.
        new: Dumped current device/axis.
    """
    for name, marker in markers.items():
        if "x_unit" in marker:
            _write_phys(node, name, old.get(name), new.get(name))
        else:
            _write_plain(node, name, old.get(name), new.get(name))


def merge_phys_from_firmware(
    current: dict[str, Any] | None, reported: dict[str, Any], kind: str
) -> dict[str, Any]:
    """Merge the members a device reported into a dumped physical value.

    Args:
        current: Dumped current value, or None.
        reported: Dumped `PhysVal` as reported by the firmware (already in the field's
            unit); only the members present in it are taken over.
        kind: ``"limits"`` keeps the user-owned ``value``; ``"full"`` takes it too.

    Returns:
        The merged dumped value.
    """
    merged = dict(current) if current is not None else {}
    for member in PHYS_MEMBERS:
        if member not in reported:
            continue
        if member == "value" and kind == "limits":
            continue
        merged[member] = reported[member]
    return merged
