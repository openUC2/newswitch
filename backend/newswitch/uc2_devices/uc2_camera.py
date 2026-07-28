"""
uc2_camera.py — Abstract base class for UC2 camera drivers.

This is the *driver / control* layer. It is deliberately independent of rekuest:
a ``Uc2Camera`` talks to a vendor SDK (HIK MVS, Basler pylon, ...) and exposes a
uniform interface that the ``Uc2DetectorManager`` composes with the rekuest
``Detector`` dataclass / ``CameraState``.

Design boundaries (see architecture discussion):
  * Control lives here: connect, exposure, gain, framerate, ROI, start/stop.
  * The high-throughput frame path (streaming / recording at full rate) runs in
    the native C++ engine. This class *configures* it, *starts/stops* it and
    *reports capabilities* (DMA, pixel format). It does NOT pull every frame in
    Python. ``grab_frame()`` is only for snapshots / moderate-rate captures.
  * ROI is applied on the camera / in the native layer, never cropped per frame
    in Python.

Why an ABC (not a Protocol)? Because camera drivers share real, non-trivial
logic — variance, saving (TIFF/Zarr), settings application, lifecycle — which
lives here once. Only the vendor-specific bits are abstract.
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

if TYPE_CHECKING:  # avoid a runtime import cycle with settings.py
    from .settings import Uc2CameraSettings


# --------------------------------------------------------------------------- #
# Native ring-buffer extension (read side only).
#
# The full-rate frame path lives in the C++ ``uc2::RingBuffer`` and is exposed to
# Python via the compiled ``_ringbuffer`` module. The wheel installs it next to
# the package as ``newswitchSources.uc2_devices._ringbuffer`` (see the root
# ``CMakeLists.txt`` ``install(... DESTINATION newswitchSources/uc2_devices)``,
# and how ``hik_camera.py`` imports ``_hikcam`` from the same place).
#
# The import is guarded so the pure-Python driver layer stays importable even
# where the native module has not been built; ``create_ring_buffer`` / the read
# methods raise a clear error in that case.
# --------------------------------------------------------------------------- #
_RINGBUFFER_MISSING_MSG = (
    "The native '_ringbuffer' extension is not available in this environment. "
    "Build the wheel (scikit-build-core / pybind11) so that "
    "'newswitchSources.uc2_devices._ringbuffer' is importable."
)


def _load_ringbuffer_module() -> Optional[Any]:
    """Import the compiled ``_ringbuffer`` extension, or return ``None``.

    Tries the installed location first, then a couple of fallbacks so an
    out-of-tree build (a bare ``.so`` on ``sys.path``) still works — mirroring
    ``tests/test_ringbuffer_py.py``.
    """
    for name in (
        "newswitchSources.uc2_devices._ringbuffer",
        "newswitch.uc2_devices._ringbuffer",
        "_ringbuffer",
    ):
        try:
            return importlib.import_module(name)
        except Exception:  # noqa: BLE001 - any failure means "not available here"
            continue
    return None


_ringbuffer = _load_ringbuffer_module()


def _coerce_image_norm(value: Any) -> Any:
    """Resolve an ``ImageNorm`` from the enum, its name, or ``None`` (=> no norm).

    Accepts the extension enum directly, a case-insensitive name (``"variance"``,
    ``"none"`` -> ``None_``), or ``None`` for the default ``ImageNorm.None_``.
    """
    if _ringbuffer is None:
        raise RuntimeError(_RINGBUFFER_MISSING_MSG)
    if value is None:
        return _ringbuffer.ImageNorm.None_
    if isinstance(value, str):
        if value.lower() in ("none", "none_"):
            return _ringbuffer.ImageNorm.None_
        # Members are single title-cased words (Variance, Max, Mean, ...).
        return getattr(_ringbuffer.ImageNorm, value.capitalize())
    return value


def _coerce_blocked_strategy(value: Any) -> Any:
    """Resolve a ``BlockedStrategy`` from the enum, its name, or ``None`` (=> Jump)."""
    if _ringbuffer is None:
        raise RuntimeError(_RINGBUFFER_MISSING_MSG)
    if value is None:
        return _ringbuffer.BlockedStrategy.Jump
    if isinstance(value, str):
        return getattr(_ringbuffer.BlockedStrategy, value.capitalize())
    return value


class Interface(str, Enum):
    """Physical camera interface (informational)."""

    USB3 = "usb3"
    GIGE = "gige"
    COAXPRESS = "coaxpress"
    OTHER = "other"


@dataclass(frozen=True)
class CameraInfo:
    """Identity + high-level capabilities of a discovered camera."""

    vendor: str
    model: str
    serial: str
    interface: Interface = Interface.OTHER
    supports_dma: bool = False


@dataclass(frozen=True)
class FrameFormat:
    """Describes the shape and type of one frame.

    ``bit_depth`` (significant bits) and ``dtype`` (storage) are kept separate on
    purpose: a 12-bit sensor typically delivers ``uint16`` data with only 12
    significant bits. ``channels`` is an arbitrary integer (1 = mono, 3 = RGB,
    N = multispectral) — not limited to 1 or 3.
    """

    width: int
    height: int
    channels: int = 1
    dtype: str = "uint16"  # uint8 / uint16 / uint32 / float32 / float64 / ...
    bit_depth: int = 16  # significant bits: 8, 10, 12, 14, 16, 32, 64, ...

    def numpy_shape(self, frames: int = 1) -> tuple[int, ...]:
        """Return the numpy shape for one frame or a stack of ``frames``."""
        base = (
            (self.height, self.width)
            if self.channels == 1
            else (self.height, self.width, self.channels)
        )
        return base if frames == 1 else (frames, *base)

    def bytes_per_frame(self) -> int:
        return int(np.dtype(self.dtype).itemsize) * self.width * self.height * max(self.channels, 1)


@dataclass
class Roi:
    """Region of interest, applied on hardware / in the native layer."""

    x: int
    y: int
    width: int
    height: int


class Uc2Camera(ABC):
    """Abstract base for all UC2 camera drivers.

    Subclasses (e.g. ``HikCamera``) implement the vendor-specific methods; the
    shared logic (variance, saving, settings application, lifecycle) is provided
    here.
    """

    def __init__(self, info: CameraInfo, settings: "Uc2CameraSettings | None" = None) -> None:
        self._info = info
        self._settings = settings
        self._roi: Optional[Roi] = None
        # Full-rate frame path: the native C++ engine writes into this ring
        # buffer; Python only reads from it (see the ring-buffer section below).
        self._ring_buffer: Optional[Any] = None

    # ------------------------------------------------------------------ #
    # discovery
    # ------------------------------------------------------------------ #
    @classmethod
    @abstractmethod
    def enumerate(cls) -> list[Uc2Camera]:
        """Return all cameras of this type currently attached to the system."""

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    @abstractmethod
    def connect(self) -> None:
        """Open the device and read its capabilities (format, DMA, ...)."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the device and release all SDK handles."""

    @abstractmethod
    def start(self) -> None:
        """Start acquisition / streaming."""

    @abstractmethod
    def stop(self) -> None:
        """Stop acquisition / streaming."""

    # ------------------------------------------------------------------ #
    # parameters
    # ------------------------------------------------------------------ #
    @abstractmethod
    def set_exposure_time(self, seconds: float) -> None: ...

    @abstractmethod
    def set_gain(self, gain: float) -> None: ...

    @abstractmethod
    def set_framerate(self, fps: float) -> None: ...

    @abstractmethod
    def set_roi(self, roi: Optional[Roi]) -> None:
        """Configure ROI on the camera / native layer (``None`` = full frame).

        The ROI is applied at readout (hardware) or in the native engine — it is
        never cropped per frame in Python. Implementations should also store the
        value via ``self._roi = roi`` so ``get_roi()`` stays consistent.
        """

    def get_roi(self) -> Optional[Roi]:
        return self._roi

    # ------------------------------------------------------------------ #
    # frames
    # ------------------------------------------------------------------ #
    @abstractmethod
    def grab_frame(self) -> np.ndarray:
        """Grab a single frame (snapshot / moderate rate).

        The full-rate stream does NOT go through this method — the native engine
        pulls frames via ``acquisition_handle()``.
        """

    @abstractmethod
    def acquisition_handle(self) -> Any:
        """Return an opaque handle the native engine uses to pull frames.

        For DMA-capable cameras this exposes the DMA / pinned buffer (zero-copy);
        otherwise it exposes a copy-based grabber. The native side branches on
        ``self.supports_dma``.
        """

    # ------------------------------------------------------------------ #
    # ring buffer — full-rate frame read path (native _ringbuffer)
    #
    # The high-throughput stream is written by the C++ engine into a
    # ``uc2::RingBuffer``; Python only ever *reads*. These methods make the
    # buffer's read side (frames + metadata) available on every ``Uc2Camera``
    # and any subclass. They are the counterpart of ``grab_frame()``: use
    # ``grab_frame()`` for a one-off snapshot, use the ring buffer for the
    # sustained full-rate stream (live view / recording, LiveKit hand-off).
    # ------------------------------------------------------------------ #
    @staticmethod
    def ringbuffer_available() -> bool:
        """Whether the native ``_ringbuffer`` extension was importable."""
        return _ringbuffer is not None

    def create_ring_buffer(
        self,
        buffer_size: int,
        *,
        name: str = "",
        image_norm: Any = None,
        strategy_if_frame_is_blocked: Any = None,
        rearrange_channels: bool = False,
        save_file_path: str = "",
        save_file_chunk_size: int = 0,
    ) -> Any:
        """Create the ring buffer that the native engine writes frames into.

        Its geometry (sample size, channel count, ROI = stored frame size) is
        derived from this camera's :pyattr:`frame_format` and current ROI, so
        ``connect()`` (and any ``set_roi``) must run first. The instance is
        stored on ``self`` and returned; subsequent calls replace it.

        ``image_norm`` / ``strategy_if_frame_is_blocked`` accept the extension
        enums, their (case-insensitive) names, or ``None`` for the defaults
        (``ImageNorm.None_`` / ``BlockedStrategy.Jump``).
        """
        if _ringbuffer is None:
            raise RuntimeError(_RINGBUFFER_MISSING_MSG)

        fmt = self.frame_format
        byte_size = int(np.dtype(fmt.dtype).itemsize)

        roi = self._roi
        if roi is not None:
            row_offset, col_offset = roi.y, roi.x
            roi_height, roi_width = roi.height, roi.width
        else:
            row_offset, col_offset = 0, 0
            roi_height, roi_width = fmt.height, fmt.width

        self._ring_buffer = _ringbuffer.RingBuffer(
            name=name or self._info.serial,
            buffer_size=buffer_size,
            byte_size=byte_size,
            channel_count=max(fmt.channels, 1),
            roi_row_offset=row_offset,
            roi_col_offset=col_offset,
            roi_height=roi_height,
            roi_width=roi_width,
            save_file_path=save_file_path,
            save_file_chunk_size=save_file_chunk_size,
            rearrange_channels=rearrange_channels,
            image_norm=_coerce_image_norm(image_norm),
            strategy_if_frame_is_blocked=_coerce_blocked_strategy(strategy_if_frame_is_blocked),
        )
        return self._ring_buffer

    def attach_ring_buffer(self, ring_buffer: Any) -> None:
        """Attach an externally-created ``_ringbuffer.RingBuffer`` to this camera.

        Use this when the buffer is owned elsewhere (e.g. handed over by the
        native engine) instead of created via :pymeth:`create_ring_buffer`.
        """
        self._ring_buffer = ring_buffer

    @property
    def has_ring_buffer(self) -> bool:
        """Whether a ring buffer has been created/attached on this camera."""
        return self._ring_buffer is not None

    @property
    def ring_buffer(self) -> Any:
        """The attached ring buffer (raises if none has been created/attached)."""
        return self._require_ring_buffer()

    def _require_ring_buffer(self) -> Any:
        if self._ring_buffer is None:
            raise RuntimeError(
                "No ring buffer on this camera. Call create_ring_buffer(...) "
                "(or attach_ring_buffer(...)) first."
            )
        return self._ring_buffer

    # --- read side (frames) ------------------------------------------- #
    def read(self, index: int) -> Optional[np.ndarray]:
        """Copy frame ``index`` out of the ring buffer as an owning numpy array.

        Shape is ``(H, W)`` / ``(H, W, C)`` (interleaved) or ``(C, H, W)`` (if
        the buffer de-interleaves channels). Returns ``None`` if the frame is
        currently blocked or the index is out of range.
        """
        return self._require_ring_buffer().read(index)

    def read_last_ready(self) -> Optional[np.ndarray]:
        """Copy the newest fully-ready frame (``None`` if none/blocked).

        This is the realtime "drop-old" read used by the live-view / LiveKit
        path.
        """
        return self._require_ring_buffer().read_last_ready()

    # --- read side (metadata) ----------------------------------------- #
    def read_metadata(self, index: int) -> dict:
        """Timestamps + per-channel image norm of frame ``index``.

        The returned dict has ``valid=False`` if the frame is blocked/out of
        range. Keys: ``valid``, ``frame_count``, ``timestamp_start_ns``,
        ``timestamp_stop_ns``, ``image_norm``.
        """
        return self._require_ring_buffer().read_metadata(index)

    def read_metadata_last_ready(self) -> dict:
        """Timestamps + per-channel image norm of the newest ready frame."""
        return self._require_ring_buffer().read_metadata_last_ready()

    # --- read-only introspection -------------------------------------- #
    @property
    def buffer_size(self) -> int:
        """Number of frame slots in the ring buffer."""
        return self._require_ring_buffer().buffer_size

    @property
    def index_of_last_ready_frame(self) -> int:
        """Index of the last fully-written (post-processed) frame, or ``-1``."""
        return self._require_ring_buffer().index_of_last_ready_frame

    # ------------------------------------------------------------------ #
    # capabilities
    # ------------------------------------------------------------------ #
    @property
    def info(self) -> CameraInfo:
        return self._info

    @property
    def supports_dma(self) -> bool:
        return self._info.supports_dma

    @property
    @abstractmethod
    def frame_format(self) -> FrameFormat: ...

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @property
    @abstractmethod
    def is_running(self) -> bool: ...

    # ------------------------------------------------------------------ #
    # context manager + misc
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "Uc2Camera":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.disconnect()

    def describe(self) -> str:
        f = self.frame_format
        return (
            f"{self._info.vendor} {self._info.model} [{self._info.serial}] "
            f"{f.width}x{f.height}x{f.channels} {f.bit_depth}bit "
            f"dtype={f.dtype} dma={self.supports_dma}"
        )
