"""A record streamed into mikro as it is taken: each exposure written natively into its datalayer.

mikro stores an array as zarr v3 under a prefix it grants (``requestZarrUpload``: temporary S3
credentials scoped to ``bucket/key/``), checks it on ``finishZarrUpload``, and a dataset is made of
the store's id. Its own client uploads a whole array at the end; here each exposure goes from where
the camera put it (`FrameMemory`, a ring slot by address) into `newswitch_native.ShardedUpload`,
which copies it once, encodes it into its shard (zstd, crc32c index: zarr's own layout) and PUTs
it in the background, through the datalayer's endpoint and the mesh's proxy, with the grant's
credentials. So nothing of a record is held until the acquisition ends, and the pixels do not pass
through Python.

The grant is refreshed (``refreshZarrUpload``) on the next write once three quarters of its time
have passed: from the acquisition's own thread, which can call the server; a timer's could not.

A record may be stored with its pyramid (``levels``): each coarser level an array of its own, with
a grant of its own, which the native writer makes of each exposure as it stores it (``y`` and
``x`` halved, by ``reduction``: `mikro.pyramid`'s). Each level states where it sits in level 0's
grid (`placement`), as `mikro.dataset_arrays` would have.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Literal

from mikro import Mikro

from newswitch.protocols.dataset_store import FrameMemory

logger = logging.getLogger(__name__)

#: How much may be written and not yet stored, over every record streamed at once (they share
#: one `newswitch_native.InFlightBudget`): what a write waits for beyond it. About twenty 12 MP
#: color frames with their pyramids: a z-stack's burst, taken at the camera's pace while the
#: upload catches up. Less where memory is short (`in_flight_limit`).
MAX_IN_FLIGHT_BYTES = 1024**3
#: The share of the memory available that frames in flight may take: the rest of the run, and
#: what else runs on the machine, must not be pushed into swap by them.
IN_FLIGHT_SHARE = 0.5
#: When in a grant's life it is refreshed, as a share of it.
REFRESH_AT = 0.75
#: A pyramid is halved until its coarsest level fits one tile of this side (the writer's inner
#: chunk): what a viewer reads at once.
TILE = 256

Reduction = Literal["max", "mean", "nearest"]


def available_memory() -> int:
    """The bytes of memory available now without swapping (the kernel's ``MemAvailable``: free,
    and what the page cache would give back), or the free pages where that is not known."""
    try:
        with open("/proc/meminfo") as meminfo:
            for line in meminfo:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")


def in_flight_limit() -> int:
    """How much streamed records may hold unstored: `MAX_IN_FLIGHT_BYTES`, or `IN_FLIGHT_SHARE`
    of the memory available now if that is less."""
    return min(MAX_IN_FLIGHT_BYTES, int(available_memory() * IN_FLIGHT_SHARE))


def _halved(n: int, reduction: Reduction) -> int:
    """An extent halved as `reduction` does it: a stride keeps an odd edge's last sample, a
    reduction of pairs leaves it out."""
    return (n + 1) // 2 if reduction == "nearest" else n // 2


def pyramid_levels(height: int, width: int, reduction: Reduction = "max") -> int:
    """How many levels a pyramid of a `height` x `width` record has, level 0 included: halved
    until one fits a tile (or an edge could not be halved again)."""
    levels = 1
    while max(height, width) > TILE and min(height, width) >= 2:
        height, width = _halved(height, reduction), _halved(width, reduction)
        levels += 1
    return levels


def level_shapes(
    shape: tuple[int, ...], levels: int, reduction: Reduction = "max"
) -> list[tuple[int, ...]]:
    """The shape of each level of a ``(..., y, x)`` record of `shape`, level 0 first."""
    shapes = [tuple(int(n) for n in shape)]
    for _ in range(levels - 1):
        *rest, height, width = shapes[-1]
        shapes.append((*rest, _halved(height, reduction), _halved(width, reduction)))
    return shapes


def placement(
    level: int, rank: int, reduction: Reduction = "max"
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Where `level` of a ``(..., y, x)`` pyramid of `rank` axes sits in level 0's grid: its scale
    and translation per axis, as `mikro.pyramid` tracks them (a pair's reduction centres its
    voxel half a voxel in, a stride keeps voxel 0)."""
    factor = float(2**level)
    shift = 0.0 if reduction == "nearest" else (factor - 1) / 2
    return (1.0,) * (rank - 2) + (factor, factor), (0.0,) * (rank - 2) + (shift, shift)


@dataclass(frozen=True)
class Level:
    """A coarser level of a streamed record: the store it went into, its shape, and where it sits
    in level 0's grid."""

    level: int
    store: str
    shape: tuple[int, ...]
    scale: tuple[float, ...]
    translation: tuple[float, ...]


