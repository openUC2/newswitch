"""Registered routines: workflows across several managers. Importing this module registers them.

The routines themselves live in `newswitch.routines`. `run_autofocus` registers itself with
``@register`` in `newswitch.routines.autofocus`; it is imported here so that every
registration happens under `newswitch.registers`.
"""

from rekuest_next.app import get_default_app_registry

from newswitch.routines import autofocus  # noqa: F401  (registration side effects)
from newswitch.routines import (
    acquire_multidimensional_acquisition,
    calibrate_light_path,
    scan_region,
)

default_app_registry = get_default_app_registry()
default_app_registry.register(acquire_multidimensional_acquisition)
default_app_registry.register(calibrate_light_path)
default_app_registry.register(scan_region)
