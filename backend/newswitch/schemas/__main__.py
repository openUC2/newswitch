"""Inspect config files from the shell.

    python -m newswitch.schemas                       # the default Devices.yml
    python -m newswitch.schemas Devices.yml hik_mv_ca023_10um
    python -m newswitch.schemas /path/to/Devices.json

Every argument is a bare config name (resolved against the managed config directory)
or an explicit path, and may hold a single device or a whole registry.
"""

from __future__ import annotations

import sys

from .device_io import describe
from .errors import ConfigError
from .loader import load_config


def main(args: list[str]) -> int:
    """Print one description block per file.

    Args:
        args: File names or paths; defaults to ``["Devices.yml"]``.

    Returns:
        Process exit code: 0 if every file validated, 1 otherwise.
    """
    failed = False
    for arg in args or ["Devices.yml"]:
        try:
            print(describe(load_config(arg)))
        except ConfigError as exc:
            failed = True
            print(f"[FAIL] {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
