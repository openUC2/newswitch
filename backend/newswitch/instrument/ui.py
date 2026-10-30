"""The ``ui`` and ``agent_ui`` sections of a description: the bloks a server declares."""

from __future__ import annotations

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

STRICT = ConfigDict(extra="forbid")


@dataclass(kw_only=True, config=STRICT)
class BlokEntry:
    """A blok of a UI: its BSX source, exactly as the frontend gets it."""

    bsx: str = Field(description="The blok's tree as BSX source")
    description: str | None = Field(
        default=None, description="Shown in the bottom bar; a view's starts with its tab label"
    )
    default: bool = Field(
        default=False, description="The blok shown first (per context: its root, <Html> or <Scene>)"
    )


@dataclass(kw_only=True, config=STRICT)
class UiConfig:
    """A UI: the bloks, and the catalog they are written against."""

    catalog: str = Field(
        pattern=r"^[A-Za-z0-9_-]+@[A-Za-z0-9_.-]+$",
        description="The catalog the bloks were written against, as <name>@<version>",
    )
    bloks: dict[str, BlokEntry] = Field(description="The bloks, keyed by name")
