"""The UC2 board."""

from arkitekt import App

from newswitch.actions import uc2
from newswitch.calibration.mount import calibrate_mount
from newswitch.calibration.states import MountCalibrationState
from newswitch.microscope import locks
from newswitch.microscope.apps import core, detector, values
from newswitch.microscope.run import Run
from newswitch.microscope.startup import provide_mount_calibration, provide_uc2
from newswitch.protocols.uc2 import UC2BusManager
from newswitch.states.uc2 import UC2State

app = App("newswitch", app_context=Run)
app.registry.merge(core.app.registry).merge(values.app.registry).merge(detector.app.registry)

app.register_state(UC2State)
app.register_context(UC2BusManager)
app.register_startup(provide_uc2)
app.register_background(uc2.run_uc2_bus)
app.register_background(uc2.run_uc2_event_dispatch)
app.register_background(uc2.keep_firmware)
app.register_action(uc2.home_stage, locks=[locks.MOTION])
app.register_state(MountCalibrationState)
app.register_startup(provide_mount_calibration)
app.register_action(calibrate_mount, locks=[locks.MOTION, locks.TUNE, locks.DETECTOR])
app.register_action(uc2.stop_stage)
app.register_action(uc2.led_matrix_fill, locks=[locks.TUNE])
app.register_action(uc2.led_matrix_off, locks=[locks.TUNE])
app.register_action(uc2.uc2_scan_nodes)
app.register_action(uc2.home_objective, locks=[locks.SWAP])
app.register_action(uc2.galvo_set_position, locks=[locks.GALVO])
app.register_action(uc2.galvo_raster_scan, locks=[locks.GALVO])
app.register_action(uc2.galvo_stop)
app.register_action(uc2.galvo_get_status)
app.register_action(uc2.update_firmware, locks=[locks.MOTION, locks.SWAP, locks.TUNE, locks.GALVO])
