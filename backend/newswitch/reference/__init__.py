"""The complete reference microscope: one of every part, simulated.

What the tests run on (``tests/conftest.py``): a microscope with every part exercises every action.
What is registered does not depend on it (`newswitch.microscope.registry`).
"""

from pathlib import Path

#: A microscope with every part (and no UI).
REFERENCE_INSTRUMENT = Path(__file__).parent / "complete-microscope"
