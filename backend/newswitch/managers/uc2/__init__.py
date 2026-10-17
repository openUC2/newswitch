"""Managers driving real openUC2 hardware.

Transport-agnostic device managers (stage, illumination, galvo) sit on top of
the ``UC2BusManager`` protocol; two real transports (``UC2CanBus`` via
uc2canopen, ``UC2RestBus`` via uc2rest) plus a simulator (``VirtualUC2Bus``)
are plug-in replacements for each other.
"""
