"""What delivers images."""

from arkitekt import App

from newswitch.actions import detector
from newswitch.microscope import locks
from newswitch.microscope.apps import core
from newswitch.microscope.run import Run
from newswitch.microscope.startup import provide_detector
from newswitch.protocols.acquisition import AcquisitionManager
from newswitch.protocols.detector import DetectorManager
from newswitch.states.detector import DetectorState

app = App("newswitch", app_context=Run)
app.registry.merge(core.app.registry)
app.register_state(DetectorState, required_locks=[locks.DETECTOR])
app.register_context(DetectorManager, locks=[locks.DETECTOR])
app.register_context(AcquisitionManager, locks=[locks.EXPANSE, locks.IO])
app.register_startup(provide_detector)
app.register_shutdown(detector.close_detector)
app.register_background(detector.run_detector_loop)
app.register_action(detector.capture_image)
app.register_action(detector.start_live_view)
app.register_action(detector.stop_live_view)
app.register_action(detector.activate_detector)
app.register_action(detector.deactivate_detector)
app.register_action(detector.set_window)
