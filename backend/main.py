"""ASGI entry point. NEWSWITCH_CONFIG selects device YAML; NEWSWITCH_MODE selects hardware/virtual."""

import os
from pathlib import Path
from newswitch.app import ImswitchConfig, create_app


def load_config() -> ImswitchConfig:
    """Use YAML device configuration without a parallel JSON hardware source."""
    overrides = {}
    if source := os.environ.get("NEWSWITCH_CONFIG"):
        path = Path(source).expanduser()
        if path.suffix.lower() not in (".yaml", ".yml"):
            raise ValueError(
                "NEWSWITCH_CONFIG must select a device YAML; legacy JSON startup is unsupported"
            )
        path = path if path.is_absolute() else Path(__file__).resolve().parent / path
        overrides.update(
            config_file=path,
            static_config_path=path,
            persistent_config_path=path.with_name(path.stem + ".persistent" + path.suffix),
            load_from_static_config_path=True,
        )
    if mode := os.environ.get("NEWSWITCH_MODE"):
        if mode not in ("hardware", "virtual"):
            raise ValueError("NEWSWITCH_MODE must be hardware or virtual")
        overrides["use_virtual_microscope"] = mode == "virtual"
    return ImswitchConfig(**overrides)


app = create_app(load_config())
