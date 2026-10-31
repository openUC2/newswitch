"""What an acquisition is asked to do: a plan, a region scan."""

from dataclasses import dataclass
from enum import Enum

from arkitekt import model_field, withValidator

from newswitch.models.hooks import Hook


class PositionOrder(str, Enum):
    """Defines the order in which stage positions are visited during acquisition."""

    SEQUENTIAL = "sequential"
    RANDOM = "random"


@dataclass
class AcquisitionChannel:
    """One thing to see: what to set for it, and the detectors that take an image of it."""

    detectors: list[str] = model_field(
        default_factory=list,
        validators=[
            withValidator(
                "len(value) > 0",
                error_message="We need at least one detector to acquire this channel",
            )
        ],
        description="The detectors that image it, by name; each becomes channels of the dataset.",
    )
    name: str = model_field(
        default="",
        description="What it shows (e.g., 'GFP'): the start of its channels' labels.",
    )
    set_to: dict[str, float] = model_field(
        default_factory=dict,
        description="What to set for it, by variable (e.g., 'laser_488.power', 'filter.slot'). A "
        "source it does not name is off.",
    )


@dataclass
class AcquisitionPosition:
    """One place to go: each is a dataset of its own."""

    set_to: dict[str, float] = model_field(
        default_factory=dict,
        description="What to set to get there, by variable (e.g., 'stage.x'); nothing: stay.",
    )
    name: str = model_field(default="", description="What to call it.")


@dataclass
class AcquisitionStack:
    """Planes around where a position is."""

    offsets: list[float] = model_field(
        default_factory=list,
        description="Where the planes are, from where the position is; none: one plane, there.",
    )
    variable: str | None = model_field(
        default=None,
        description="What to sweep; by default what focuses, if it is clear which that is.",
    )


@dataclass
class AcquisitionPlan:
    """What to acquire: every channel, on every plane, at every position, every time."""

    channels: list[AcquisitionChannel] = model_field(
        default_factory=list,
        description="What to see at each plane.",
        validators=[
            withValidator(
                "len(value) > 0",
                error_message="You need at least one channel to perform an acquisition",
            )
        ],
    )
    positions: list[AcquisitionPosition] = model_field(
        default_factory=lambda: [AcquisitionPosition()],
        description="Where to go; each is a dataset of its own.",
        validators=[
            withValidator(
                "len(value) > 0",
                error_message="You need at least one position to perform an acquisition",
            )
        ],
    )
    stack: AcquisitionStack = model_field(
        default_factory=AcquisitionStack, description="Which planes to take at each position."
    )
    times: int = model_field(default=1, description="How many times to do all of it.")
    every_s: float = model_field(
        default=0.0,
        description="Seconds from the start of one time to the next; 0: right after it.",
    )
    order: PositionOrder = model_field(
        default=PositionOrder.SEQUENTIAL, description="In which order to visit the positions."
    )
    name: str = model_field(
        default="acquisition",
        description="Name of the datasets; with several positions, each gets its position's.",
    )
    m_hooks: list[Hook] = model_field(
        default_factory=list, description="What to run at the start (e.g., an autofocus)."
    )
    t_hooks: list[Hook] = model_field(default_factory=list, description="What to run each time.")
    p_hooks: list[Hook] = model_field(
        default_factory=list, description="What to run at each position, on arrival."
    )
    z_hooks: list[Hook] = model_field(
        default_factory=list, description="What to run at each plane."
    )


@dataclass
class AcquiredDataset:
    """A dataset an acquisition created, in the store it went to."""

    id: str
    name: str
    position: int = model_field(description="Which position of the acquisition it holds, from 0")


class ScanOrder(str, Enum):
    """Defines the order in which stage positions are visited during acquisition."""

    SNAKE_ROW = "SNAKE_ROW"
    SNAKE_COL = "SNAKE_COL"
    RASTER_ROW = "RASTER_ROW"
    RASTER_COL = "RASTER_COL"
