"""Every description in ``instruments/expected-failures/refused`` stops a server, for its reason.

Each file is a working microscope but for one mistake, and says what must be said about it in its
``# expected:`` lines. A new way of being refused is one more file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from newswitch.instrument import spec
from newswitch.microscope.parts import build_microscope
from tests.conftest import run_settings

REFUSED = sorted(
    (Path(__file__).parent.parent / "instruments/expected-failures/refused").glob("*.yml")
)


def expected_of(path: Path) -> list[str]:
    """What a file says must be said about it."""
    return re.findall(r"^# expected: (.+)$", path.read_text(), re.M)


def test_there_are_some() -> None:
    """Or the test below would pass by having nothing to do."""
    assert REFUSED


@pytest.mark.parametrize("path", REFUSED, ids=lambda path: path.stem)
def test_it_is_refused(path: Path, tmp_path: Path) -> None:
    """Whether by parsing it or by starting what it describes, as a server does."""
    expected = expected_of(path)
    assert expected, f"{path.name} says nothing about why it is refused"
    with pytest.raises(spec.SpecError) as info:
        instrument = spec.load(path)
        build_microscope(run_settings(tmp_path, simulate=instrument.settings.simulate), instrument)
    for finding in expected:
        assert finding in str(info.value)
