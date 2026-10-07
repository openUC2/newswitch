"""Inspect the configuration from the shell.

python -m newswitch.config_io                        # ImswitchConfig().config_file
python -m newswitch.config_io path/to/other.yaml
python -m newswitch.config_io --export-schema        # regenerate the YAML schema

The defaults come from ``backend/base_config.yaml`` via `newswitch.app.ImswitchConfig`.
"""

from __future__ import annotations

import argparse
import sys

from .config_file import load_config
from .devices import NewswitchConfig
from .errors import ConfigError
from .validation import SCHEMA_FILE_NAME, export_schema


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
    # imported here, not at module level: newswitch.app itself imports config_io
    from newswitch.app import ImswitchConfig

    parser = argparse.ArgumentParser(prog="python -m newswitch.config_io")
    parser.add_argument("file", nargs="?", help="config file (default: base_config.yaml)")
    parser.add_argument("--export-schema", action="store_true", help="write the YAML schema")
    args = parser.parse_args(argv)

    settings = ImswitchConfig()
    if args.export_schema:
        print(f"wrote {export_schema(settings.schema_dir / SCHEMA_FILE_NAME)}")
        return 0
    file = args.file or settings.config_file
    if file is None:
        print("[FAIL] no config file given and none configured")
        return 1
    try:
        print(describe(load_config(file).config))
    except ConfigError as exc:
        print(f"[FAIL] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
