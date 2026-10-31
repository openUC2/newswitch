"""An acquisition in a real mikro: run with the stack up (`just mikro`) and its MIKRO_* set.

    MIKRO_URL=http://localhost:6580 MIKRO_DATALAYER_URL=http://localhost:6890 \\
        MIKRO_TOKEN=newswitch-dev uv run --extra mikro pytest tests/test_mikro_acquisition.py

Everything is read back from the server: nothing here looks at what was sent.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pint
import pytest
from arkitekt import Task
from arkitekt_fastapi.testing import AsyncAgentTestClient

pytest.importorskip("mikro")

from mikro import Mikro, space_3d  # noqa: E402
from scipy import ndimage  # noqa: E402

from main_fastapi import create_app  # noqa: E402
from newswitch.accounts.auth import AllowAllAuthenticator  # noqa: E402
from newswitch.instrument import spec  # noqa: E402
from newswitch.microscope.parts import build_microscope  # noqa: E402
from newswitch.models.acquisition import (  # noqa: E402
    AcquiredDataset,
    MultidimensionalAcquisition,
    Position,
    Stack,
    StreamIllumination,
    Streams,
    Timepoint,
)
from newswitch.routines.multidimensional_acquisition import (  # noqa: E402
    acquire_multidimensional_acquisition,
)
from newswitch.services.mikro_connection import MikroConnection  # noqa: E402
from newswitch.services.mikro_store import MikroDatasetStore  # noqa: E402
from tests.conftest import collect_until_completed, run_settings  # noqa: E402

INSTRUMENTS = Path(__file__).parent.parent / "instruments"
LASER = StreamIllumination("laser_488", 488.0, 0.8)
LED = StreamIllumination("led_625", 625.0, 0.5)
Quantity = pint.UnitRegistry().Quantity

pytestmark = pytest.mark.skipif(
    not os.environ.get("MIKRO_URL"), reason="needs the mikro stack (just mikro) and MIKRO_URL"
)

ANCHORS = """
query ($id: ID!) {
  arrayDataset(id: $id) {
    anchors(pagination: {limit: 1000}) {
      coordinates
      channelLabel { label }
      lightGraph { id }
      acquisitionWindow { start end }
      microscope { state { stage { x y z } devices { label settings { name number } } } }
    }
  }
}
"""


def graphql(query: str, **variables: Any) -> dict[str, Any]:  # noqa: ANN401
    """Ask the server directly, so that the answer is what it holds."""
    request = urllib.request.Request(
        f"{os.environ['MIKRO_URL']}/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['MIKRO_TOKEN']}",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        answer = json.load(response)
    assert "errors" not in answer, answer["errors"]
    return answer["data"]


@pytest.fixture
def mikro() -> Iterator[Mikro]:
    """A client of the running mikro."""
    connection = MikroConnection.from_env()
    assert connection is not None
    with connection.client() as client:
        yield client


def run(
    mikro: Mikro,
    tmp_path: Path,
    instrument: str,
    streams: list[Streams],
    places: tuple[tuple[float, float], ...] = ((0.0, 0.0),),
    planes: list[float] | None = None,
    times: int = 1,
) -> list[AcquiredDataset]:
    """The routine on a simulated instrument, through the store a server would use."""
    described = spec.load(INSTRUMENTS / instrument)
    m = build_microscope(run_settings(tmp_path), described)
    positions = [
        Position(
            x=x,
            y=y,
            z=0.0,
            stacks=[Stack(z_offset=0.0, z_slices=planes or [], z_step=1.0, channels=streams)],
        )
        for x, y in places
    ]
    return acquire_multidimensional_acquisition(
        MultidimensionalAcquisition(
            timepoints=[Timepoint(positions=positions) for _ in range(times)],
            file_name=f"test {uuid.uuid4().hex[:8]}",
        ),
        MikroDatasetStore(mikro, described, m),
        m.optics,
        m.detector,
        m.values,
        m.calibration_state,
        m.metadata,
        m.hooks,
        Task.local(),
    )


def anchors_of(dataset_id: str) -> list[dict[str, Any]]:
    """Every anchor of a dataset, as the server holds them."""
    return graphql(ANCHORS, id=dataset_id)["arrayDataset"]["anchors"]


def coordinates_of(anchor: dict[str, Any]) -> dict[str, int]:
    """An anchor's coordinates, by axis."""
    coordinates = anchor["coordinates"]
    if isinstance(coordinates, dict):
        return coordinates
    return {item["axis"]: item["value"] for item in coordinates}


