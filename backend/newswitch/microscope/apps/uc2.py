"""The UC2 boards: their buses, and what a board does of its own (its nodes, firmware, galvo).

Always included, as every part is: a microscope without a board has an empty `UC2Boards`, and its
actions nothing to choose from.
"""

from arkitekt import App

from newswitch.actions import uc2
from newswitch.calibration.mount import calibrate_mount
from newswitch.calibration.states import MountCalibrationState
from newswitch.drivers.uc2.boards import UC2Boards
from newswitch.microscope import locks
from newswitch.microscope.apps import core, detector, values
from newswitch.microscope.run import Run
from newswitch.microscope.startup import provide_mount_calibration, provide_uc2
from newswitch.states.uc2 import UC2State

app = App("newswitch", app_context=Run)
app.include(core.app, values.app, detector.app)

app.register_state(UC2State, name="uc2")
app.register_context(UC2Boards)
app.register_startup(provide_uc2)
app.register_background(uc2.run_uc2_bus)
app.register_background(uc2.run_uc2_event_dispatch)
app.register_background(uc2.keep_firmware)
# Where the holder sits: homes, holds for a person to check the light is on the calibration
# slide, finds its mark, writes the mount down. Its state is what a panel shows of it.
app.register_state(MountCalibrationState, name="mount_calibration")
app.register_startup(provide_mount_calibration)
app.register_action(calibrate_mount, locks=[locks.MOTION, locks.TUNE, locks.DETECTOR])
app.register_action(uc2.uc2_scan_nodes)
app.register_action(uc2.galvo_set_position, locks=[locks.GALVO])
app.register_action(uc2.galvo_raster_scan, locks=[locks.GALVO])
app.register_action(uc2.galvo_stop)
app.register_action(uc2.galvo_get_status)
# The bus is down while it flashes: nothing may move, swap, tune or scan meanwhile.
app.register_action(uc2.update_firmware, locks=[locks.MOTION, locks.SWAP, locks.TUNE, locks.GALVO])
