# A declarative microscope

A worked example of a model for newswitch: you say where you want an image, and the microscope
works out what that takes. It is self-contained: the runtime does not import it, and the routines
and the camera are simulated (`simulated.py`).

```bash
uv run python -m examples.declarative_acquisition.demo     # the story, in the terminal
uv run pytest tests/test_declarative_acquisition.py        # what it promises
```

## The model

- **Cubes** say what they are and what their variables impact (`microscope.yaml`). They are
  reusable, so they name no light path.
- **Paths** say how light connects the cubes. Which actuator matters on which path follows from
  those two (`Instrument.impact_report`).
- **Calibrations** are how a quantity is obtained. A variable *selects* which calibration applies
  (the objective for the pixel size) or is *used* by it (x and y for a tilted focus plane). Time,
  events and what it depends on make one stale, and `on_stale` says what then happens.
- **One graph** connects images, the stage, a plate and the motors, as in mikro and OME-Zarr RFC-5.
  Going somewhere is walking that graph to the motors, so a position can be given in a plate or
  in an earlier image.
- **A request** is one image: where, and through which channel. `Instrument.plan` says what it
  takes before anything moves. An `Acquisition` is nothing but the requests it expands into.

## Mikro

On the instrument the light path decides and computes. In the data, mikro's `CoordinateAnchor` is
the hub, so a `Record` splits into its spokes on the way out (`mikro_export.py`): the light path, the
microscope state, the time, and one registration edge named by the calibration it used.

```bash
just mikro      # the stack in docker-compose.yml, profile "mikro"
MIKRO_URL=http://localhost:6580 MIKRO_DATALAYER_URL=http://localhost:6890 MIKRO_TOKEN=newswitch-dev \
    uv run --extra mikro python -m examples.declarative_acquisition.demo
```

## What it leaves out

- `microscope.yaml` is written by hand: nothing compiles it from a `.dsn` yet.
- The calibrations are simulated, and a failed check (Optimus' "bad data") is not modelled.
- `chromatic_shift` and `flat_field` are placeholders until we know which ones get corrected for.
- A rotated pixel calibration is refused on export: it needs an AFFINE edge, not `register`.
- It has one detector, one path, and no objective the plate registration depends on.
