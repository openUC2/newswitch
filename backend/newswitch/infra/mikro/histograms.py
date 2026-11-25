"""Value histograms of a record, by time point and channel: what mikro draws a channel's contrast
from (`ValueHistogramInput`: min, max, 1st and 99th percentile, the counts over bins).

A record's histograms are counted exactly: how often each possible value occurs (256 values of
an 8-bit sample, 65536 of a 16-bit one), at each time point and channel, over every plane. A
streamed record's are counted natively while it is written (`newswitch_native.ShardedUpload.
histograms`); one held in memory has them counted here (`counted`). mikro gets them summarised:
the percentiles from the exact counts, the counts over `BINS` bins between min and max.
"""

from __future__ import annotations

from typing import Iterable, Mapping

import numpy as np
from mikro.api.schema import AxisAnchorInput, CoordinateAnchorInput, ValueHistogramInput

#: How many bins a histogram is shown with (mikro's own default).
BINS = 256


def counted(data: np.ndarray, dims: tuple[str, ...]) -> dict[tuple[int, int], np.ndarray]:
    """How often each value occurs in `data` (``t, c, …`` integers), by time point and channel."""
    if data.dtype.kind not in "ui" or dims[:2] != ("t", "c"):
        return {}
    values = 1 << (8 * data.dtype.itemsize)
    return {
        (t, c): np.bincount(data[t, c].ravel(), minlength=values).astype(np.uint64)
        for t in range(data.shape[0])
        for c in range(data.shape[1])
    }


def of_native(raw: Iterable[tuple[int, int, bytes]]) -> dict[tuple[int, int], np.ndarray]:
    """The native writer's histograms (`ShardedUpload.histograms`) as counts by (t, c)."""
    return {(int(t), int(c)): np.frombuffer(counts, dtype="<u8") for t, c, counts in raw}


def summarised(counts: np.ndarray, bins: int = BINS) -> ValueHistogramInput | None:
    """`counts` (one per value) as mikro takes a histogram; None when nothing was counted."""
    total = int(counts.sum())
    if total == 0:
        return None
    present = np.flatnonzero(counts)
    low, high = int(present[0]), int(present[-1])
    cumulative = np.cumsum(counts)
    p1 = int(np.searchsorted(cumulative, 0.01 * total))
    p99 = int(np.searchsorted(cumulative, 0.99 * total))
    edges = np.linspace(low, high + 1, bins + 1)
    # Each value's count into the bin its value falls in: the counts of an integer histogram.
    which = np.clip(np.searchsorted(edges, np.arange(low, high + 1), side="right") - 1, 0, bins - 1)
    binned = np.bincount(which, weights=counts[low : high + 1], minlength=bins)
    return ValueHistogramInput(
        min=float(low),
        max=float(high),
        p1=float(p1),
        p99=float(p99),
        bins=tuple(edges.tolist()),
        histogram=tuple(binned.tolist()),
    )


def anchors(histograms: Mapping[tuple[int, int], np.ndarray]) -> list[CoordinateAnchorInput]:
    """An anchor per time point and channel, carrying its histogram."""
    found = []
    for (t, c), counts in sorted(histograms.items()):
        summary = summarised(counts)
        if summary is None:
            continue
        found.append(
            CoordinateAnchorInput(
                axis_anchors=(AxisAnchorInput(axis="t", value=t), AxisAnchorInput(axis="c", value=c)),
                value_histogram=summary,
            )
        )
    return found


def contrast(
    histograms: Mapping[tuple[int, int], np.ndarray], channel: int
) -> tuple[float, float] | None:
    """A channel's contrast window over all its time points: its 1st and 99th percentile."""
    counts = [h for (_, c), h in histograms.items() if c == channel]
    if not counts:
        return None
    summary = summarised(np.sum(counts, axis=0))
    if summary is None or summary.p1 is None or summary.p99 is None:
        return None
    return summary.p1, max(summary.p99, summary.p1 + 1)
