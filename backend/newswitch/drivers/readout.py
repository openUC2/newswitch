"""What part of each axis a detector reads out, and how: shared by every detector manager.

A detector delivers axes (`newswitch.models.devices.DetectorAxis`). Of each spatial one with a size
it reads a window, ``start`` and ``size`` in unbinned steps; a binnable one (a sensor's own pixels)
is then binned. For a camera the windows are its region of interest; for a scan they are the part
of it that is scanned, at the same step: a smaller field, not a zoom.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from newswitch.models.devices import AxisWindow, Detector, DetectorAxis


def windowable(axis: DetectorAxis) -> bool:
    """Whether a window can be read of `axis`: it is spatial and has a size of its own."""
    return axis.domain == "space" and axis.size is not None


def check_windows(detector: Detector, windows: Sequence[AxisWindow], binning: int) -> None:
    """Whether `windows`, at `binning`, leave every axis of `detector` something to read.

    Raises:
        ValueError: A window of an axis it has not, or that cannot have one, one twice, one outside
            its axis, or one smaller than the binning.
    """
    named = [window.axis for window in windows]
    if len(named) != len(set(named)):
        raise ValueError(f"{detector.name}: an axis has two windows: {named}")
    for window in windows:
        if not detector.has_axis(window.axis):
            raise ValueError(f"{detector.name} has no axis {window.axis!r}")
        axis = detector.axis(window.axis)
        if not windowable(axis):
            raise ValueError(f"{detector.name}: the axis {axis.name} has no window to read")
        assert axis.size is not None
        if window.start < 0 or window.size < 1 or window.start + window.size > axis.size:
            raise ValueError(
                f"{detector.name}: {window.size} steps from {window.start} are not within the "
                f"{axis.size} of {axis.name}"
            )
    by_axis = {window.axis: window for window in windows}
    for axis in detector.axes:
        if axis.binnable and axis.size is not None:
            size = by_axis[axis.name].size if axis.name in by_axis else axis.size
            if size // binning < 1:
                raise ValueError(
                    f"{detector.name}: {size} steps of {axis.name} are fewer than the binning "
                    f"{binning}"
                )


def apply(detector: Detector, windows: Sequence[AxisWindow] | None, binning: int | None) -> None:
    """Set the windows and binning of `detector`, as `check_windows` allows them.

    None keeps what it has; an axis `windows` does not name is read whole.
    """
    new_binning = detector.binning() if binning is None else binning
    if windows is None:
        windows = [
            AxisWindow(axis.name, axis.window_start, axis.window_size)
            for axis in detector.axes
            if axis.window_size is not None
        ]
    check_windows(detector, windows, new_binning)
    by_axis = {window.axis: window for window in windows}
    for axis in detector.axes:
        window = by_axis.get(axis.name)
        whole = window is None or (window.start == 0 and window.size == axis.size)
        axis.window_start = 0 if whole or window is None else window.start
        axis.window_size = None if whole or window is None else window.size
        if axis.binnable:
            axis.binning = new_binning
        axis.refresh()


def read_out(data: np.ndarray, detector: Detector, dims: Sequence[str]) -> np.ndarray:
    """Cut each window out of `data`, whose axes are `dims`, and bin what bins (block means).

    `data` is what the whole of each axis delivered; the result has the detector's type.
    """
    for index, name in enumerate(dims):
        axis = detector.axis(name)
        if not windowable(axis):
            continue
        size = axis.windowed()
        assert size is not None
        cut = [slice(None)] * data.ndim
        cut[index] = slice(axis.window_start, axis.window_start + size)
        data = data[tuple(cut)]
        if axis.binnable and axis.binning > 1:
            factor = axis.binning
            kept = (size // factor) * factor
            cut = [slice(None)] * data.ndim
            cut[index] = slice(0, kept)
            data = data[tuple(cut)]
            shape = (*data.shape[:index], kept // factor, factor, *data.shape[index + 1 :])
            data = data.reshape(shape).mean(axis=index + 1)
    return np.ascontiguousarray(data, dtype=np.dtype(detector.data_type))


def settings(detector: Detector) -> dict[str, object]:
    """The windows and binning of `detector`, as a session's settings say them."""
    return {
        "binning": detector.binning(),
        "windows": {
            axis.name: [axis.window_start, axis.windowed()]
            for axis in detector.axes
            if axis.window_size is not None
        },
    }
