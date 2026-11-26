"""The detector state: what the microscope has that delivers images."""

from dataclasses import dataclass, field

from newswitch.models.devices import Detector


@dataclass
class DetectorState:
    """The detectors, and whether they stream."""

    is_acquiring: bool = False
    detectors: list[Detector] = field(default_factory=lambda: [])
    names: list[str] = field(default_factory=list)
    """What the detectors are called: what a detector's action can be asked of
    (``withStateChoices("self.detector.names")``)."""

    def get_active_detectors(self) -> list[Detector]:
        """The detectors that are on."""
        return [detector for detector in self.detectors if detector.is_active]

    def get(self, name: str) -> Detector:
        """The detector called `name`.

        Raises:
            ValueError: There is none.
        """
        for detector in self.detectors:
            if detector.name == name:
                return detector
        known = [detector.name for detector in self.detectors]
        raise ValueError(f"No detector {name!r}: there are {known}")
