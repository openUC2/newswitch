"""A mikro client for FastAPI mode, configured by hand.

In agent mode arkitekt provides mikro (the client `Mikro`, ``app.py``). FastAPI mode has no
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
