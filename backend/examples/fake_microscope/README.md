# A fake microscope

Stands in for a rig we don't have at hand. It has a description of what the designer believes
(`microscope.yml`) and a hidden truth about what is really there (`truth.yml`), so predictions can be
compared with images, and we can check whether the comparison catches what is wrong.

```bash
uv run --with optiland python -m examples.fake_microscope.demo
uv run --with optiland pytest tests/test_fake_microscope.py
```

Optiland is deliberately not a dependency: it only runs when compiling, on a real computer.

## How it fits together

| File | What it does | May it read the truth? |
|---|---|---|
| `spec.py` | Loads the description: cubes, elements, how light connects them | No |
| `optics.py` | Ray traces each route, and multiplies transmission curves. The only module importing optiland | No: errors are passed in |
| `compiler.py` | Traces every swap combination and nudges every variable, writing `compiled.json` | No |
| `predict.py` | Answers from `compiled.json`, with no optics library: what the microscope itself runs | No |
| `hardware.py` | The fake instrument: renders images from the truth | Yes, the only one |
| `demo.py` | Runs the loop, and reveals the truth at the end | After everyone has answered |

## The model

- A **cube** is housing around an optical **element**. An actuator **moves**, **swaps** or **tunes** it.
- A **sensor's size lives on its axes**, and nowhere else.
- **Routes** are found by walking the edges from the sample, so another detector is another few edges.
- **What impacts what is calculated:** nudge a variable, compare the answers, against a tolerance.

## What this does and does not prove

It proves the pipeline: compile, predict, measure, detect a mismatch. It does **not** prove that ray
tracing matches a real instrument: the images come from the same tracer as the predictions, so only
the errors in `truth.yml` can differ. Only images from real hardware can show that.

Also simplified:
- The objectives are ideal lenses, and the only prescription (`lenses/AC254-100-A.optiland`) is a real
  achromat used as a tube lens.
- Filters and dichroics only shape the spectrum; the wedge is added by `hardware.py`, not traced.
- A mirror only flips the image: routes are traced unfolded.
- Light levels are relative, and the sample is a plane.
