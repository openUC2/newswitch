"""The example, told as a story: what a declarative microscope plans, and why.

    uv run python -m examples.declarative_acquisition.demo

With the mikro stack up (`just mikro`) it also writes its images there, the way FastAPI mode is
configured by hand:

    MIKRO_URL=http://localhost:6580 MIKRO_DATALAYER_URL=http://localhost:6890 \\
        MIKRO_TOKEN=newswitch-dev uv run --extra mikro \\
        python -m examples.declarative_acquisition.demo
"""

from examples.declarative_acquisition import simulated
from examples.declarative_acquisition.instrument import (
    Acquisition,
    Blocked,
    Position,
    Record,
    Request,
)
from newswitch.services.mikro_connection import MikroConnection


def heading(text: str) -> None:
    """Start a chapter."""
    print(f"\n=== {text}")


def main() -> None:
    """Run the story."""
    clock = simulated.Clock()
    instrument = simulated.instrument(clock)
    records: list[Record] = []

    heading("What impacts what: derived from what the cubes declare, not written down")
    for row in instrument.impact_report():
        actuator = row["actuator"] or "-"
        print(
            f"  {row['variable']:24} {actuator:8} {row['relation']:8} "
            f"{row['quantity']:18} on {', '.join(row['paths'])}"
        )

    heading("Nothing calibrated: it says so, repairs what it can, and takes a nominal pixel size")
    plan = instrument.plan(Request(Position("stage", 100.0, 50.0), "gfp"))
    print(plan.describe())
    records.append(instrument.apply(plan))
    print(f"  -> {records[-1].image}: placement {records[-1].validity.name}")

    heading("Measure the pixel size: the image is now placed by a measurement")
    instrument.calibrate("pixel_to_sample", "epi-488")
    plan = instrument.plan(Request(Position("stage", 100.0, 50.0), "gfp"))
    print(plan.describe())
    records.append(instrument.apply(plan))
    print(f"  -> {records[-1].image}: placement {records[-1].validity.name}")

    heading("Another filter: the laser goes off first. The pixel size still holds")
    print(instrument.plan(Request(Position("stage", 100.0, 50.0), "reflection")).describe())

    heading("Another objective: the pixel size and the focus need their own calibration")
    plan = instrument.plan(Request(Position("stage", 100.0, 50.0), "gfp", {"objective.slot": 2}))
    print(plan.describe())

    heading("Another exposure: only the dark frame cares")
    plan = instrument.plan(
        Request(Position("stage", 100.0, 50.0), "gfp", {"camera.exposure_ms": 500.0})
    )
    print("\n".join(line for line in plan.describe().splitlines() if "needs" in line))

    heading("A plate that is not registered cannot be reached")
    plan = instrument.plan(Request(Position("plate-1", 9000.0, 9000.0), "gfp"))
    print(plan.describe())
    try:
        instrument.apply(plan)
    except Blocked as refused:
        print(f"  -> refused before anything moved: {refused}")

    heading("Register it: the position in the plate goes through the graph to the motors")
    instrument.calibrate("plate_registration", "epi-488")
    print(instrument.plan(Request(Position("plate-1", 9000.0, 9000.0), "gfp")).describe())

    heading("A point in an earlier image is a place to go")
    earlier = records[-1]
    print(instrument.plan(Request(Position(earlier.image, 0.0, 0.0), "gfp")).describe())

    heading("Three hours later: only the focus has aged out")
    clock.advance(3)
    plan = instrument.plan(Request(Position("stage", 100.0, 50.0), "gfp"))
    print("\n".join(line for line in plan.describe().splitlines() if "repair" in line))

    heading("A power cycle: the stage has lost its zero, and with it plate and focus")
    instrument.apply(plan)
    instrument.event("power-cycle")
    plan = instrument.plan(Request(Position("plate-1", 9000.0, 9000.0), "gfp"))
    print(plan.describe())

    heading("A multidimensional acquisition is nothing but requests, each planned on its own")
    instrument.calibrate("stage_zero", "epi-488")
    instrument.calibrate("plate_registration", "epi-488")
    acquisition = Acquisition(
        positions=(Position("plate-1", 9000.0, 9000.0), Position("plate-1", 18000.0, 9000.0)),
        channels=("gfp", "reflection"),
        z_offsets=(-2.0, 2.0),
    )
    before = len(instrument.log)
    for request in acquisition.requests():
        records.append(instrument.apply(instrument.plan(request)))
    print(f"  {len(list(acquisition.requests()))} images, {len(instrument.log) - before} steps:")
    print("  " + ", ".join(instrument.log[before : before + 14]) + ", ...")

    connection = MikroConnection.from_env()
    if connection is None:
        heading("MIKRO_URL is not set: nothing is written to mikro")
        return
    from examples.declarative_acquisition.mikro_export import publish

    heading(f"Writing to mikro at {connection.url}")
    with connection.client() as mikro:
        for record in (records[0], records[1], records[-1]):
            dataset = publish(mikro, instrument, record)
            print(f"  {record.image} -> dataset {dataset.id}, placement {record.validity.name}")


if __name__ == "__main__":
    main()
