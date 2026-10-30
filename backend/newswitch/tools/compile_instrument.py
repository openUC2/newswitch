"""Compile an instrument: ray trace it, and write the tables a server reads.

    uv run --with optiland python -m newswitch.tools.compile_instrument instruments/fake-microscope

Needs optiland, which a server never does. Rerun it after changing the description.
"""

import argparse
from pathlib import Path

from newswitch.drivers.optics.simulator import TRUTH_TABLE, optical_errors
from newswitch.instrument.compiler import compile_instrument
from newswitch.instrument.spec import load


def main(argv: list[str] | None = None) -> None:
    """Compile the instrument the command line names."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("instrument", type=Path, help="the instrument's folder")
    args = parser.parse_args(argv)
    instrument = load(args.instrument)
    print(f"wrote {compile_instrument(instrument)}")
    errors = optical_errors(instrument)
    if errors is not None:
        print(f"wrote {compile_instrument(instrument, TRUTH_TABLE, errors)}")


if __name__ == "__main__":
    main()
