"""Camera description schema.

Defines the geometry, identity and acquisition parameters of a camera as a
Pydantic model. `CameraSchema.model_json_schema()` exports a Draft 2020-12
JSON Schema that can validate raw dicts loaded from JSON or YAML.

Field conventions
-----------------
* A field WITHOUT a default is required.
* A field WITH a default (including ``None``) is optional.
* Some optional fields are *derived* by model validators when omitted
  (pixelpitch y -> x, pixelsize -> pixelpitch). Derivation happens in
  Pydantic, not in the exported JSON Schema.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .bounded import Bounded

# import numpy as np  # noqa: ERA001  -- needed for quantum_efficiency, see below


class Vector2Int(BaseModel):
    """Integer pair, both components required (e.g. pixel counts)."""

    model_config = ConfigDict(extra="forbid")

    x: int = Field(gt=0, description="Extent along x in pixels")
    y: int = Field(gt=0, description="Extent along y in pixels")


class Vector2Float(BaseModel):
    """Float pair where y is optional and falls back to x (square geometry)."""

    model_config = ConfigDict(extra="forbid")

    x: float = Field(gt=0, description="Value along x in micrometers")
    y: Optional[float] = Field(
        default=None, gt=0, description="Value along y; defaults to x when omitted"
    )

    @model_validator(mode="after")
    def _fill_y(self) -> "Vector2Float":
        if self.y is None:
            self.y = self.x
        return self


class Trigger(BaseModel):
    """Trigger configuration. Omit the whole object for free-running mode."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["software", "hardware"]
    edge: Optional[Literal["rising", "falling"]] = None
    level: Optional[Literal["high", "low"]] = None

    @model_validator(mode="after")
    def _check_software(self) -> "Trigger":
        if self.type == "software" and (self.edge or self.level):
            raise ValueError("edge/level are only meaningful for hardware triggers")
        return self


class CameraSchema(BaseModel):
    """Full camera description."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, populate_by_name=True)

    # --- tooling --------------------------------------------------------
    schema_ref: Optional[str] = Field(
        default=None,
        alias="$schema",
        serialization_alias="$schema",
        description="Optional pointer to the schema file, for editor autocomplete",
    )

    # --- identity -------------------------------------------------------
    type: Literal["camera"] = Field(
        default="camera", description="Discriminator used in multi-device files"
    )
    name: str = Field(description="Model designation, e.g. MV-CA023-10UM")
    manufacturer: Optional[str] = Field(default=None, description="Vendor name")
    camera_id: Optional[str] = Field(
        default=None, description="Unique identifier of the physical unit"
    )

    # --- sensor geometry ------------------------------------------------
    pixelcount: Vector2Int = Field(description="Sensor resolution in pixels")
    pixelpitch_um: Vector2Float = Field(
        description="Center-to-center pixel distance; y defaults to x"
    )
    pixelsize_um: Optional[Vector2Float] = Field(
        default=None,
        description="Photosensitive area per pixel; defaults to pixelpitch_um",
    )
    channels: int = Field(default=1, ge=1, description="Color/spectral channels")

    # --- acquisition ----------------------------------------------------
    # Bounded = value + the device's own min/max/increment. A bare number is
    # accepted as shorthand for {"value": <number>}; see bounded.py.
    exposure_time_ms: Optional[Bounded] = Field(
        default=None, description="Integration time in ms, with device limits"
    )
    framerate_per_sec: Optional[Bounded] = Field(
        default=None, description="Frame rate in Hz, with device limits"
    )
    gain_db: Optional[Bounded] = Field(
        default=None, description="Analog gain in dB, with device limits"
    )
    binning: Literal[1, 2, 4] = 1
    roi: Optional[tuple[int, int, int, int]] = Field(
        default=None, description="Region of interest as (x, y, width, height)"
    )
    trigger: Optional[Trigger] = None
    tags: list[str] = Field(default_factory=list)

    # --- spectral response ----------------------------------------------
    # quantum_efficiency: Optional[np.ndarray] = None
    #
    # Enabling this requires ConfigDict(arbitrary_types_allowed=True) and a
    # custom serializer, and the field cannot be expressed in JSON Schema.
    # Preferred JSON-native alternative:
    #     qe_wavelength_nm: Optional[list[float]] = None
    #     qe_values: Optional[list[float]] = None   # 0.0 .. 1.0, same length

    @model_validator(mode="after")
    def _derive_pixelsize(self) -> "CameraSchema":
        if self.pixelsize_um is None:
            self.pixelsize_um = Vector2Float(x=self.pixelpitch_um.x, y=self.pixelpitch_um.y)
        return self

    @model_validator(mode="after")
    def _check_roi(self) -> "CameraSchema":
        if self.roi is not None:
            x, y, w, h = self.roi
            if w <= 0 or h <= 0:
                raise ValueError("roi width and height must be positive")
            if x < 0 or y < 0:
                raise ValueError("roi origin must be non-negative")
            if x + w > self.pixelcount.x or y + h > self.pixelcount.y:
                raise ValueError("roi exceeds sensor pixelcount")
        return self

    # --- convenience ----------------------------------------------------
    @property
    def sensor_size_mm(self) -> tuple[float, float]:
        """Physical sensor extent (width, height) in millimeters."""
        return (
            self.pixelcount.x * self.pixelpitch_um.x / 1000.0,
            self.pixelcount.y * self.pixelpitch_um.y / 1000.0,
        )

    @property
    def fill_factor(self) -> float:
        """Photosensitive area fraction per pixel (0.0 .. 1.0)."""
        ps, pp = self.pixelsize_um, self.pixelpitch_um
        return (ps.x * ps.y) / (pp.x * pp.y)


if __name__ == "__main__":
    import json

    print(json.dumps(CameraSchema.model_json_schema(), indent=2))
