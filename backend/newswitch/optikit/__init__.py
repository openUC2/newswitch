"""optikit, vendored: reading optikit designs (``.dsn`` folders) in newswitch.

`dsn` evaluates a design: its devices (`dsn.devices`), its 3D model with a joint per input
(`dsn.build`, `dsn.simplify`) and the scene blok that moves that model (`dsn.scene`).
newswitch uses it through `newswitch.design`.
"""

from newswitch.optikit import dsn

__all__ = ["dsn"]
