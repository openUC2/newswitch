"""A mikro for FastAPI mode: its client, for as long as the agent runs.

Merged only when a mikro is configured (`mikro_connection`): importing this needs the extra ``mikro``.
"""

from collections.abc import AsyncIterator

from arkitekt import App
from mikro import Mikro

from newswitch.microscope.run import Run

app = App("newswitch", app_context=Run)
app.register_context(Mikro)


@app.lifecycle
async def provide_mikro(run: Run) -> AsyncIterator[Mikro]:
    """Enter the client, and leave it on shutdown. It connects with its first call, so a mikro that
    is down does not keep the microscope from starting."""
    assert run.mikro is not None
    client = run.mikro.client()
    async with client:
        yield client