def test_two_detectors_merge_into_one_dataset(mikro: Mikro, tmp_path: Path) -> None:
    """t, c, z, y, x on the server, and the pixels of both cameras in it."""
    (made,) = run(
        mikro,
        tmp_path,
        "dual-camera",
        [
            Streams(
                detectors=["camera_green", "camera_red"], mapping="all", illuminations=[LASER, LED]
            )
        ],
        planes=[-2.0, 0.0, 2.0],
        times=2,
    )
    dataset = mikro.get_array_dataset(made.id)
    assert tuple(dataset.axis_names) == ("t", "c", "z", "y", "x")
    assert tuple(dataset.shape) == (2, 2, 3, 512, 512)
    data = np.asarray(dataset.data)
    assert data.shape == (2, 2, 3, 512, 512)
    assert data.max() > 200
    # the two channels really are two images
    assert not np.array_equal(data[0, 0, 0], data[0, 1, 0])


def test_every_channel_and_plane_has_its_anchor(mikro: Mikro, tmp_path: Path) -> None:
    """A channel's label and light path; a plane's microscope state and time."""
    (made,) = run(
        mikro,
        tmp_path,
        "dual-camera",
        [Streams(detectors=["camera_green", "camera_red"], mapping="gfp", illuminations=[LASER])],
        planes=[-1.0, 1.0],
    )
    anchors = anchors_of(made.id)

    labels = {
        coordinates_of(a)["c"]: a["channelLabel"]["label"] for a in anchors if a["channelLabel"]
    }
    assert labels == {0: "gfp camera_green", 1: "gfp camera_red"}
    assert all(a["lightGraph"] for a in anchors if a["channelLabel"])

    planes = [a for a in anchors if a["microscope"]]
    assert {tuple(sorted(coordinates_of(a).items())) for a in planes} == {
        (("c", c), ("t", 0), ("z", z)) for c in range(2) for z in range(2)
    }
    assert all(a["acquisitionWindow"]["start"] for a in planes)
    stage_z = {
        coordinates_of(a)["z"]: float(str(a["microscope"]["state"]["stage"]["z"]).split()[0])
        for a in planes
    }
    assert stage_z[1] - stage_z[0] == pytest.approx(2.0)


def test_positions_share_a_stage_space(mikro: Mikro, tmp_path: Path) -> None:
    """Through mikro's own transforms, a bead seen from two positions is at one stage point."""
    first, second = run(
        mikro,
        tmp_path,
        "dual-camera",
        [Streams(detectors=["camera_green"], mapping="gfp", illuminations=[LASER])],
        places=((0.0, 0.0), (60.0, 40.0)),
    )
    world = space_3d(mikro, "stage", reference="stage-dual-camera")

    def bead_in_stage(made: AcquiredDataset) -> np.ndarray:
        dataset = mikro.get_array_dataset(made.id)
        image = ndimage.gaussian_filter(np.asarray(dataset.data)[0, 0, 0].astype(float), 2.0)
        row, column = np.unravel_index(np.argmax(image), image.shape)
        return np.asarray(
            dataset.intrinsic_system.transform_points_to(
                world, [[0, 0, 0, row, column]], axes=("z", "y", "x")
            )
        )[0]

    assert bead_in_stage(first)[1:] == pytest.approx(bead_in_stage(second)[1:], abs=2.0)


def test_an_rgb_camera_is_three_labelled_channels(mikro: Mikro, tmp_path: Path) -> None:
    """On the server as well."""
    (made,) = run(
        mikro,
        tmp_path,
        "rgb-camera",
        [Streams(detectors=["camera"], mapping="gfp", illuminations=[LASER])],
    )
    assert tuple(mikro.get_array_dataset(made.id).shape) == (1, 3, 1, 512, 512)
    labels = {
        coordinates_of(a)["c"]: a["channelLabel"]["label"]
        for a in anchors_of(made.id)
        if a["channelLabel"]
    }
    assert labels == {0: "gfp camera r", 1: "gfp camera g", 2: "gfp camera b"}


