"""Records streamed as they are taken: the native writer, the acquisition writing into it exposure
by exposure, and mikro's side (grant, finish, a dataset of the store)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import zarr

from newswitch.models.acquisition import AcquisitionChannel
from newswitch.protocols.dataset_store import (
    AcquiredRecord,
    FrameMemory,
    StreamingDatasetStore,
)
from tests.conftest import acquisition as plan
from tests.test_acquire import LASER, LED, RecordingStore, acquire, built

native = pytest.importorskip("newswitch_native")
DIMS = ["t", "c", "z", "y", "x"]


# --- the native writer --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("shape", "dtype", "colors", "planar"),
    [
        ((682, 1000, 3), np.uint8, 3, False),  # a color camera's (y, x, 3), not a multiple of 256
        ((3, 300, 500), np.uint16, 3, True),  # a simulated detector's (c, y, x)
        ((256, 512), np.uint16, 1, False),  # mono
    ],
)
def test_frames_written_natively_read_back_as_zarr(
    tmp_path: Path, shape: tuple[int, ...], dtype: Any, colors: int, planar: bool  # noqa: ANN401
) -> None:
    rng = np.random.default_rng(0)
    frames = {
        (t, z): rng.integers(0, np.iinfo(dtype).max, shape, dtype=dtype) for t in range(2) for z in range(2)
    }
    height, width = (shape[1], shape[2]) if planar else shape[:2]
    upload = native.ShardedUpload.local(
        str(tmp_path), [2, colors * 2, 2, height, width], np.dtype(dtype).name, DIMS, colors
    )
    for (t, z), frame in frames.items():
        for channel in range(2):
            upload.write(
                t, channel * colors, z, frame.ctypes.data, frame.nbytes, height, width, colors,
                frame.itemsize, planar=planar,
            )
    assert upload.finish() > 0
    array = zarr.open_array(str(tmp_path), mode="r")
    assert array.shape == (2, colors * 2, 2, height, width)
    assert list(array.metadata.dimension_names) == DIMS
    for (t, z), frame in frames.items():
        planes = frame if planar else frame.reshape(height, width, colors).transpose(2, 0, 1)
        for channel in range(2):
            assert np.array_equal(array[t, channel * colors : (channel + 1) * colors, z], planes)


def test_a_frame_that_is_not_the_arrays_is_refused(tmp_path: Path) -> None:
    upload = native.ShardedUpload.local(str(tmp_path), [1, 1, 1, 64, 64], "uint16", DIMS, 1)
    frame = np.zeros((64, 32), np.uint16)
    with pytest.raises(ValueError, match="not the array's"):
        upload.write(0, 0, 0, frame.ctypes.data, frame.nbytes, 64, 32, 1, 2)
    frame = np.zeros((64, 64), np.uint16)
    with pytest.raises(ValueError, match="no place"):
        upload.write(1, 0, 0, frame.ctypes.data, frame.nbytes, 64, 64, 1, 2)
    with pytest.raises(ValueError, match="uint8 or uint16"):
        native.ShardedUpload.local(str(tmp_path / "f"), [1, 1, 1, 8, 8], "float32", DIMS, 1)


def test_writing_waits_for_what_is_not_yet_stored(tmp_path: Path) -> None:
    """Never more than the limit unstored (a lone frame aside), and nothing once finished."""
    frame = np.ones((512, 512), np.uint16)
    upload = native.ShardedUpload.local(
        str(tmp_path), [8, 1, 1, 512, 512], "uint16", DIMS, 1, max_in_flight_bytes=frame.nbytes
    )
    for t in range(8):
        upload.write(t, 0, 0, frame.ctypes.data, frame.nbytes, 512, 512, 1, 2)
        assert upload.pending_bytes <= frame.nbytes
    upload.finish()
    assert upload.pending_bytes == 0


def test_uploads_sharing_a_budget_are_bounded_together(tmp_path: Path) -> None:
    """Records streamed at once (every position, every camera) never hold more than their one
    budget unstored, all of them together; and a budget that grows lets waiting writes through."""
    frame = np.ones((512, 512), np.uint16)
    budget = native.InFlightBudget(frame.nbytes)
    uploads = [
        native.ShardedUpload.local(str(tmp_path / f"r{k}"), [6, 1, 1, 512, 512], "uint16", DIMS, 1, budget=budget)
        for k in range(3)
    ]
    for t in range(6):
        for upload in uploads:
            upload.write(t, 0, 0, frame.ctypes.data, frame.nbytes, 512, 512, 1, 2)
            assert budget.pending_bytes <= frame.nbytes
    for upload in uploads:
        upload.finish()
    assert budget.pending_bytes == 0
    budget.limit = 3 * frame.nbytes
    assert budget.limit == 3 * frame.nbytes


def test_what_may_be_in_flight_is_a_gigabyte_or_half_the_memory_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from newswitch.infra.mikro import stream as streaming

    monkeypatch.setattr(streaming, "available_memory", lambda: 6 * 1024**3)
    assert streaming.in_flight_limit() == 1024**3
    monkeypatch.setattr(streaming, "available_memory", lambda: 1024**3)
    assert streaming.in_flight_limit() == 512 * 1024**2


@pytest.mark.parametrize("reduction", ["max", "mean", "nearest"])
@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_a_pyramid_written_natively_is_mikros_own(
    tmp_path: Path, reduction: str, dtype: Any  # noqa: ANN401
) -> None:
    """Each level, made of each exposure as it is written, is what `mikro.dataset_arrays` makes of
    the whole record halving y and x: its pixels (odd edges trimmed, or kept by a stride), and its
    shape as `level_shapes` says, placed as `placement` says."""
    from mikro import dataset_arrays

    from newswitch.infra.mikro.stream import level_shapes, placement

    shape = (2, 4, 3, 101, 67)  # two exposures of two interleaved colors, odd y and x
    rng = np.random.default_rng(1)
    data = rng.integers(0, np.iinfo(dtype).max, shape, dtype=dtype)
    upload = native.ShardedUpload.local(
        str(tmp_path / "0"), list(shape), np.dtype(dtype).name, DIMS, 2, reduction=reduction
    )
    shapes = level_shapes(shape, 3, reduction)  # type: ignore[arg-type]
    for k in (1, 2):
        assert tuple(upload.add_level_local(str(tmp_path / str(k)))) == shapes[k]
    assert upload.levels == 3
    for t in range(2):
        for z in range(3):
            for c0 in (0, 2):
                frame = np.ascontiguousarray(data[t, c0 : c0 + 2, z].transpose(1, 2, 0))
                upload.write(t, c0, z, frame.ctypes.data, frame.nbytes, 101, 67, 2, frame.itemsize)
    upload.finish()
    _, scales = dataset_arrays(data, levels=3, method=reduction, axes=("y", "x"), dims=DIMS)  # type: ignore[arg-type]
    for k, expected in enumerate(scales, start=1):
        level = zarr.open_array(str(tmp_path / str(k)), mode="r")
        assert level.shape == shapes[k]
        assert np.array_equal(level[...], np.asarray(expected.array.data))
        assert (expected.scale, expected.translation) == placement(k, 5, reduction)  # type: ignore[arg-type]


def test_a_level_is_added_before_any_frame_and_while_it_can_be_halved(tmp_path: Path) -> None:
    upload = native.ShardedUpload.local(str(tmp_path / "0"), [1, 1, 1, 4, 3], "uint8", DIMS, 1)
    assert upload.add_level_local(str(tmp_path / "1")) == [1, 1, 1, 2, 1]
    with pytest.raises(ValueError, match="not halved again"):
        upload.add_level_local(str(tmp_path / "2"))
    frame = np.zeros((4, 3), np.uint8)
    upload.write(0, 0, 0, frame.ctypes.data, frame.nbytes, 4, 3, 1, 1)
    upload.finish()
    later = native.ShardedUpload.local(str(tmp_path / "a"), [1, 1, 1, 8, 8], "uint8", DIMS, 1)
    frame = np.zeros((8, 8), np.uint8)
    later.write(0, 0, 0, frame.ctypes.data, frame.nbytes, 8, 8, 1, 1)
    with pytest.raises(ValueError, match="before the first frame"):
        later.add_level_local(str(tmp_path / "b"))
    with pytest.raises(ValueError, match="max, mean or nearest"):
        native.ShardedUpload.local(str(tmp_path / "c"), [1, 1, 1, 8, 8], "uint8", DIMS, 1, reduction="median")


def test_a_pyramid_is_halved_until_it_fits_a_tile() -> None:
    from newswitch.infra.mikro.stream import level_shapes, placement, pyramid_levels

    assert pyramid_levels(256, 200) == 1
    assert pyramid_levels(512, 512) == 2  # 512 -> 256
    assert pyramid_levels(3000, 4000) == 5  # 4000 -> 2000 -> 1000 -> 500 -> 250
    assert pyramid_levels(1, 100000) == 1  # an edge that cannot be halved
    assert level_shapes((1, 3, 2, 101, 67), 3) == [
        (1, 3, 2, 101, 67), (1, 3, 2, 50, 33), (1, 3, 2, 25, 16)
    ]
    assert level_shapes((1, 1, 1, 101, 67), 2, "nearest")[1] == (1, 1, 1, 51, 34)
    assert placement(2, 5) == ((1.0, 1.0, 1.0, 4.0, 4.0), (0.0, 0.0, 0.0, 1.5, 1.5))
    assert placement(2, 5, "nearest")[1] == (0.0,) * 5


# --- the acquisition, into a store that streams --------------------------------------------------


@dataclass
class LocalStream:
    """A record streamed into a local zarr, through the native writer."""

    root: Path
    upload: Any
    aborted: bool = False
    finished: bool = False

    def write(self, t: int, c0: int, z: int, frame: FrameMemory) -> None:
        self.upload.write(
            t, c0, z, frame.address, frame.nbytes, frame.height, frame.width, frame.colors,
            frame.bytes_per_sample, planar=frame.planar,
        )

    def finish(self) -> np.ndarray:
        self.upload.finish()
        self.finished = True
        return zarr.open_array(str(self.root), mode="r")[...]

    def abort(self) -> None:
        self.aborted = True


@dataclass
class StreamingStore(RecordingStore):
    """Streams camera records into local zarrs, keeps what is published."""

    root: Path = Path()
    opened: list[LocalStream] = field(default_factory=list)
    fail_after: int | None = None
    pyramids: list[bool] = field(default_factory=list)

    def stream(
        self,
        shape: tuple[int, ...],
        dtype: str,
        dims: tuple[str, ...],
        colors: int,
        pyramid: bool = False,
    ) -> LocalStream:
        from newswitch.infra.mikro.stream import pyramid_levels

        record = self.root / f"record-{len(self.opened)}"
        folder = record / "0"
        upload = native.ShardedUpload.local(str(folder), list(shape), dtype, list(dims), colors)
        self.pyramids.append(pyramid)
        for k in range(1, pyramid_levels(shape[-2], shape[-1]) if pyramid else 1):
            upload.add_level_local(str(record / str(k)))
        stream = LocalStream(folder, upload)
        if self.fail_after is not None:
            written = []

            def failing(t: int, c0: int, z: int, frame: FrameMemory) -> None:
                written.append(1)
                if len(written) > (self.fail_after or 0):
                    raise RuntimeError("the store went away")
                LocalStream.write(stream, t, c0, z, frame)

            stream.write = failing  # type: ignore[method-assign]
        self.opened.append(stream)
        return stream


def test_a_streaming_store_gets_every_exposure_as_it_is_taken(tmp_path: Path) -> None:
    """The camera records hold no array: their exposures went into the stream, all of them, and
    the published record carries it, with its shape and planes."""
    m = built(tmp_path, "dual-camera")
    store = StreamingStore(root=tmp_path / "zarr")
    assert isinstance(store, StreamingDatasetStore)
    acquire(
        m,
        plan(
            [AcquisitionChannel(detectors=["camera_green", "camera_red"], name="all", set_to={**LASER, **LED})],
            planes=[-2.0, 0.0, 2.0],
            times=2,
        ),
        store,
    )
    assert len(store.opened) == 2 and len(store.published) == 2
    for acquired in store.published:
        assert isinstance(acquired, AcquiredRecord) and acquired.data is None
        assert acquired.stream is not None and acquired.shape == (2, 1, 3, 512, 512)
        assert acquired.dtype == "uint16"
        assert {(p.t, p.c, p.z) for p in acquired.planes} == {(t, 0, z) for t in range(2) for z in range(3)}
        pixels = acquired.stream.finish()  # type: ignore[attr-defined]
        assert pixels.shape == (2, 1, 3, 512, 512)
        assert all(pixels[t, 0, z].max() > 0 for t in range(2) for z in range(3))  # every plane came


def test_a_plan_with_a_pyramid_streams_each_record_with_its_levels(tmp_path: Path) -> None:
    """`AcquisitionPlan.pyramid` reaches the store's streams, and every exposure reaches every
    level: a 512 camera's halved once, to one tile."""
    m = built(tmp_path, "dual-camera")
    store = StreamingStore(root=tmp_path / "zarr")
    acquire(
        m,
        plan(
            [AcquisitionChannel(detectors=["camera_green"], name="green", set_to={**LASER})],
            planes=[-2.0, 0.0, 2.0],
            pyramid=True,
        ),
        store,
    )
    assert store.pyramids == [True]
    [acquired] = store.published
    assert acquired.pyramid
    [stream] = store.opened
    assert stream.upload.levels == 2
    pixels = stream.finish()
    coarse = zarr.open_array(str(tmp_path / "zarr" / "record-0" / "1"), mode="r")[...]
    assert coarse.shape == (1, 1, 3, 256, 256)
    assert np.array_equal(coarse, pixels.reshape(1, 1, 3, 256, 2, 256, 2).max(axis=(4, 6)))


