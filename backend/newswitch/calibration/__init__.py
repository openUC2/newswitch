"""What measures how this copy of the microscope differs from its design.

The routines (`light_path`: how large a pixel is on the sample, and how the image lies on the
stage; `mount`: where a holder really sits), their arithmetic (`affine`), what they found
(`models`, `states`) and the manager that keeps it (`manager`).

Only the composition root (`newswitch.microscope`) and the app register these; the runtime reads
what was calibrated through `newswitch.protocols.calibration`. Nothing here imports
`newswitch.simulation`.
"""
