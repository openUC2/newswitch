"""A mikro for FastAPI mode: its client, and acquisitions stored through it, as long as the agent runs.

Merged only when a mikro is configured (`mikro_connection`): importing this needs the extra ``mikro``.
"""

from collections.abc import AsyncIterator
from typing import Tuple

from arkitekt import App
from mikro import Mikro

from newswitch.microscope.run import Run
from newswitch.protocols.dataset_store import DatasetStore
from newswitch.services.mikro_store import MikroDatasetStore

app = App("newswitch", app_context=Run)
app.register_context(Mikro)
app.register_context(DatasetStore)


@app.lifecycle
async def provide_mikro(run: Run) -> AsyncIterator[Tuple[Mikro, DatasetStore]]:
    """Enter the client, and leave it on shutdown. It connects with its first call, so a mikro that
    is down does not keep the microscope from starting."""
    assert run.mikro is not None
    client = run.mikro.client()
    async with client:
        yield client, MikroDatasetStore(client, run.instrument, run.microscope)