def test_a_plan_without_a_pyramid_streams_level_0_only(tmp_path: Path) -> None:
    m = built(tmp_path, "dual-camera")
    store = StreamingStore(root=tmp_path / "zarr")
    acquire(
        m,
        plan([AcquisitionChannel(detectors=["camera_green"], name="green", set_to={**LASER})]),
        store,
    )
    assert store.pyramids == [False] and store.opened[0].upload.levels == 1
    assert not store.published[0].pyramid


def test_a_failed_acquisition_drops_what_it_streamed(tmp_path: Path) -> None:
    m = built(tmp_path, "dual-camera")
    store = StreamingStore(root=tmp_path / "zarr", fail_after=2)
    with pytest.raises(RuntimeError, match="went away"):
        acquire(
            m,
            plan(
                [AcquisitionChannel(detectors=["camera_green"], name="green", set_to={**LASER})],
                planes=[-2.0, 0.0, 2.0],
            ),
            store,
        )
    assert store.opened and all(stream.aborted for stream in store.opened)
    assert store.published == []


# --- mikro's side ----------------------------------------------------------------------------------


class FakeUpload:
    """What `ShardedUpload.s3` is given and asked."""

    made: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        self.args, self.kwargs, self.writes, self.credentials = args, kwargs, [], []
        self.added: list[tuple[Any, ...]] = []
        self.fail = False
        self.shape = list(args[6])
        FakeUpload.made.append({"args": args, "kwargs": kwargs, "upload": self})

    def add_level_s3(self, *args: Any) -> list[int]:  # noqa: ANN401
        self.added.append(args)
        *rest, height, width = self.shape
        self.shape = [*rest, height // 2, width // 2]
        return self.shape

    @classmethod
    def s3(cls, *args: Any, **kwargs: Any) -> "FakeUpload":  # noqa: ANN401
        return cls(*args, **kwargs)

    def write(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        self.writes.append((args, kwargs))

    def set_credentials(self, *args: Any, level: int = 0) -> None:  # noqa: ANN401
        self.credentials.append(args if level == 0 else (*args, level))

    def finish(self) -> int:
        if self.fail:
            raise RuntimeError("c/0/0/0/0/0: 403")
        return 123

    def histograms(self) -> list[tuple[int, int, bytes]]:
        return [(0, 0, np.bincount([7, 7, 9], minlength=256).astype("<u8").tobytes())]


class FakeMikro:
    """A mikro client: grants, refreshes and finishes, and a datalayer behind the mesh's proxy."""

    def __init__(self, expires_in: int = 3600) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.expires_in = expires_in
        self.datalayer = SimpleNamespace(
            endpoint_url="http://100.94.1.2:8000/datalayer",
            proxy="http://mesh:secret@127.0.0.1:41234",
            certificates=["PEM"],
        )

    def _grant(self, n: int, store: str = "store-1") -> Any:  # noqa: ANN401
        return SimpleNamespace(
            access_key=f"AK{n}", secret_key=f"SK{n}", session_token=f"T{n}", bucket="zarr",
            key=f"user/{n}", store=store, expires_in=self.expires_in,
        )

    def request_zarr_upload(self, **kwargs: Any) -> Any:  # noqa: ANN401
        self.calls.append(("request", kwargs))
        n = sum(1 for call in self.calls if call[0] == "request")
        return self._grant(1, f"store-{n}")

    def refresh_zarr_upload(self, store_id: str) -> Any:  # noqa: ANN401
        self.calls.append(("refresh", store_id))
        return self._grant(2, store_id)

    def finish_zarr_upload(self, store_id: str, valid: bool) -> Any:  # noqa: ANN401
        self.calls.append(("finish", (store_id, valid)))
        return SimpleNamespace(id=store_id)


@pytest.fixture
def fake_native(monkeypatch: pytest.MonkeyPatch) -> type[FakeUpload]:
    FakeUpload.made = []
    monkeypatch.setattr(native, "ShardedUpload", FakeUpload)
    return FakeUpload


def test_a_mikro_stream_writes_with_the_grant_through_the_mesh(fake_native: type[FakeUpload]) -> None:
    from newswitch.infra.mikro.stream import MikroRecordStream

    client = FakeMikro()
    stream = MikroRecordStream(client, (1, 3, 1, 64, 64), "uint8", tuple(DIMS), 3)  # type: ignore[arg-type]
    [made] = fake_native.made
    endpoint, bucket, prefix, key, secret, token = made["args"][:6]
    assert (endpoint, bucket, prefix, key, secret, token) == (
        "http://100.94.1.2:8000/datalayer", "zarr", "user/1", "AK1", "SK1", "T1"
    )
    assert made["kwargs"]["proxy"] == "http://mesh:secret@127.0.0.1:41234"
    assert made["kwargs"]["certificates"] == ["PEM"]
    frame = FrameMemory.of_array(np.zeros((3, 64, 64), np.uint8))
    stream.write(0, 0, 0, frame)
    assert stream.finish() == "store-1"
    assert client.calls[-1] == ("finish", ("store-1", True))


def test_a_grant_is_refreshed_before_it_runs_out(
    fake_native: type[FakeUpload], monkeypatch: pytest.MonkeyPatch
) -> None:
    from newswitch.infra.mikro import stream as streaming

    client = FakeMikro(expires_in=100)
    stream = streaming.MikroRecordStream(client, (2, 1, 1, 8, 8), "uint16", tuple(DIMS), 1)  # type: ignore[arg-type]
    frame = FrameMemory.of_array(np.zeros((8, 8), np.uint16))
    stream.write(0, 0, 0, frame)
    assert not any(call[0] == "refresh" for call in client.calls)
    later = streaming.time.monotonic() + 80  # past three quarters of its 100 s
    monkeypatch.setattr(streaming.time, "monotonic", lambda: later)
    stream.write(1, 0, 0, frame)
    assert ("refresh", "store-1") in client.calls
    assert stream.upload.credentials == [("AK2", "SK2", "T2")]  # type: ignore[attr-defined]


def test_what_could_not_be_stored_is_dropped(fake_native: type[FakeUpload]) -> None:
    from newswitch.infra.mikro.stream import MikroRecordStream

    client = FakeMikro()
    stream = MikroRecordStream(client, (1, 1, 1, 8, 8), "uint16", tuple(DIMS), 1)  # type: ignore[arg-type]
    stream.upload.fail = True  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="403"):
        stream.finish()
    assert client.calls[-1] == ("finish", ("store-1", False))
    stream.abort()  # once only
    assert [call for call in client.calls if call[0] == "finish"] == [("finish", ("store-1", False))]


def test_a_mikro_stream_with_a_pyramid_has_a_grant_for_each_level(
    fake_native: type[FakeUpload], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each level its own store, of its shape: each refreshed with its level, each finished; and
    all of them dropped when anything was not stored."""
    from newswitch.infra.mikro import stream as streaming

    client = FakeMikro(expires_in=100)
    stream = streaming.MikroRecordStream(client, (1, 1, 1, 64, 48), "uint16", tuple(DIMS), 1, levels=3)  # type: ignore[arg-type]
    assert [kwargs["shape"] for name, kwargs in client.calls if name == "request"] == [
        (1, 1, 1, 64, 48), (1, 1, 1, 32, 24), (1, 1, 1, 16, 12)
    ]
    [made] = fake_native.made
    assert made["kwargs"]["reduction"] == "max"
    assert [args[:2] for args in made["upload"].added] == [("zarr", "user/1"), ("zarr", "user/1")]
    assert [(level.level, level.store, level.shape) for level in stream.levels] == [
        (1, "store-2", (1, 1, 1, 32, 24)), (2, "store-3", (1, 1, 1, 16, 12))
    ]
    later = streaming.time.monotonic() + 80
    monkeypatch.setattr(streaming.time, "monotonic", lambda: later)
    stream.write(0, 0, 0, FrameMemory.of_array(np.zeros((64, 48), np.uint16)))
    assert [call for call in client.calls if call[0] == "refresh"] == [
        ("refresh", "store-1"), ("refresh", "store-2"), ("refresh", "store-3")
    ]
    assert made["upload"].credentials == [
        ("AK2", "SK2", "T2"), ("AK2", "SK2", "T2", 1), ("AK2", "SK2", "T2", 2)
    ]
    assert stream.finish() == "store-1"
    assert [call for call in client.calls if call[0] == "finish"] == [
        ("finish", (f"store-{n}", True)) for n in (1, 2, 3)
    ]

    client = FakeMikro()
    failing = streaming.MikroRecordStream(client, (1, 1, 1, 64, 48), "uint16", tuple(DIMS), 1, levels=2)  # type: ignore[arg-type]
    failing.upload.fail = True  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="403"):
        failing.finish()
    assert [call for call in client.calls if call[0] == "finish"] == [
        ("finish", ("store-1", False)), ("finish", ("store-2", False))
    ]


def test_a_streamed_record_is_declared_with_its_store(fake_native: type[FakeUpload]) -> None:
    """The dataset mutation is checked against an array of the record's shape, as any, and sent
    with the store the record went into as its data."""
    from mikro.api import schema

    from newswitch.infra.mikro.store import MikroDatasetStore
    from newswitch.instrument import spec
    from newswitch.models.space import Axis

    sent: list[dict[str, Any]] = []
    client = FakeMikro()

    def query(document: str, variables: dict[str, Any], headers: Any = None) -> Any:  # noqa: ANN401
        sent.append(variables)
        raise RuntimeError("stop here")  # what came back is mikro's business

    client._serialize = lambda op, variables: schema.CreateArrayDatasetMutation.Arguments(**variables).model_dump(  # type: ignore[attr-defined]
        by_alias=True, exclude_unset=True
    )
    client.rath = SimpleNamespace(query=query)  # type: ignore[attr-defined]
    client._headers = lambda task: None  # type: ignore[attr-defined]
    instrument = spec.load(Path(__file__).parent.parent / "instruments" / "johannes-frame")
    store = MikroDatasetStore(client, instrument, SimpleNamespace())  # type: ignore[arg-type]
    record_stream = store.stream((1, 3, 1, 64, 64), "uint8", tuple(DIMS), 3)
    record_stream.write(0, 0, 0, FrameMemory.of_array(np.zeros((3, 64, 64), np.uint8)))
    acquired = AcquiredRecord(
        name="run camera", position=0, detector="camera", data=None,
        axes=tuple(Axis(name, kind) for name, kind in zip(DIMS, ("TIME", "CHANNEL", "SPACE", "SPACE", "SPACE"))),
        channels=(), planes=(), registration=(), calibrated=False,
        stream=record_stream, shape=(1, 3, 1, 64, 64), dtype="uint8",
    )
    with pytest.raises(RuntimeError, match="stop here"):
        store._create_dataset(acquired, None, anchors=[])
    assert sent and sent[0]["input"]["data"] == "store-1"
    [histogram] = [a for a in sent[0]["input"]["anchors"] if a.get("valueHistogram")]
    assert histogram["valueHistogram"]["min"] == 7.0 and histogram["valueHistogram"]["max"] == 9.0
    assert ("finish", ("store-1", True)) in client.calls


def test_a_streamed_pyramid_is_declared_with_each_levels_store_and_place(
    fake_native: type[FakeUpload],
) -> None:
    from mikro.api import schema

    from newswitch.infra.mikro.store import MikroDatasetStore
    from newswitch.instrument import spec
    from newswitch.models.space import Axis

    sent: list[dict[str, Any]] = []
    client = FakeMikro()

    def query(document: str, variables: dict[str, Any], headers: Any = None) -> Any:  # noqa: ANN401
        sent.append(variables)
        raise RuntimeError("stop here")

    client._serialize = lambda op, variables: schema.CreateArrayDatasetMutation.Arguments(**variables).model_dump(  # type: ignore[attr-defined]
        by_alias=True, exclude_unset=True
    )
    client.rath = SimpleNamespace(query=query)  # type: ignore[attr-defined]
    client._headers = lambda task: None  # type: ignore[attr-defined]
    instrument = spec.load(Path(__file__).parent.parent / "instruments" / "johannes-frame")
    store = MikroDatasetStore(client, instrument, SimpleNamespace())  # type: ignore[arg-type]
    shape = (1, 3, 1, 1024, 768)  # 1024 -> 512 -> 256: three levels
    record_stream = store.stream(shape, "uint8", tuple(DIMS), 3, pyramid=True)
    other = store.stream((1, 1, 1, 64, 64), "uint8", tuple(DIMS), 1)
    budgets = [made["kwargs"]["budget"] for made in fake_native.made]
    assert len(budgets) == 2 and budgets[0] is budgets[1]  # one for every record streamed
    acquired = AcquiredRecord(
        name="run camera", position=0, detector="camera", data=None,
        axes=tuple(Axis(name, kind) for name, kind in zip(DIMS, ("TIME", "CHANNEL", "SPACE", "SPACE", "SPACE"))),
        channels=(), planes=(), registration=(), calibrated=False,
        stream=record_stream, shape=shape, dtype="uint8", pyramid=True,
    )
    with pytest.raises(RuntimeError, match="stop here"):
        store._create_dataset(acquired, None, anchors=[])
    scales = sent[0]["input"]["scales"]
    assert sent[0]["input"]["data"] == "store-1"
    assert [(s["level"], s["array"], s["scaleMethod"]) for s in scales] == [
        (1, "store-2", "MAX"), (2, "store-3", "MAX")
    ]
    assert scales[1]["scale"] == (1.0, 1.0, 1.0, 4.0, 4.0)
    assert scales[1]["translation"] == (0.0, 0.0, 0.0, 1.5, 1.5)
    assert [call for call in client.calls if call[0] == "finish"] == [
        ("finish", (f"store-{n}", True)) for n in (1, 2, 3)
    ]


def test_a_record_held_in_memory_is_declared_with_the_same_pyramid() -> None:
    """Without the native writer the pyramid is mikro's own, made the same way: max of 2 x 2,
    y and x only, until one tile."""
    from newswitch.infra.mikro.store import MikroDatasetStore
    from newswitch.instrument import spec
    from newswitch.models.space import Axis

    created: list[dict[str, Any]] = []
    client = SimpleNamespace(create_array_dataset=lambda **kwargs: created.append(kwargs))
    instrument = spec.load(Path(__file__).parent.parent / "instruments" / "johannes-frame")
    store = MikroDatasetStore(client, instrument, SimpleNamespace())  # type: ignore[arg-type]
    data = np.random.default_rng(2).integers(0, 255, (1, 1, 2, 600, 300), dtype=np.uint8)
    axes = tuple(Axis(name, kind) for name, kind in zip(DIMS, ("TIME", "CHANNEL", "SPACE", "SPACE", "SPACE")))
    for pyramid, levels in ((False, 0), (True, 2)):  # 600 -> 300 -> 150
        acquired = AcquiredRecord(
            name="run camera", position=0, detector="camera", data=data, axes=axes,
            channels=(), planes=(), registration=(), calibrated=False, pyramid=pyramid,
        )
        store._create_dataset(acquired, data, anchors=[])
        scales = created[-1]["scales"]
        assert len(scales) == levels
    assert [s.array.shape for s in scales] == [(1, 1, 2, 300, 150), (1, 1, 2, 150, 75)]
    assert all(s.scale_method == "MAX" for s in scales)
    assert np.array_equal(np.asarray(scales[0].array.data), data.reshape(1, 1, 2, 300, 2, 150, 2).max(axis=(4, 6)))


# --- histograms and the scene of a run ------------------------------------------------------------


def test_the_native_writer_counts_every_value_by_time_point_and_channel(tmp_path: Path) -> None:
    from newswitch.infra.mikro import histograms

    rng = np.random.default_rng(1)
    frames = {t: rng.integers(0, 4096, (2, 64, 64), dtype=np.uint16) for t in range(2)}
    upload = native.ShardedUpload.local(str(tmp_path), [2, 2, 3, 64, 64], "uint16", DIMS, 2)
    for t, frame in frames.items():
        for z in range(3):
            upload.write(t, 0, z, frame.ctypes.data, frame.nbytes, 64, 64, 2, 2, planar=True)
    upload.finish()
    counts = histograms.of_native(upload.histograms())
    assert sorted(counts) == [(0, 0), (0, 1), (1, 0), (1, 1)]
    for t, frame in frames.items():
        for c in range(2):
            want = np.bincount(frame[c].ravel(), minlength=65536) * 3  # three planes
            assert np.array_equal(counts[t, c], want)
    # the same counts as one held in memory has them counted
    data = np.stack([np.stack([frames[t]] * 3, axis=1) for t in range(2)])
    held = histograms.counted(data, tuple(DIMS))
    assert all(np.array_equal(held[key], counts[key]) for key in counts)


def test_a_histogram_is_summarised_as_mikro_takes_it() -> None:
    from newswitch.infra.mikro import histograms

    values = np.concatenate([np.full(98, 100), [10, 250]]).astype(np.uint8)
    summary = histograms.summarised(np.bincount(values, minlength=256).astype(np.uint64))
    assert summary is not None
    assert (summary.min, summary.max) == (10.0, 250.0)
    assert summary.p1 == 10.0 and summary.p99 == 100.0
    assert len(summary.bins) == histograms.BINS + 1 and sum(summary.histogram) == 100
    assert histograms.summarised(np.zeros(256, np.uint64)) is None
    [anchor] = histograms.anchors({(2, 1): np.bincount(values, minlength=256).astype(np.uint64)})
    assert [(a.axis, a.value) for a in anchor.axis_anchors] == [("t", 2), ("c", 1)]


class SceneClient(FakeMikro):
    """A mikro that records the scene, lenses and layers it is asked for."""

    def __init__(self) -> None:
        super().__init__()
        self.lenses: list[dict[str, Any]] = []

    def create_scene(self, **kwargs: Any) -> Any:  # noqa: ANN401
        self.calls.append(("scene", kwargs))
        return SimpleNamespace(id="scene-1")

    def create_lens(self, **kwargs: Any) -> Any:  # noqa: ANN401
        self.lenses.append(kwargs)
        return SimpleNamespace(id=f"lens-{len(self.lenses)}")

    def create_rgb_layer(self, **kwargs: Any) -> Any:  # noqa: ANN401
        self.calls.append(("rgb", kwargs))

    def create_intensity_layer(self, **kwargs: Any) -> Any:  # noqa: ANN401
        self.calls.append(("intensity", kwargs))


def test_a_run_gets_a_scene_of_its_datasets_with_their_contrast() -> None:
    """One scene over the sample's space: a color camera's dataset as one RGB layer, a mono one's
    a layer per channel, each with its 1st/99th percentile as contrast."""
    from newswitch.infra.mikro.store import MikroDatasetStore, _Shown
    from newswitch.models.acquisition import AcquiredDataset

    client = SceneClient()
    store = MikroDatasetStore(client, SimpleNamespace(name="frame"), SimpleNamespace())  # type: ignore[arg-type]
    ramp = np.bincount(np.arange(256, dtype=np.uint8), minlength=256).astype(np.uint64)
    store._shown = {
        "rgb": _Shown(space="sample-1", colors=("r", "g", "b"), histograms={(0, c): ramp for c in range(3)}),
        "mono": _Shown(space="sample-1", colors=(None,), histograms={(0, 0): ramp, (1, 0): ramp}),
    }
    datasets = [
        AcquiredDataset(id="rgb", name="run camera", position=0, detector="camera"),
        AcquiredDataset(id="mono", name="run other", position=0, detector="other"),
    ]
    assert store.show("run 2026-11-24 15:00", datasets) == ["scene-1"]
    scene = [c for c in client.calls if c[0] == "scene"]
    assert scene == [("scene", {"name": "run 2026-11-24 15:00", "coordinate_system": "sample-1"})]
    [rgb] = [c[1] for c in client.calls if c[0] == "rgb"]
    [mono] = [c[1] for c in client.calls if c[0] == "intensity"]
    assert rgb["scene"] == "scene-1" and (rgb["clim_min"], rgb["clim_max"]) == (2.0, 253.0)
    assert {rgb["red_lens"], rgb["green_lens"], rgb["blue_lens"]} == {"lens-2", "lens-3", "lens-4"}
    slices = [lens["slices"][0] for lens in client.lenses if "slices" in lens]
    assert [(s.axis, s.start, s.stop) for s in slices] == [("c", 0, 1), ("c", 1, 2), ("c", 2, 3), ("c", 0, 1)]
    assert mono["color"] is None and (mono["clim_min"], mono["clim_max"]) == (2.0, 253.0)


def test_the_acquisition_asks_for_a_scene_and_a_failing_one_loses_nothing(tmp_path: Path) -> None:
    m = built(tmp_path, "dual-camera")

    @dataclass
    class Showing(RecordingStore):
        shown: list[tuple[str, list[Any]]] = field(default_factory=list)

        def show(self, name: str, datasets: list[Any]) -> list[str]:  # noqa: ANN401
            self.shown.append((name, datasets))
            raise RuntimeError("no scenes today")

    store = Showing()
    acquire(m, plan([AcquisitionChannel(detectors=["camera_green"], name="green", set_to={**LASER})]), store)
    [(name, datasets)] = store.shown
    assert name.startswith("run ") and len(datasets) == len(store.published) == 1


# --- triggered cameras: each frame asked for, copied while the acquisition goes on ------------


def triggering(m: Any) -> list[tuple[str, str]]:  # noqa: ANN401
    """Make `m`'s detectors act as triggered cameras: each frame stays where it is until the next
    is asked for (`held`). What is begun, captured and ended, in order."""
    detector = m.detector
    calls: list[tuple[str, str]] = []
    detector.begin_triggered = lambda name: calls.append(("begin", name)) or True

    def capture_frame(name: str) -> FrameMemory:
        calls.append(("capture", name))
        return replace(FrameMemory.of_array(detector.capture_channels(name)), held=True)

    detector.capture_frame = capture_frame
    detector.end_triggered = lambda name: calls.append(("end", name))
    return calls


def test_a_triggered_acquisition_copies_each_exposure_while_it_goes_on(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Each camera is triggered for the whole run, not for each exposure; every exposure reaches
    its stream though it is copied beside what comes next; and the run says where its time went."""
    m = built(tmp_path, "dual-camera")
    calls = triggering(m)
    store = StreamingStore(root=tmp_path / "zarr")
    caplog.set_level("INFO", logger="newswitch.routines.acquire")
    acquire(
        m,
        plan(
            [AcquisitionChannel(detectors=["camera_green", "camera_red"], name="all", set_to={**LASER, **LED})],
            planes=[-2.0, 0.0, 2.0],
            times=2,
        ),
        store,
    )
    kinds = [kind for kind, _ in calls]
    assert kinds[:2] == ["begin", "begin"] and kinds[-2:] == ["end", "end"]
    assert kinds.count("capture") == 2 * 3 * 2
    for acquired in store.published:
        pixels = acquired.stream.finish()  # type: ignore[union-attr]
        assert all(pixels[t, 0, z].max() > 0 for t in range(2) for z in range(3))
    summary = next(r.getMessage() for r in caplog.records if "exposures in" in r.getMessage())
    assert "6 exposures" in summary and "setup" in summary and all(
        phase in summary for phase in ("move", "light", "camera", "write", "bookkeeping")
    )


def test_a_copy_that_fails_beside_the_run_stops_it_and_drops_what_it_streamed(
    tmp_path: Path,
) -> None:
    m = built(tmp_path, "dual-camera")
    calls = triggering(m)
    store = StreamingStore(root=tmp_path / "zarr", fail_after=1)
    with pytest.raises(RuntimeError, match="went away"):
        acquire(
            m,
            plan(
                [AcquisitionChannel(detectors=["camera_green"], name="green", set_to={**LASER})],
                planes=[-2.0, 0.0, 2.0],
            ),
            store,
        )
    assert store.opened and all(stream.aborted for stream in store.opened)
    assert calls[-1] == ("end", "camera_green")  # the camera runs free again, whatever happened


def test_an_acquisition_sets_a_light_only_when_it_changes(tmp_path: Path) -> None:
    """Each light is a write on the bus: set for the first exposure, and not again while every
    exposure lights alike."""
    m = built(tmp_path, "dual-camera")
    sets: list[dict[str, Any]] = []
    original = m.values.set

    def recording(targets: Any, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        sets.append(dict(targets))
        original(targets, *args, **kwargs)

    m.values.set = recording  # type: ignore[method-assign]
    acquire(
        m,
        plan(
            [AcquisitionChannel(detectors=["camera_green"], name="green", set_to={**LASER})],
            planes=[-2.0, 0.0, 2.0],
            times=2,
        ),
        StreamingStore(root=tmp_path / "zarr"),
    )
    lit = [targets for targets in sets if set(targets) & set(LASER)]
    assert len(lit) == 2  # set once at the start, off once at the end
    assert lit[-1] and all(value == 0 for value in lit[-1].values())