class MikroRecordStream:
    """One record's array, written into mikro's datalayer exposure by exposure: with each level of
    its pyramid, if it has one."""

    def __init__(
        self,
        client: Mikro,
        shape: tuple[int, ...],
        dtype: str,
        dims: tuple[str, ...],
        colors: int,
        budget: Any = None,  # noqa: ANN401 - a newswitch_native.InFlightBudget
        levels: int = 1,
        reduction: Reduction = "max",
    ) -> None:
        """Ask mikro for a grant for an array of `shape` and `dtype` (and one for each of its
        `levels` but the first, of that level's shape), and open them: waiting on `budget`, which
        other records share, or on one of its own (`in_flight_limit`).

        Raises:
            ImportError: newswitch's native module is not built (``just native``).
        """
        from newswitch_native import ShardedUpload

        self.client = client
        self.reduction: Reduction = reduction
        self.shapes = level_shapes(shape, levels, reduction)
        self.grants: list[Any] = []
        self._granted_at: list[float] = []
        self.finished = False
        try:
            for level_shape in self.shapes:
                self.grants.append(client.request_zarr_upload(shape=level_shape))
                self._granted_at.append(time.monotonic())
            datalayer = client.datalayer
            first = self.grants[0]
            self.upload = ShardedUpload.s3(
                datalayer.endpoint_url,
                first.bucket,
                first.key,
                first.access_key,
                first.secret_key,
                first.session_token,
                list(self.shapes[0]),
                dtype,
                list(dims),
                colors,
                proxy=datalayer.proxy,
                certificates=list(datalayer.certificates or []),
                max_in_flight_bytes=in_flight_limit(),
                reduction=reduction,
                budget=budget,
            )
            for grant, level_shape in zip(self.grants[1:], self.shapes[1:]):
                made = self.upload.add_level_s3(
                    grant.bucket, grant.key, grant.access_key, grant.secret_key, grant.session_token
                )
                if tuple(made) != level_shape:
                    raise RuntimeError(f"a level of {tuple(made)}, granted as {level_shape}")
        except Exception:
            self._drop()
            raise

    @property
    def grant(self) -> Any:  # noqa: ANN401 - mikro's grant
        """Level 0's grant."""
        return self.grants[0]

    @property
    def store(self) -> str:
        """The store's id: what a dataset is made of."""
        return str(self.grants[0].store)

    @property
    def levels(self) -> list[Level]:
        """Its pyramid's coarser levels (none without one): each in its store, placed."""
        rank = len(self.shapes[0])
        return [
            Level(k, str(grant.store), shape, *placement(k, rank, self.reduction))
            for k, (grant, shape) in enumerate(zip(self.grants, self.shapes))
            if k > 0
        ]

    def refresh_if_due(self) -> None:
        """Renew each grant once three quarters of it have passed: from a thread that can call
        the server."""
        for k, grant in enumerate(self.grants):
            lifetime = float(grant.expires_in or 0)
            if lifetime and time.monotonic() - self._granted_at[k] > REFRESH_AT * lifetime:
                store = str(grant.store)
                grant = self.grants[k] = self.client.refresh_zarr_upload(store_id=store)
                self._granted_at[k] = time.monotonic()
                self.upload.set_credentials(
                    grant.access_key, grant.secret_key, grant.session_token, level=k
                )
                logger.info("mikro upload %s: credentials refreshed", store)

    def write(self, t: int, c0: int, z: int, frame: FrameMemory) -> None:
        """Copy `frame` in (natively, from its address) as time `t`, channels `c0` on, plane `z`."""
        self.refresh_if_due()
        self.upload.write(
            t,
            c0,
            z,
            frame.address,
            frame.nbytes,
            frame.height,
            frame.width,
            frame.colors,
            frame.bytes_per_sample,
            planar=frame.planar,
        )

    def finish(self) -> str:
        """Wait until every exposure is stored (at every level) and have mikro check each store;
        level 0's id.

        Raises:
            RuntimeError: Something was not stored; mikro is told to drop every store.
        """
        try:
            stored = self.upload.finish()
        except Exception:
            self.abort()
            raise
        for grant in self.grants:
            self.client.finish_zarr_upload(store_id=str(grant.store), valid=True)
        self.finished = True
        logger.info(
            "mikro upload %s: %.1f MB stored in %d level(s); %s",
            self.store,
            stored / 1e6,
            len(self.grants),
            self.described(),
        )
        return self.store

    def described(self) -> str:
        """What was in it, per channel over every time point: its min, 99th percentile and max,
        so a dark or saturated record shows in the log."""
        import numpy as np

        from newswitch.infra.mikro.histograms import summarised

        by_channel: dict[int, list[Any]] = {}
        for (_, c), counts in self.histograms.items():
            by_channel.setdefault(c, []).append(counts)
        parts = []
        for c, counts in sorted(by_channel.items()):
            summary = summarised(np.sum(counts, axis=0))
            if summary is not None:
                parts.append(f"c{c} {summary.min:.0f}/{summary.p99:.0f}/{summary.max:.0f}")
        return "min/p99/max " + ", ".join(parts) if parts else "nothing counted"

    @property
    def histograms(self) -> dict[tuple[int, int], Any]:
        """How often each value occurred, by time point and channel: counted natively as each
        exposure was written (complete once `finish` returned)."""
        from newswitch.infra.mikro.histograms import of_native

        return of_native(self.upload.histograms())

    def abort(self) -> None:
        """Drop every store: mikro deletes what arrived and frees its quota."""
        if self.finished:
            return
        self.finished = True
        try:
            self.upload.finish()
        except Exception:  # noqa: BLE001 - what failed is what is being dropped
            pass
        self._drop()

    def _drop(self) -> None:
        """Have mikro drop each store granted."""
        self.finished = True
        for grant in self.grants:
            try:
                self.client.finish_zarr_upload(store_id=str(grant.store), valid=False)
            except Exception:  # noqa: BLE001 - dropping must not hide why the acquisition failed
                logger.exception("mikro upload %s: could not be dropped", grant.store)


def placeholder(shape: tuple[int, ...], dtype: str) -> Any:  # noqa: ANN401 - an array view
    """An array of `shape` and `dtype` taking no memory (one zero, broadcast): what a dataset's
    declaration validates its axes and layout against, the pixels being in the store already."""
    import numpy as np

    return np.broadcast_to(np.zeros((), dtype=dtype), shape)
