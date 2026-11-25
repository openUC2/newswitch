"""A mikro for FastAPI mode: acquisitions stored through its client, as long as the agent runs.

Included only when a mikro is configured (`connection`): importing this needs the extra ``mikro``.

The client itself is no context: `Mikro` is an arkitekt client, which a run provides (in agent
mode, ``app.py``), not a startup hook. Here the hook keeps it and hands out what is stored through
it, the `DatasetStore`.
"""

from collections.abc import AsyncIterator

from arkitekt import App

from newswitch.microscope.run import Run
from newswitch.protocols.dataset_store import DatasetStore
from newswitch.infra.mikro.store import MikroDatasetStore

app = App("newswitch", app_context=Run)
app.register_context(DatasetStore)


@app.lifecycle
async def provide_mikro(run: Run) -> AsyncIterator[DatasetStore]:
    """Enter the client, and leave it on shutdown. It connects with its first call, so a mikro that
    is down does not keep the microscope from starting."""
    assert run.mikro is not None
    client = run.mikro.client()
    async with client:
        yield MikroDatasetStore(client, run.instrument, run.microscope)
