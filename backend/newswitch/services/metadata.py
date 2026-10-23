"""A metadata manager that collects the current state of the microscope and the light path configuration to generate metadata for acquired images."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Protocol

import numpy as np

from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.frames import Metadata
from newswitch.models.light_path import (
    AffineMatrix,
    DetectorKube,
    DetectorKubeState,
    DichroicKube,
    DichroicKubeState,
    FilterBankKube,
    FilterBankKubeState,
    FilterKube,
    FilterKubeState,
    GenericKube,
    GenericKubeState,
    IlluminationKube,
    IlluminationKubeState,
    KubeState,
    LightEdgeState,
    LightPath,
    LightPathSnapshot,
    ObjectiveKube,
    ObjectiveKubeState,
    ObjectiveTurretKube,
    StageKube,
    StageKubeState,
)
from newswitch.states.calibration import CalibrationState
from newswitch.states.detector import CameraState
from newswitch.states.filter_bank import FilterBankState
from newswitch.states.illumination import IlluminationState
from newswitch.states.objective import ObjectiveState
from newswitch.states.stage import StageState


class KubeLike(Protocol):
    """Structural type for any kube whose identifying and calibration fields can be serialized."""

    kube_id: str
    affine_matrix: AffineMatrix
    model_file: str | None
    model_name: str | None


def with_kube_metadata(cube: KubeLike) -> Dict[str, Any]:
    """Helper function to extract metadata from a kube-like object."""
    return {
        "kube_id": cube.kube_id,
        "affine_matrix": cube.affine_matrix,
        "model_file": cube.model_file,
        "model_name": cube.model_name,
    }


class MetadataManager:
    """Registry and execution for acquisition hooks."""

    def __init__(
        self,
        objective_state: ObjectiveState,
        filter_bank_state: FilterBankState,
        illumination_state: IlluminationState,
        stage_state: StageState,
        camera_state: CameraState,
        calibration_state: CalibrationState,
    ) -> None:
        """Initialize the MetadataManager with all the necessary states (to retrieve the state from and the) and light paths."""
        self._objective_state = objective_state
        self._filter_bank_state = filter_bank_state
        self._illumination_state = illumination_state
        self._stage_state = stage_state
        self._camera_state = camera_state
        self._calibration_state = calibration_state

    def _create_light_path_state(self, light_path: LightPath) -> LightPathSnapshot:
        affine_matrix_hash = ""

        light_kube_states: list[KubeState] = []
        for kube in light_path.kubes:
            match kube:
                case IlluminationKube():
                    source = self._illumination_state.get_illumination_by_slot(kube.slot_id)
                    light_kube_states.append(
                        IlluminationKubeState(
                            intensity=source.intensity,
                            wavelength=source.wavelength,
                            slot_id=source.slot,
                            **with_kube_metadata(kube),
                        )
                    )
                    # light does not transform from the source, so we can skip adding to the transformation hash
                case FilterBankKube():
                    filter = self._filter_bank_state.get_active_filter()
                    light_kube_states.append(
                        FilterBankKubeState(
                            **with_kube_metadata(kube),
                            center_wavelength=filter.center_wavelength,
                            bandwidth=filter.bandwidth,
                            transmission=filter.transmission,
                            slot_id=filter.slot,
                        )
                    )
                # filters do not transform the affine matrix
                case DichroicKube():
                    light_kube_states.append(
                        DichroicKubeState(
                            **with_kube_metadata(kube),
                        )
                    )

                case StageKube():
                    light_kube_states.append(
                        StageKubeState(
                            **with_kube_metadata(kube),
                        )
                    )
                    # The stage of course affects the transformation from sample to pixel coordinates, so we add its affine matrix to the hash
                    affine_matrix_hash += str(kube.affine_matrix)
                case ObjectiveTurretKube():
                    objective = self._objective_state.get_active_objective()
                    light_kube_states.append(
                        ObjectiveKubeState(
                            slot_id=objective.slot,
                            **with_kube_metadata(kube),
                        )
                    )
                    # The stage of course affects the transformation from sample to pixel coordinates, so we add its affine matrix to the hash
                    affine_matrix_hash += str(objective.slot)
                case ObjectiveKube():
                    light_kube_states.append(
                        ObjectiveKubeState(
                            slot_id=kube.slot_id,
                            **with_kube_metadata(kube),
                        )
                    )
                    affine_matrix_hash += str(kube.slot_id)
                case FilterKube():
                    filter = self._filter_bank_state.get_active_filter()
                    light_kube_states.append(
                        FilterKubeState(
                            **with_kube_metadata(kube),
                            wavelength=filter.center_wavelength,
                        )
                    )
                    affine_matrix_hash += str(filter.slot)
                case DetectorKube():
                    detector = self._camera_state.get_detector_for_slot(kube.slot_id)
                    light_kube_states.append(
                        DetectorKubeState(
                            gain=detector.current_gain,
                            exposure_time=detector.current_exposure_time,
                            **with_kube_metadata(kube),
                        )
                    )
                    # The stage of course affects the transformation from sample to pixel coordinates, so we add its affine matrix to the hash
                    affine_matrix_hash += str(kube.slot_id)
                case GenericKube():
                    light_kube_states.append(
                        GenericKubeState(
                            **with_kube_metadata(kube),
                        )
                    )

        return LightPathSnapshot(
            kubes=light_kube_states,
            edges=[
                LightEdgeState(
                    source=edge.source,
                    target=edge.target,
                    intensity=43,
                    polarization=None,
                )
                for edge in light_path.edges
                # TODO: we should also add the current state of the edges here, but for now we are just adding dummy values
            ],
        )

    def get_metadata_for_light_path(self, light_path: LightPath) -> Metadata:
        """Get the metadata for a specific light path."""

        """Get the current metadata, including image IDs and affine matrices."""

        # Here we are collecting calibrated states, calibrates states are
        # calibrated ONCE and are not dependent on the current state, BUT are
        # dependent on the light path configuration (i.e. which objective and which camera)

        light_path_state = self._create_light_path_state(light_path)

        try:
            calibrated_light_path = self._calibration_state.get_calibrated_path(
                light_path_state=light_path_state
            )
        except ValueError:
            # Not calibrated (or no stage to calibrate against): the detector's nominal
            # pixel size, through the objective's magnification if there is one.
            calibrated_light_path = self._uncalibrated(light_path, light_path_state)
        camera_matrix = calibrated_light_path.affine_matrix

        # Here we are extracing the actual states that are relevant for metadata,
        # they are dependend on the current state of the microscope,
        stage_matrix = self._stage_state.as_affine_matrix()

        # Combine the camera and stage matrices (assuming matrix multiplication)
        combined_matrix = np.dot(
            np.array(camera_matrix), np.array(stage_matrix)
        )  # This is a placeholder for actual matrix multiplication

        return Metadata(
            affine_matrix=combined_matrix.tolist(),
            fov_height=calibrated_light_path.fov_height,
            fov_width=calibrated_light_path.fov_width,
            light_state=light_path_state,
            acquisition_time=datetime.now().isoformat(),
        )

    def _uncalibrated(
        self, light_path: LightPath, light_path_state: LightPathSnapshot
    ) -> CalibratedLightPath:
        """The nominal scale of a light path no calibration covers."""
        detector = self._camera_state.get_detector_for_slot(light_path.detector)
        magnification = 1.0
        if self._objective_state.mounted_lenses:
            magnification = self._objective_state.get_active_objective().magnification or 1.0
        pixel_um = detector.pixel_size_um / magnification
        return CalibratedLightPath(
            light_path_state_hash=light_path_state.hash,
            affine_matrix=[
                [pixel_um, 0.0, 0.0, 0.0],
                [0.0, pixel_um, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            fov_width=pixel_um * detector.width,
            fov_height=pixel_um * detector.height,
        )

    def get_current_state_for_light_path(self, light_path: LightPath) -> LightPathSnapshot:
        """Get the current state for a specific light path."""
        return self._create_light_path_state(light_path)
