"""The store of a server that has none."""

from typing import Any, Mapping

from newswitch.models.acquisition import AcquiredDataset
from newswitch.protocols.dataset_store import AcquiredPosition


class NoDatasetStore:
    """Refuses an acquisition before it starts, and says what is missing."""

    MESSAGE = (
        "An acquisition is stored in mikro, and this server has none: "
        "set MIKRO_URL, MIKRO_DATALAYER_URL and MIKRO_TOKEN (just dev-mikro)"
    )

    def check(self) -> None:
        """Always refuses."""
        raise RuntimeError(self.MESSAGE)

    def state(self) -> Mapping[str, Any]:
        """Never reached: `check` refuses first."""
        raise RuntimeError(self.MESSAGE)

    def publish(self, acquired: AcquiredPosition) -> AcquiredDataset:
        """Never reached: `check` refuses first."""
        raise RuntimeError(self.MESSAGE)
