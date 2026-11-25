"""How an acquisition keeps pace: what each of its phases took, and exposures copied into their
streams while what comes next is done.

A triggered camera's frame stays in its ring slot until the next exposure is asked for
(`FrameMemory.held`), so it need not be copied before the stage moves on: `Writes` copies it on a
worker thread meanwhile (the native writer lets go of the GIL), one at a time, and the next write
waits for the last. `Timing` sums the wall time of each phase, so a run says where its time went.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any

from newswitch.protocols.dataset_store import FrameMemory, RecordStream

logger = logging.getLogger(__name__)

#: The phases of an exposure, in the order they come.
PHASES = ("move", "light", "camera", "write", "bookkeeping")
#: What the run does once before its exposures (a stream and its grant per record, the cameras
#: triggered): not shared out over them.
SETUP = "setup"


class Timing:
    """The wall time an acquisition spent in each phase (`PHASES`), and in all."""

    def __init__(self) -> None:
        self.spent = dict.fromkeys((SETUP, *PHASES), 0.0)
        self.exposures = 0
        self._started = time.perf_counter()
        self._ended: float | None = None

    @contextmanager
    def __call__(self, phase: str) -> Iterator[None]:
        """Count what the block takes as `phase`."""
        begun = time.perf_counter()
        try:
            yield
        finally:
            self.spent[phase] += time.perf_counter() - begun

    def stop(self) -> None:
        """The acquisition's exposures are over: what comes after is not theirs."""
        if self._ended is None:
            self._ended = time.perf_counter()

    @property
    def total_s(self) -> float:
        return (self._ended or time.perf_counter()) - self._started

    @property
    def per_exposure_ms(self) -> float:
        """What an exposure took, the setup left out."""
        return 1000.0 * (self.total_s - self.spent[SETUP]) / max(self.exposures, 1)

    def summary(self) -> str:
        """The setup, then each phase's share of an exposure, in milliseconds; what no phase took
        is `other`."""
        n = max(self.exposures, 1)
        other = self.total_s - sum(self.spent.values())
        parts = [f"{phase} {1000.0 * self.spent[phase] / n:.0f}" for phase in PHASES]
        return (
            f"setup {self.spent[SETUP]:.1f} s, then {self.exposures} exposures in "
            f"{self.total_s - self.spent[SETUP]:.1f} s, {self.per_exposure_ms:.0f} ms each: "
            f"{', '.join(parts)}, other {1000.0 * other / n:.0f} ms"
        )


class Writes:
    """Exposures copied into their streams on a worker thread, one at a time: each waits for the
    last, so a failed one stops the acquisition at the next."""

    def __init__(self) -> None:
        self._pool: ThreadPoolExecutor | None = None
        self._pending: Future[None] | None = None

    def later(self, stream: RecordStream, t: int, c0: int, z: int, frame: FrameMemory) -> None:
        """Copy `frame` in once the last is: the stream's grant renewed first, here (a worker
        thread cannot call the server).

        Raises:
            Exception: What the last write raised.
        """
        refresh = getattr(stream, "refresh_if_due", None)
        if refresh is not None:
            refresh()
        self.wait()
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stream-write")
        self._pending = self._pool.submit(_write, stream, t, c0, z, frame)

    def wait(self) -> None:
        """Until the last write is done.

        Raises:
            Exception: What it raised.
        """
        pending, self._pending = self._pending, None
        if pending is not None:
            pending.result()

    def close(self) -> None:
        """Wait for the last write, whatever it raised (the acquisition is over), and let go of
        the thread."""
        try:
            self.wait()
        except Exception:  # noqa: BLE001 - what failed is aborted with its stream
            logger.debug("a write failed as the acquisition ended", exc_info=True)
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None


def _write(stream: Any, t: int, c0: int, z: int, frame: FrameMemory) -> None:  # noqa: ANN401
    stream.write(t, c0, z, frame)
    if not frame.valid():
        raise RuntimeError("the camera reused a slot while it was copied: an exposure is lost")
