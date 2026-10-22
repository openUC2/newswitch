"""The settings newswitch starts with: `ImswitchConfig`, read from `BASE_CONFIG_FILE`.

A leaf module: `newswitch.arkitekt_app` declares it as the app context, and every
module declaring actions, states and contexts imports that.
"""

from pathlib import Path
from typing import Any, Optional

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


#: The base settings file; see the comments in it. Relative folders in it are taken
#: relative to its own folder, so the working directory does not matter.
BASE_CONFIG_FILE = Path(__file__).parent.parent / "base_config.yaml"


class ImswitchConfig(BaseSettings):
    """Configuration for imswitch application, read from `BASE_CONFIG_FILE`.

    Keyword arguments override the file, e.g. ``ImswitchConfig(config_file=None)``.
    Host and port are not part of it; they come from BACKEND_HOST / BACKEND_PORT.
    """

    # extra="forbid": a misspelled key in base_config.yaml is an error, not ignored
    model_config = SettingsConfigDict(extra="forbid")

    use_virtual_microscope: bool
    db_path: str
    available_cubes: list[str]

    config_dir: Path
    """Folder of the device configuration files."""
    schema_dir: Path
    """Folder of the generated schema files."""

    static_config_path: Path
    persistent_config_path: Path
    load_from_static_config_path: bool

    config_file: Optional[Path] = Field(
        default_factory=lambda data: (
            data["static_config_path"]
            if data["load_from_static_config_path"]
            else data["persistent_config_path"]
        )
    )
    """Device configuration read at startup: `static_config_path` or
    `persistent_config_path` (changes always go into the persistent one, see
    `config_io.open_config`). None keeps the built-in virtual devices."""

    camera_recording_dir: Optional[Path] = None
    """Folder the cameras record into (see `managers.uc2.uc2_detector`). None: the default of
    uc2_cam_py (``~/UC2_recordings``)."""

    camera_debug_window: bool = False
    """Show every camera's newest image in a window of uc2_cam_py (debugging without the
    frontend); the cameras then acquire from startup on."""

    # UC2 hardware transport (used when use_virtual_microscope is False).
    # "canopen" (preferred, multi-node CAN bus) or "rest" (single ESP32 master
    # over serial JSON). Both are plug-in replacements behind UC2BusManager.
    uc2_transport: str = "rest"  # "canopen"
    uc2_can_interface: Optional[str] = None  # "socketcan" | "waveshare" | None (auto)
    uc2_can_channel: Optional[str] = "can0"
    uc2_can_port: Optional[str] = None  # Waveshare USB-CAN-A serial port
    uc2_serial_port: Optional[str] = None  # None = autodetect
    uc2_baudrate: int = 962100
    # Detailed per-component overrides, keyed like the corresponding config
    # dataclasses (UC2CanBusConfig / UC2RestBusConfig / UC2StageConfig /
    # UC2IlluminationConfig). Nested values win over the flat fields above.
    # See backend/configs/*.json for complete examples.
    uc2_can: dict[str, Any] = {}
    uc2_rest: dict[str, Any] = {}
    uc2_stage: dict[str, Any] = {}
    uc2_illumination: dict[str, Any] = {}
    uc2_objective: dict[str, Any] = {}
    uc2_filter_bank: dict[str, Any] = {}

    def __init__(self, **values: Any) -> None:  # noqa: ANN401 - passed on to pydantic
        """Read `BASE_CONFIG_FILE`; keyword arguments override single values.

        Declared explicitly so type checkers do not demand every field as an argument:
        the values normally come from the file, which they cannot see.
        """
        super().__init__(**values)

    @model_validator(mode="before")
    @classmethod
    def _drop_comment_keys(cls, data: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        # JSON has no comments, so the files in backend/configs/ carry them as "_comment"
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if not str(key).startswith("_")}
        return data

    @field_validator("config_dir", "schema_dir", "camera_recording_dir")
    @classmethod
    def _relative_to_base_config(cls, path: Optional[Path]) -> Optional[Path]:
        if path is None or path.is_absolute():
            return path
        return BASE_CONFIG_FILE.parent / path

    @field_validator("static_config_path", "persistent_config_path")
    @classmethod
    def _bare_name_in_config_dir(cls, path: Path, info: ValidationInfo) -> Path:
        # an explicit path (absolute, or with a directory part) is taken as given
        if path.is_absolute() or path.parent != Path("."):
            return path
        return info.data["config_dir"] / path

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read keyword arguments, then `BASE_CONFIG_FILE`; never the environment.

        Raises:
            FileNotFoundError: `BASE_CONFIG_FILE` does not exist.
        """
        if not BASE_CONFIG_FILE.is_file():
            raise FileNotFoundError(f"{BASE_CONFIG_FILE} is missing; newswitch needs it to start")
        return (init_settings, YamlConfigSettingsSource(settings_cls, yaml_file=BASE_CONFIG_FILE))
