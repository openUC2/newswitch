"""Inspect the configuration from the shell.

python -m newswitch.config_io                        # managed newswitch-config.yaml
python -m newswitch.config_io path/to/other.yaml
python -m newswitch.config_io --export-schema        # regenerate the YAML schema
"""

from __future__ import annotations

import argparse
import sys

from .config_file import load_config
from .devices import NewswitchConfig
from .document import DEFAULT_CONFIG_NAME
from .errors import ConfigError
from .validation import export_schema


def describe(config: NewswitchConfig) -> str:
    """One human-readable line per device.

    Args:
        config: A loaded configuration.

    Returns:
        The description, one device per line.
    """
    lines = [f"newswitch_version: {config.newswitch_version}"]
    for key, device in config.devices.items():
        lines.append(f"  [{device.type:<11}] slot {config.slot_of(key):<2} {key:<24} {device.name}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    """Validate a config file or export the schema.

    Args:
        argv: Command-line arguments without the program name.

    Returns:
        Process exit code: 0 on success, 1 when the file is invalid.
    """
    parser = argparse.ArgumentParser(prog="python -m newswitch.config_io")
    parser.add_argument("file", nargs="?", default=DEFAULT_CONFIG_NAME)
    parser.add_argument("--export-schema", action="store_true", help="write the YAML schema")
    args = parser.parse_args(argv)

    if args.export_schema:
        print(f"wrote {export_schema()}")
        return 0
    try:
        print(describe(load_config(args.file).config))
    except ConfigError as exc:
        print(f"[FAIL] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
