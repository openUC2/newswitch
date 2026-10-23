"""What newswitch can do, per part of the microscope: plain functions, nothing registered here.

`newswitch.microscope.registry.create_registry` imports these modules and registers each function
whose part the device configuration has (`stage` only with a stage, `uc2` only with a UC2
board, ...). The routines that need several parts live in `newswitch.routines`.
"""
