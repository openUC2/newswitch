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
"""

from __future__ import annotations

import logging
import time
from typing import Any

from mikro import Mikro

from newswitch.protocols.dataset_store import FrameMemory

logger = logging.getLogger(__name__)

#: How much of a record may be written and not yet stored: what a write waits for beyond it.
MAX_IN_FLIGHT_BYTES = 256 * 1024 * 1024
#: When in a grant's life it is refreshed, as a share of it.
REFRESH_AT = 0.75


class MikroRecordStream:
    """One record's array, written into mikro's datalayer exposure by exposure."""

    def __init__(
        self,
        client: Mikro,
        shape: tuple[int, ...],
        dtype: str,
        dims: tuple[str, ...],
        colors: int,
        max_in_flight_bytes: int = MAX_IN_FLIGHT_BYTES,
    ) -> None:
        """Ask mikro for a grant for an array of `shape` and `dtype`, and open it.

        Raises:
            ImportError: newswitch's native module is not built (``just native``).
        """
        from newswitch_native import ShardedUpload

        self.client = client
        self.grant = client.request_zarr_upload(shape=tuple(int(n) for n in shape))
        self._granted_at = time.monotonic()
        datalayer = client.datalayer
        self.upload = ShardedUpload.s3(
            datalayer.endpoint_url,
            self.grant.bucket,
            self.grant.key,
            self.grant.access_key,
            self.grant.secret_key,
            self.grant.session_token,
            [int(n) for n in shape],
            dtype,
            list(dims),
            colors,
            proxy=datalayer.proxy,
            certificates=list(datalayer.certificates or []),
            max_in_flight_bytes=max_in_flight_bytes,
        )
        self.finished = False

    @property
    def store(self) -> str:
        """The store's id: what a dataset is made of."""
        return str(self.grant.store)

    def refresh_if_due(self) -> None:
        """Renew the grant once three quarters of it have passed: from a thread that can call
        the server."""
        lifetime = float(self.grant.expires_in or 0)
        if lifetime and time.monotonic() - self._granted_at > REFRESH_AT * lifetime:
            self.grant = self.client.refresh_zarr_upload(store_id=self.store)
            self._granted_at = time.monotonic()
            self.upload.set_credentials(
                self.grant.access_key, self.grant.secret_key, self.grant.session_token
            )
            logger.info("mikro upload %s: credentials refreshed", self.store)

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
        """Wait until every exposure is stored and have mikro check the store; its id.

        Raises:
            RuntimeError: Something was not stored; mikro is told to drop the store.
        """
        try:
            stored = self.upload.finish()
        except Exception:
            self.abort()
            raise
        self.client.finish_zarr_upload(store_id=self.store, valid=True)
        self.finished = True
        logger.info(
            "mikro upload %s: %.1f MB stored; %s", self.store, stored / 1e6, self.described()
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
        """Drop the store: mikro deletes what arrived and frees its quota."""
        if self.finished:
            return
        self.finished = True
        try:
            self.upload.finish()
        except Exception:  # noqa: BLE001 - what failed is what is being dropped
            pass
        try:
            self.client.finish_zarr_upload(store_id=self.store, valid=False)
        except Exception:  # noqa: BLE001 - dropping must not hide why the acquisition failed
            logger.exception("mikro upload %s: could not be dropped", self.store)


def placeholder(shape: tuple[int, ...], dtype: str) -> Any:  # noqa: ANN401 - an array view
    """An array of `shape` and `dtype` taking no memory (one zero, broadcast): what a dataset's
    declaration validates its axes and layout against, the pixels being in the store already."""
    import numpy as np

    return np.broadcast_to(np.zeros((), dtype=dtype), shape)
