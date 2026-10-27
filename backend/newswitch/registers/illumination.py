"""Registered functions for the illumination. Importing this module registers them."""

from typing import Optional

from rekuest_next.register import register

from newswitch.protocols import IlluminationManager, IlluminationState


@register
def set_illumination_intensity(
    illumination: IlluminationManager,
    intensity: float,
    channel: int = 1,
) -> float:
    """
    Set illumination intensity for a specific channel.

    Args:
        intensity: Light intensity value
        channel: Illumination channel number (default 1)

    Returns:
        The actual clamped intensity value.
    """
    result = illumination.set_intensity(intensity, channel)
    return result


@register
def turn_on_illumination(
    illumination: IlluminationManager,
    state: IlluminationState,
    channel: int = 1,
    intensity: Optional[float] = None,
) -> str:
    """
    Turn on a specific illumination channel.

    Args:
        channel: Illumination channel number (default 1)
        intensity: Optional intensity to set. Uses current/default if not provided.

    Returns:
        Confirmation message.
    """
    result = illumination.turn_on(channel, intensity)
    return result


@register
def turn_off_illumination_channel(
    illumination: IlluminationManager,
    state: IlluminationState,
    channel: int,
) -> str:
    """
    Turn off a specific illumination channel.

    Args:
        channel: Illumination channel number to turn off

    Returns:
        Confirmation message.
    """  # Move stage home when turning off illumination for safety
    result = illumination.turn_off_channel(channel)
    return result
