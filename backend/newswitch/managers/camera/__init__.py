"""
Camera Managers

Detector managers for real cameras, driven through the camera library uc2_cam_py (extra
"camera"). Importing this package imports uc2_cam_py, so the app imports it only when
cameras are configured.
"""

from .uc2_cam_detector import UC2CamDetectorManager

__all__ = ["UC2CamDetectorManager"]
