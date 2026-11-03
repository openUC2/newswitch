"""Everything the frontend can call: actions (``@register``), routines and bloks.

Importing this package registers all of them on the default app registry; `newswitch.app`
imports it for these side effects. One module per device, plus `uc2` (the UC2 bus itself),
`routines`, `debug` (test and demo actions) and `bloks` (last: bloks refer to actions).
"""

from newswitch.registers import (  # noqa: F401  (registration side effects)
    debug,
    detector,
    expanse,
    filter_bank,
    illumination,
    objective,
    routines,
    stage,
    uc2,
)
from newswitch.registers import bloks  # noqa: F401  (registration side effects)
