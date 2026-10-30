"""A mikro client for FastAPI mode, configured by hand.

In agent mode arkitekt provides mikro (`mikro_service`, ``main_arkitekt.py``). FastAPI mode has no
server to ask, so where mikro is comes from the environment, like the backend's own host and port,
and the token stays out of the committed settings. Unset, newswitch runs without one.

An action takes it the same way in both modes: as a parameter of type `mikro.Mikro`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arkitekt import App
    from mikro import Mikro


class MikroConfigError(ValueError):
    """The environment names a mikro, but not everything it takes to reach it."""


@dataclass(frozen=True)
class MikroConnection:
    """Where a mikro is, and what to authenticate with."""

    url: str
    """The server, without a path: ``http://localhost:6580``."""
    datalayer_url: str
    """The object store it keeps pixels in, which a client talks to itself."""
    token: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> MikroConnection | None:
        """The mikro the environment names, or None when ``MIKRO_URL`` is unset or empty.

        Raises:
            MikroConfigError: ``MIKRO_URL`` is set, but ``MIKRO_DATALAYER_URL`` or ``MIKRO_TOKEN``
                is not: half a configuration should not look like running without mikro.
        """
        url = environ.get("MIKRO_URL")
        if not url:
            return None
        missing = [name for name in ("MIKRO_DATALAYER_URL", "MIKRO_TOKEN") if not environ.get(name)]
        if missing:
            raise MikroConfigError(f"MIKRO_URL is set, but {' and '.join(missing)} are not")
        return cls(url.rstrip("/"), environ["MIKRO_DATALAYER_URL"], environ["MIKRO_TOKEN"])

    def client(self) -> Mikro:
        """A new client, not yet entered: what the mikro service builds, with a fixed token."""
        from graphql import OperationType
        from mikro import Mikro
        from mikro.datalayer import DataLayer
        from mikro.middleware.upload import UploadMiddleware
        from mikro.rath import MikroRath
        from rath.links.aiohttp import AIOHttpLink
        from rath.links.auth import ComposedAuthLink
        from rath.links.compose import compose
        from rath.links.dictinglink import DictingLink
        from rath.links.file import FileExtraction
        from rath.links.graphql_ws import GraphQLWSLink
        from rath.links.split import SplitLink

        token = self.token

        async def token_loader() -> str:
            return token

        websocket_url = self.url.replace("http", "ws", 1)
        datalayer = DataLayer(endpoint_url=self.datalayer_url)
        return Mikro(
            datalayer=datalayer,
            rath=MikroRath(
                link=compose(
                    FileExtraction(),
                    DictingLink(),
                    ComposedAuthLink(token_loader=token_loader, token_refresher=token_loader),
                    SplitLink(
                        left=AIOHttpLink(endpoint_url=f"{self.url}/graphql"),
                        right=GraphQLWSLink(ws_endpoint_url=f"{websocket_url}/graphql"),
                        split=lambda o: o.node.operation != OperationType.SUBSCRIPTION,
                    ),
                ),
                middlewares=[UploadMiddleware(datalayer=datalayer)],
            ),
        )


def register_mikro(app: App, connection: MikroConnection) -> None:
    """Provide `connection`'s client to the actions of `app`, for as long as the agent runs."""
    from typing import Tuple

    from mikro import Mikro

    from newswitch.settings import Settings

    app.register_context(Mikro)

    async def provide_mikro(app_context: Settings) -> Tuple[Mikro]:
        """Startup: enter the client. It connects with its first call, so a mikro that is down
        does not keep the microscope from starting."""
        client = connection.client()
        await client.__aenter__()
        return (client,)

    async def close_mikro(mikro: Mikro) -> None:
        """Shutdown: leave the client."""
        await mikro.__aexit__(None, None, None)

    # The annotations above are strings here (`from __future__`); the registry reads them.
    provide_mikro.__annotations__ = {"app_context": Settings, "return": Tuple[Mikro]}
    close_mikro.__annotations__ = {"mikro": Mikro, "return": None}
    app.register_startup(provide_mikro)
    app.register_shutdown(close_mikro)
