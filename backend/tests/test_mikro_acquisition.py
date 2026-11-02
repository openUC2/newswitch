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

from main_fastapi import create_app  # noqa: E402
from newswitch.infra.accounts.auth import AllowAllAuthenticator  # noqa: E402
from newswitch.instrument import spec  # noqa: E402
from newswitch.microscope.parts import Microscope, build_microscope  # noqa: E402
from newswitch.models.acquisition import AcquiredDataset, AcquisitionChannel  # noqa: E402
from newswitch.routines.acquire import acquire  # noqa: E402
from newswitch.infra.mikro.connection import MikroConnection  # noqa: E402
from newswitch.infra.mikro.store import MikroDatasetStore  # noqa: E402
from tests.test_acquire import assert_same_beads, bead_pixels
from tests.conftest import acquisition, collect_until_completed, run_settings  # noqa: E402

INSTRUMENTS = Path(__file__).parent.parent / "instruments"
LASER = {"laser_488.power": 40.0}
LED = {"led_625.power": 2.5e-5}
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


#: The microscopes `run` built, newest last: what their datasets were placed in is theirs.
BUILT: list[Microscope] = []


def run(
    mikro: Mikro,
    tmp_path: Path,
    instrument: str,
    streams: list[AcquisitionChannel],
    places: tuple[tuple[float, float], ...] = ((0.0, 0.0),),
    planes: list[float] | None = None,
    times: int = 1,
) -> list[AcquiredDataset]:
    """The routine on a simulated instrument, through the store a server would use."""
    described = spec.load(INSTRUMENTS / instrument)
    m = build_microscope(run_settings(tmp_path), described)
    BUILT.append(m)
    return acquire(
        acquisition(streams, planes, times, places, name=f"test {uuid.uuid4().hex[:8]}"),
        MikroDatasetStore(mikro, described, m),
        m.optics,
        m.detector,
        m.values,
        m.space,
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


def test_two_detectors_are_a_dataset_each(mikro: Mikro, tmp_path: Path) -> None:
    """t, c, z, y, x on the server, each camera's pixels in its own."""
    made = run(
        mikro,
        tmp_path,
        "dual-camera",
        [
            AcquisitionChannel(
                detectors=["camera_green", "camera_red"], name="all", set_to={**LASER, **LED}
            )
        ],
        planes=[-2.0, 0.0, 2.0],
        times=2,
    )
    assert [dataset.detector for dataset in made] == ["camera_green", "camera_red"]
    green, red = (np.asarray(mikro.get_array_dataset(d.id).data) for d in made)
    for d in made:
        dataset = mikro.get_array_dataset(d.id)
        assert tuple(dataset.axis_names) == ("t", "c", "z", "y", "x")
        assert tuple(dataset.shape) == (2, 1, 3, 512, 512)
    assert max(green.max(), red.max()) > 200
    # the two cameras really took two images
    assert not np.array_equal(green[0, 0, 0], red[0, 0, 0])


def test_every_channel_and_plane_has_its_anchor(mikro: Mikro, tmp_path: Path) -> None:
    """A channel's label and light path; a plane's microscope state and time."""
    made, _ = run(
        mikro,
        tmp_path,
        "dual-camera",
        [AcquisitionChannel(detectors=["camera_green", "camera_red"], name="gfp", set_to=LASER)],
        planes=[-1.0, 1.0],
    )
    anchors = anchors_of(made.id)

    labels = {
        coordinates_of(a)["c"]: a["channelLabel"]["label"] for a in anchors if a["channelLabel"]
    }
    assert labels == {0: "gfp camera_green"}
    assert all(a["lightGraph"] for a in anchors if a["channelLabel"])

    planes = [a for a in anchors if a["microscope"]]
    assert {tuple(sorted(coordinates_of(a).items())) for a in planes} == {
        (("c", 0), ("t", 0), ("z", z)) for z in range(2)
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
        [AcquisitionChannel(detectors=["camera_green"], name="gfp", set_to=LASER)],
        places=((0.0, 0.0), (60.0, 40.0)),
    )
    world = space_3d(
        mikro,
        "sample",
        reference=f"sample-dual-camera-stage-{BUILT[-1].space_state.samples['stage'].mount_id}",
    )

    def beads_in_stage(made: AcquiredDataset) -> np.ndarray:
        dataset = mikro.get_array_dataset(made.id)
        pixels = bead_pixels(np.asarray(dataset.data)[0, 0, 0])
        return np.asarray(
            dataset.intrinsic_system.transform_points_to(
                world, [[0, 0, 0, row, column] for row, column in pixels], axes=("z", "y", "x")
            )
        )[:, 1:]

    assert_same_beads(beads_in_stage(first), beads_in_stage(second))


def test_an_rgb_camera_is_three_labelled_channels(mikro: Mikro, tmp_path: Path) -> None:
    """On the server as well."""
    (made,) = run(
        mikro,
        tmp_path,
        "rgb-camera",
        [AcquisitionChannel(detectors=["camera"], name="gfp", set_to=LASER)],
    )
    assert tuple(mikro.get_array_dataset(made.id).shape) == (1, 3, 1, 512, 512)
    labels = {
        coordinates_of(a)["c"]: a["channelLabel"]["label"]
        for a in anchors_of(made.id)
        if a["channelLabel"]
    }
    assert labels == {0: "gfp camera r", 1: "gfp camera g", 2: "gfp camera b"}


def test_a_thermometer_is_a_scalar_dataset_at_its_point(mikro: Mikro, tmp_path: Path) -> None:
    """Beside the camera's images, its readings: one position along z, y and x, which mikro's own
    transforms put 3 cm from the section, in the sample space the camera's images are in."""
    camera, thermometer = run(
        mikro,
        tmp_path,
        "he-microscope",
        [AcquisitionChannel(detectors=["camera", "thermometer"], name="air")],
        planes=[0.0, 1.0],
    )
    assert (camera.detector, thermometer.detector) == ("camera", "thermometer")
    dataset = mikro.get_array_dataset(thermometer.id)
    assert tuple(dataset.axis_names) == ("t", "c", "plane", "z", "y", "x")
    assert tuple(dataset.shape) == (1, 1, 2, 1, 1, 1)
    readings = np.asarray(dataset.data)
    assert np.all(np.abs(readings - 22.0) < 0.5)
    world = space_3d(
        mikro,
        "sample",
        reference=f"sample-he-microscope-stage-{BUILT[-1].space_state.samples['stage'].mount_id}",
    )
    (point,) = np.asarray(
        dataset.intrinsic_system.transform_points_to(
            world, [[0, 0, 1, 0, 0, 0]], axes=("z", "y", "x")
        )
    )
    assert point == pytest.approx([0.0, 0.0, 30_000.0])
    labels = [a["channelLabel"]["label"] for a in anchors_of(thermometer.id) if a["channelLabel"]]
    assert labels == ["air thermometer (degC)"]


@pytest.mark.asyncio
async def test_a_served_agent_acquires_into_mikro(tmp_path: Path) -> None:
    """The action through a real agent: the client lives on the loop, the action on its thread."""
    settings = run_settings(tmp_path, instrument=INSTRUMENTS / "dual-camera")
    app = create_app(settings, AllowAllAuthenticator())
    name = f"served {uuid.uuid4().hex[:8]}"
    config = {
        "channels": [
            {
                "detectors": ["camera_green", "camera_red"],
                "name": "gfp",
                "set_to": {"laser_488.power": 40.0},
            }
        ],
        "positions": [{"set_to": {"stage.x": 0.0, "stage.y": 0.0, "stage.z": 0.0}, "name": ""}],
        "stack": {"offsets": [], "variable": None},
        "times": 1,
        "every_s": 0.0,
        "order": "SEQUENTIAL",
        "name": name,
        "m_hooks": [],
        "t_hooks": [],
        "p_hooks": [],
        "z_hooks": [],
    }
    async with AsyncAgentTestClient(app) as client:
        started = await client.assign("acquire", {"plan": config})
        events = await collect_until_completed(client, started.task_id, timeout=60.0)
    # Not the last event: the test client drops frames when its 0.1 s read times out, so whether
    # COMPLETED reaches it is chance. The server holding the dataset is what counts.
    assert not [event for event in events if event.event_type in ("FAILED", "CRITICAL")], events
    wanted = [f"{name} camera_green", f"{name} camera_red"]
    found: list[str] = []
    for _ in range(60):
        found = sorted(
            d["name"]
            for d in graphql(
                "query ($name: String!) { arrayDatasets(filters: {search: $name}) { id name } }",
                name=name,
            )["arrayDatasets"]
            if d["name"] in wanted
        )
        if found == wanted:
            break
        await asyncio.sleep(0.5)
    assert found == wanted


def test_a_stack_the_camera_sweeps_reaches_the_server(mikro: Mikro, tmp_path: Path) -> None:
    """The light sheet: one sweep of the sheet, each plane anchored where the sheet really was."""
    (made,) = run(
        mikro,
        tmp_path,
        "light-sheet",
        [AcquisitionChannel(detectors=["camera"], name="gfp", set_to=LASER)],
        planes=[-1.0, -0.5, 0.0, 0.5, 1.0],
    )
    dataset = mikro.get_array_dataset(made.id)
    assert tuple(dataset.axis_names) == ("t", "c", "z", "y", "x")
    assert tuple(dataset.shape) == (1, 1, 5, 512, 512)
    assert np.asarray(dataset.data).max() > 200
    anchored = [
        anchor["microscope"]["state"] for anchor in anchors_of(made.id) if anchor["microscope"]
    ]
    sheet_z = sorted(
        float(setting["number"])
        for state in anchored
        for device in state["devices"]
        if device["label"] == "sheet_lens"
        for setting in device["settings"]
    )
    assert sheet_z == pytest.approx([-1.0, -0.5, 0.0, 0.5, 1.0])
    assert {Quantity(state["stage"]["z"]).to("um").magnitude for state in anchored} == {0.0}


def test_a_flim_dataset_has_a_microtime_axis_on_the_server(mikro: Mikro, tmp_path: Path) -> None:
    """Arrival time, in the order and of the type mikro has for it."""
    (made,) = run(
        mikro,
        tmp_path,
        "flim",
        [AcquisitionChannel(detectors=["spad"], name="gfp", set_to=LASER)],
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
