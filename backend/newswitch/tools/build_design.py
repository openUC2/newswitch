"""Build a device configuration, UI included, from an optikit design (`newswitch.design.build`).

    just build-design <design.dsn> configs/newswitch-config.<name>.yaml
    uv run python -m newswitch.tools.build_design <design.dsn> -o <file>

Writes what newswitch then runs from: the design's devices, 3D model and bloks, in one
device configuration; checked by reading it back the way newswitch will.
"""

import argparse
from pathlib import Path

from newswitch.design.build import build


def main(argv: list[str] | None = None) -> None:
    """Command line: ``python -m newswitch.tools.build_design <dsn> -o <file>``."""
    parser = argparse.ArgumentParser(
        description="Build a device configuration, UI included, from an optikit design."
    )
    parser.add_argument("dsn", type=Path, help="the optikit design (a .dsn folder)")
    parser.add_argument("-o", "--out", type=Path, required=True, help="the YAML file to write")
    args = parser.parse_args(argv)

    out = build(args.dsn.resolve(), args.out)
    # Read back like newswitch will: what was written must load.
    from newswitch import config_io

    loaded = config_io.load_config(out).config
    assert loaded.ui is not None
    print(
        f"Wrote {out}: {len(loaded.devices)} devices, bloks {', '.join(loaded.ui.bloks)} ({loaded.ui.catalog})"
    )


if __name__ == "__main__":
    main()
