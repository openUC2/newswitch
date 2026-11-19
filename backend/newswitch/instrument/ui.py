"""The ``ui`` and ``agent_ui`` sections of a description: the bloks a server declares."""

from __future__ import annotations

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

STRICT = ConfigDict(extra="forbid")


@dataclass(kw_only=True, config=STRICT)
class BlokEntry:
    """A blok of a UI: its BSX source, exactly as the frontend gets it."""

    bsx: str = Field(
        description='The blok as BSX source: one <Blok kind="agent" context="panel" catalog="...">'
    )
    description: str | None = Field(
        default=None, description="Shown in the bottom bar; a view's starts with its tab label"
    )
    default: bool = Field(
        default=False, description="The blok shown first (per context: panel, scene or logo)"
    )


@dataclass(kw_only=True, config=STRICT)
class UiConfig:
    """The frontend's UI: the bloks, and the version of the newswitch catalog they are written against.

    Each blok names the catalog in its own root (``<Blok catalog="newswitch">``); ``catalog`` is
    the version of it they were written against, which the frontend's must be at least.
    """

    catalog: str = Field(
        pattern=r"^[A-Za-z0-9_-]+@[A-Za-z0-9_.-]+$",
        description="The catalog the bloks were written against, as <name>@<version>",
    )
    bloks: dict[str, BlokEntry] = Field(description="The bloks, keyed by name")


@dataclass(kw_only=True, config=STRICT)
class AgentUiConfig:
    """Orkestrator's UI: the bloks, each naming in its root the catalog it is written for."""

    bloks: dict[str, BlokEntry] = Field(description="The bloks, keyed by name")
