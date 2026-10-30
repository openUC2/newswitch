"""LightPathManager for calculating and managing the current light path through the microscope based on the current configuration of objectives, filters, illumination, and detectors."""

from __future__ import annotations

import math

from kaffine import Affine

from newswitch.models.light_path import (
    DetectorKube,
    DichroicKube,
    FilterBankKube,
    IlluminationKube,
    LightEdge,
    LightPath,
    ObjectiveTurretKube,
    StageKube,
)
from newswitch.states.detector import CameraState
from newswitch.states.filter_bank import FilterBankState
from newswitch.states.illumination import IlluminationState
from newswitch.states.light_path import LightPathState
from newswitch.states.objective import ObjectiveState

# Create a transform: Move 10 units X, then Rotate 45 deg Z
# (Note: Order is intuitive "Operation 1 -> Operation 2")


def create_affine_matrix(
    position_x: float, position_y: float, position_z: float
) -> list[list[float]]:
    """Helper function to create a simple affine transformation matrix based on the provided position."""
    # This is a placeholder implementation. In a real implementation, this would involve more complex logic to create an affine transformation matrix based on the microscope's optical configuration.
    return [
        [1.0, 0.0, 0.0, position_x],
        [0.0, 1.0, 0.0, position_y],
        [0.0, 0.0, 1.0, position_z],
        [0.0, 0.0, 0.0, 1.0],
    ]


class LightPathManager:
    """The light path from each light source to each detector, through the parts the microscope has."""

    def __init__(
        self,
        light_path_state: LightPathState,
        illumination_state: IlluminationState,
        filter_bank_state: FilterBankState,
        objective_state: ObjectiveState,
        camera_state: CameraState,
        has_stage: bool = True,
    ) -> None:
        """Initialize the LightPathManager with the states of the microscope's parts.

        A part the microscope lacks has an empty state (no light sources, objectives or
        filters) and is left out of the light paths; `has_stage` says whether there is a
        stage to carry the sample.
        """
        self.state = light_path_state
        self.has_stage = has_stage
        self.objective_state = objective_state
        self.filter_bank_state = filter_bank_state
        self.camera_state = camera_state
        self.illumination_state = illumination_state

    def calculate_possible_light_paths(self) -> list[LightPath]:
        """The light path to each detector, through the parts the microscope has.

        Light sources feed a dichroic, then the light passes the stage (the sample), the
        objective turret and the filter bank on to the detector. Each of these is in the
        path only when the microscope has it.
        """
        possible_light_paths: list[LightPath] = []
        illuminations = self.illumination_state.illuminations
        for detector in self.camera_state.detectors:
            kubes: list = []
            edges: list[LightEdge] = []
            chain: list[str] = []

            if illuminations:
                dichroic_kube = DichroicKube(
                    kube_id="dichroic_0",
                    slot_id=0,  # a dichroic has no physical slot
                    affine_matrix=Affine.new().translate_z(120).to_four_by_four_list(),
                )
                arc_length = 360 / len(illuminations)
                radial_distance = 40
                for il, illumination in enumerate(illuminations):
                    x_position = radial_distance * math.cos(math.radians(il * arc_length))
                    y_position = radial_distance * math.sin(math.radians(il * arc_length))
                    kubes.append(
                        IlluminationKube(
                            kube_id=f"illumination_{illumination.slot}",
                            slot_id=illumination.slot,
                            affine_matrix=Affine.new()
                            .translate_z(180)
                            .translate_x(x_position)
                            .translate_y(y_position)
                            .to_four_by_four_list(),
                        )
                    )
                    edges.append(
                        LightEdge(
                            source=f"illumination_{illumination.slot}",
                            target=dichroic_kube.kube_id,
                            intensity=1.0,
                        )
                    )
                kubes.append(dichroic_kube)
                chain.append(dichroic_kube.kube_id)

            if self.has_stage:
                stage_kube = StageKube(
                    kube_id="stage_0",
                    slot_id=0,
                    affine_matrix=Affine.new().translate_z(0).to_four_by_four_list(),
                )
                kubes.append(stage_kube)
                chain.append(stage_kube.kube_id)

            if self.objective_state.mounted_lenses:
                turret_kube = ObjectiveTurretKube(
                    kube_id="objectiveturret_0",
                    affine_matrix=Affine.new()
                    .rotate_x(180)
                    .translate_z(-70)
                    .to_four_by_four_list(),
                )
                kubes.append(turret_kube)
                chain.append(turret_kube.kube_id)

            if self.filter_bank_state.filters:
                filter_bank_kube = FilterBankKube(
                    kube_id="filterbank_0",
                    affine_matrix=Affine.new().translate_z(-150).to_four_by_four_list(),
                )
                kubes.append(filter_bank_kube)
                chain.append(filter_bank_kube.kube_id)

            detector_kube = DetectorKube(
                kube_id=f"detector_{detector.slot}",
                slot_id=detector.slot,
                affine_matrix=Affine.new().rotate_x(180).translate_z(-240).to_four_by_four_list(),
            )
            kubes.append(detector_kube)
            chain.append(detector_kube.kube_id)

            edges.extend(
                LightEdge(source=source, target=target, intensity=1.0)
                for source, target in zip(chain, chain[1:])
            )
            possible_light_paths.append(LightPath(kubes=kubes, edges=edges, detector=detector.slot))
        self.state.light_paths = possible_light_paths
        return possible_light_paths

    def get_light_path_for_detector(self, detector_slot: int) -> LightPath:
        """Get the current light path based on the objective state."""
        # Placeholder logic to determine the current light path based on the objective state
        # In a real implementation, this would involve more complex logic based on the microscope's optical configuration

        for light_path in self.state.light_paths:
            if light_path.detector == detector_slot:
                self.state.current_light_path = light_path
                return light_path

        raise ValueError(
            f"No light path found for detector slot {detector_slot}. This is likely because it is not a valid combination or because calculate_possible_light_paths() has not been called to populate the light paths."
        )
