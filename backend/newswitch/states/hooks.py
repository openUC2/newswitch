"""The hook state: the hooks registered with the hook manager."""

from dataclasses import dataclass, field

from newswitch.models.hooks import RegisteredHook


@dataclass
class HookState:
    """Shared state for camera parameters.

    Default values are set to produce visible images with default illumination.
    Higher exposure and gain ensure the captured images have sufficient
    brightness after uint16→uint8 conversion for PNG output.
    """

    registered_hooks: list[RegisteredHook] = field(default_factory=lambda: [])
