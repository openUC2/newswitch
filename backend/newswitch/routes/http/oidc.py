"""Optional Keycloak sign-in for existing local Newswitch accounts."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from newswitch.routes.http.users import get_user_store
from newswitch.users import UserStore

router = APIRouter(prefix="/auth/oidc", tags=["Authentication"])
logger = logging.getLogger(__name__)


def _valid_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        bool(parsed.hostname)
        and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
        and (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"})
        )
    )


@dataclass(frozen=True)
class OIDCConfig:
    """Trusted Keycloak realm, client and exact browser callback URL."""

    issuer: str
    client_id: str
    redirect_uri: str

    @classmethod
    def from_env(cls) -> OIDCConfig | None:
        """Enable OIDC when both URLs are configured and valid."""
        issuer = os.getenv("NEWSWITCH_OIDC_ISSUER", "").strip().rstrip("/")
        redirect_uri = os.getenv("NEWSWITCH_OIDC_REDIRECT_URI", "").strip()
        client_id = os.getenv("NEWSWITCH_OIDC_CLIENT_ID", "newswitch").strip()
        if not issuer and not redirect_uri:
            return None
        try:
            valid = _valid_url(issuer) and _valid_url(redirect_uri) and bool(client_id)
        except ValueError:
            valid = False
        if not valid:
            logger.warning("Invalid Newswitch OIDC configuration; local sign-in is available")
            return None
        return cls(issuer, client_id, redirect_uri)

    @property
    def endpoints(self) -> str:
        """Base URL for this Keycloak realm's OIDC endpoints."""
        return f"{self.issuer}/protocol/openid-connect"


class LoginStart(BaseModel):
    """Values for the browser tab that is starting sign-in."""

    authorization_url: str
    state: str
    proof: str


class LoginCompletion(BaseModel):
    """Authorization code and the initiating tab's transaction credentials."""

    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=43, max_length=43)
    proof: str = Field(min_length=43, max_length=43)


def _config(request: Request) -> OIDCConfig:
    config = request.app.state.oidc_config
    if config is None:
        raise HTTPException(404, "Keycloak sign-in is disabled")
    return config


@router.get("/enabled")
async def oidc_enabled(request: Request, response: Response) -> dict[str, bool | str]:
    """Describe the configured provider without checking the network."""
    config: OIDCConfig | None = request.app.state.oidc_config
    response.headers["Cache-Control"] = "no-store"
    return {"enabled": True, "issuer": config.issuer} if config else {"enabled": False}


async def _provider_is_reachable(config: OIDCConfig) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            discovery = await client.get(f"{config.issuer}/.well-known/openid-configuration")
            discovery.raise_for_status()
            return discovery.json()["issuer"] == config.issuer
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return False


@router.get("/availability")
async def oidc_availability(request: Request, response: Response) -> dict[str, bool]:
    """Check whether this microscope backend can reach its configured provider."""
    response.headers["Cache-Control"] = "no-store"
    return {"available": await _provider_is_reachable(_config(request))}


@router.post("/start")
async def start_oidc_login(
    request: Request, response: Response, store: UserStore = Depends(get_user_store)
) -> LoginStart:
    """Prepare a one-time Authorization Code flow using PKCE."""
    config = _config(request)
    if not await _provider_is_reachable(config):
        raise HTTPException(503, "Keycloak is unavailable")

    state, proof, verifier, nonce = (secrets.token_urlsafe(32) for _ in range(4))
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    store.save_oidc_login(state, proof, verifier, nonce)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": config.client_id,
            "scope": "openid",
            "redirect_uri": config.redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "nonce": nonce,
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return LoginStart(
        authorization_url=f"{config.endpoints}/auth?{query}", state=state, proof=proof
    )


async def _redeem_code(config: OIDCConfig, code: str, verifier: str, nonce: str) -> str:
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.post(
            f"{config.endpoints}/token",
            data={
                "grant_type": "authorization_code",
                "client_id": config.client_id,
                "redirect_uri": config.redirect_uri,
                "code": code,
                "code_verifier": verifier,
            },
        )
        if response.status_code in (400, 401):
            raise HTTPException(401, "Keycloak rejected the authorization code")
        response.raise_for_status()
        id_token = response.json()["id_token"]

        keys = await client.get(f"{config.endpoints}/certs")
        keys.raise_for_status()

    kid = jwt.get_unverified_header(id_token).get("kid")
    if not isinstance(kid, str) or not kid:
        raise ValueError("Missing key ID")
    key = jwt.PyJWKSet.from_dict(keys.json())[kid]
    claims = jwt.decode(
        id_token,
        key,
        algorithms=["RS256"],
        audience=config.client_id,
        issuer=config.issuer,
        options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
        leeway=10,
    )
    azp = claims.get("azp")
    # With multiple audiences the client must be the authorized party.
    multiple_audiences = isinstance(claims["aud"], list) and len(claims["aud"]) > 1
    if (
        claims["nonce"] != nonce
        or not claims["sub"]
        or ((azp is not None or multiple_audiences) and azp != config.client_id)
    ):
        raise ValueError("Unexpected OIDC claims")
    return claims["sub"]


@router.post("/complete")
async def complete_oidc_login(
    body: LoginCompletion,
    request: Request,
    response: Response,
    store: UserStore = Depends(get_user_store),
) -> dict[str, str]:
    """Redeem the code, verify the identity, then issue the usual Newswitch session."""
    config = _config(request)
    attempt = store.consume_oidc_login(body.state, body.proof)
    if attempt is None:
        raise HTTPException(401, "Keycloak sign-in has expired or is invalid")

    try:
        subject = await _redeem_code(config, body.code, *attempt)
    except httpx.HTTPError as error:
        raise HTTPException(503, "Keycloak is unavailable") from error
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as error:
        raise HTTPException(401, "Invalid Keycloak identity") from error

    token = store.create_oidc_session(config.issuer, subject)
    if token is None:
        raise HTTPException(403, "Keycloak identity has no active account on this instrument")
    response.headers["Cache-Control"] = "no-store"
    return {"token": token, "token_type": "bearer"}
