"""What pretends to be the microscope: the digital twin.

The simulator renders what the design says a detector sees (`simulator`), and what the real copy
hides from it (``truth.yml``, read only here: `truth`); the simulated detectors (`detector`), the
virtual UC2 board (`uc2_bus`), the drivers of what is not wired (`drivers`) and a stream's test
pattern (`test_pattern`) stand in for the hardware.

Only the composition root (`newswitch.microscope`) picks these over the real thing; nothing of the
runtime imports them, and nothing here imports `newswitch.calibration`: the twin hides a deviation,
the calibration measures one, and they meet only in a test (``tests/test_layering.py``).
"""
