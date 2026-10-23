"""Managers driving real openUC2 hardware.

Transport-agnostic device managers (stage, illumination, objective, filter bank) sit on top of
the ``UC2BusManager`` protocol; two real transports (``UC2CanBus`` via
uc2canopen, ``UC2RestBus`` via uc2rest) plus a simulator (``VirtualUC2Bus``)
are plug-in replacements for each other.

``uc2_detector`` holds the ``UC2DetectorManager`` for cameras driven through uc2_cam_py
(extra "camera"). It is deliberately not imported here: this package is always loaded,
uc2_cam_py is optional, so the app imports the module only when cameras are configured.
"""