@pytest.mark.asyncio
async def test_a_served_agent_acquires_into_mikro(tmp_path: Path) -> None:
    """The action through a real agent: the client lives on the loop, the action on its thread."""
    settings = run_settings(tmp_path, instrument=INSTRUMENTS / "dual-camera")
    app = create_app(settings, AllowAllAuthenticator())
    name = f"served {uuid.uuid4().hex[:8]}"
    config = {
        "file_name": name,
        "m_hooks": [],
        "timepoints": [
            {
                "t_hooks": [],
                "position_order": "SEQUENTIAL",
                "positions": [
                    {
                        "x": 0.0,
                        "y": 0.0,
                        "z": 0.0,
                        "p_hooks": [],
                        "stacks": [
                            {
                                "z_offset": 0.0,
                                "z_slices": [],
                                "z_step": 1.0,
                                "z_hooks": [],
                                "channels": [
                                    {
                                        "detectors": ["camera_green", "camera_red"],
                                        "mapping": "gfp",
                                        "illuminations": [
                                            {
                                                "source": "laser_488",
                                                "wavelength": 488.0,
                                                "intensity": 0.8,
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    async with AsyncAgentTestClient(app) as client:
        started = await client.assign("acquire_multidimensional_acquisition", {"config": config})
        events = await collect_until_completed(client, started.task_id, timeout=60.0)
    # Not the last event: the test client drops frames when its 0.1 s read times out, so whether
    # COMPLETED reaches it is chance. The server holding the dataset is what counts.
    assert not [event for event in events if event.event_type in ("FAILED", "CRITICAL")], events
    found: list[dict[str, Any]] = []
    for _ in range(60):
        found = graphql(
            "query ($name: String!) { arrayDatasets(filters: {search: $name}) { id name shape } }",
            name=name,
        )["arrayDatasets"]
        if found:
            break
        await asyncio.sleep(0.5)
    assert [d["name"] for d in found if d["name"] == name] == [name]


def test_a_stack_the_camera_sweeps_reaches_the_server(mikro: Mikro, tmp_path: Path) -> None:
    """The light sheet: one sweep, each plane anchored where the stage really was."""
    (made,) = run(
        mikro,
        tmp_path,
        "light-sheet",
        [Streams(detectors=["camera"], mapping="gfp", illuminations=[LASER])],
        planes=[-1.0, -0.5, 0.0, 0.5, 1.0],
    )
    dataset = mikro.get_array_dataset(made.id)
    assert tuple(dataset.axis_names) == ("t", "c", "z", "y", "x")
    assert tuple(dataset.shape) == (1, 1, 5, 512, 512)
    assert np.asarray(dataset.data).max() > 200
    stage_z = sorted(
        Quantity(anchor["microscope"]["state"]["stage"]["z"]).to("um").magnitude
        for anchor in anchors_of(made.id)
        if anchor["microscope"] is not None
    )
    assert stage_z == pytest.approx([-1.0, -0.5, 0.0, 0.5, 1.0])


def test_a_flim_dataset_has_a_microtime_axis_on_the_server(mikro: Mikro, tmp_path: Path) -> None:
    """Arrival time, in the order and of the type mikro has for it."""
    (made,) = run(
        mikro,
        tmp_path,
        "flim",
        [Streams(detectors=["spad"], mapping="gfp", illuminations=[LASER])],
    )
    dataset = mikro.get_array_dataset(made.id)
    assert tuple(dataset.axis_names) == ("t", "c", "m", "z", "y", "x")
    assert tuple(dataset.shape) == (1, 1, 64, 1, 512, 512)
    data = np.asarray(dataset.data)
    assert data[0, 0, 0].sum() > data[0, 0, 40].sum() > 0
    axes = graphql(
        "query ($id: ID!) { arrayDataset(id: $id) { intrinsicSystem { axes { name type } } } }",
        id=made.id,
    )["arrayDataset"]["intrinsicSystem"]["axes"]
    assert {axis["name"]: axis["type"] for axis in axes}["m"] == "MICROTIME"
