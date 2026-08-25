"""HTTP routes for account, role and login-audit management.

`/auth/me` and `/auth/me/password` are for the account making the call; everything
else here is admin-only. Layered behind `AuthMiddleware`, which already requires a
valid token for any of these paths - the `require_admin` dependency adds the role
check on top of that.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from newswitch.auth import UserStoreAuthenticator, bearer_token
from newswitch.users import (
    LoginEvent,
    Role,
    User,
    UserAlreadyExistsError,
    UserNotFoundError,
    UserStore,
)

router = APIRouter(prefix="/auth", tags=["Users"])


class UserOut(BaseModel):
    """An account, without its password hash."""

    username: str
    role: Role
    disabled: bool

    @classmethod
    def from_user(cls, user: User) -> "UserOut":
        """Build the wire representation of `user`."""
        return cls(username=user.username, role=user.role, disabled=user.disabled)


class CreateUserRequest(BaseModel):
    """Body of `POST /auth/users`."""

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    role: Role


class UpdateUserRequest(BaseModel):
    """Body of `PATCH /auth/users/{username}`. Both fields optional: send only what changes."""

    role: Role | None = None
    disabled: bool | None = None


class SetPasswordRequest(BaseModel):
    """Body of `POST /auth/users/{username}/password`."""

    password: str = Field(min_length=1)


class ChangeMyPasswordRequest(BaseModel):
    """Body of `POST /auth/me/password`."""

    current_password: str
    new_password: str = Field(min_length=1)


class ChangeMyPasswordResponse(BaseModel):
    """A fresh token, since changing your own password revokes the one used to ask."""

    token: str
    token_type: str = "bearer"


class LoginEventOut(BaseModel):
    """One row of the audit trail."""

    username: str
    event: str
    created_at: str

    @classmethod
    def from_event(cls, event: LoginEvent) -> "LoginEventOut":
        """Build the wire representation of `event`."""
        return cls(username=event.username, event=event.event, created_at=event.created_at)


def get_user_store(request: Request) -> UserStore:
    """The `UserStore` behind the app's authenticator.

    User management only makes sense against the real account store - apps running
    with `CredentialAuthenticator`/`AllowAllAuthenticator` (tests, the legacy single
    account) have no accounts to manage.
    """
    authenticator = request.app.state.authenticator
    if not isinstance(authenticator, UserStoreAuthenticator):
        raise HTTPException(status_code=404, detail="User management is not available")
    return authenticator.store


def get_current_user(request: Request, store: UserStore = Depends(get_user_store)) -> User:
    """The account the caller's bearer token belongs to."""
    token = bearer_token(request.headers.get("authorization"))
    user = store.resolve_session(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """The caller must hold the admin role."""
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)) -> UserOut:
    """The caller's own account - lets the frontend show who is logged in and gate admin UI."""
    return UserOut.from_user(user)


@router.post("/me/password")
async def change_my_password(
    body: ChangeMyPasswordRequest,
    user: User = Depends(get_current_user),
    store: UserStore = Depends(get_user_store),
) -> ChangeMyPasswordResponse:
    """Self-service password change.

    Revokes every session for the account, including the one used to make this call
    (see `UserStore.change_password`) - so a fresh token is minted and returned rather
    than leaving the caller logged out by its own request.
    """
    if store.verify_password(user.username, body.current_password) is None:
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    store.change_password(user.username, body.new_password)
    token = store.create_session(user.username)
    return ChangeMyPasswordResponse(token=token)


@router.get("/users")
async def list_users(
    admin: User = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> list[UserOut]:
    """All accounts. Admin only."""
    return [UserOut.from_user(user) for user in store.list_users()]


@router.post("/users", status_code=201)
async def create_user(
    body: CreateUserRequest,
    admin: User = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> UserOut:
    """Create a new account. Admin only."""
    try:
        user = store.create_user(body.username, body.password, body.role)
    except UserAlreadyExistsError as error:
        raise HTTPException(status_code=409, detail="Username already exists") from error
    return UserOut.from_user(user)


@router.patch("/users/{username}")
async def update_user(
    username: str,
    body: UpdateUserRequest,
    admin: User = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> UserOut:
    """Change the role and/or enabled state of an account. Admin only.

    Refuses an edit that would leave zero enabled admins able to log in - the one
    lockout the CLI recovery tool cannot fix without wiping every account.
    """
    target = store.get_user(username)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    demoting = target.role == Role.ADMIN and body.role is not None and body.role != Role.ADMIN
    disabling = target.role == Role.ADMIN and not target.disabled and body.disabled is True
    if (demoting or disabling) and store.count_enabled_admins() <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last admin")

    if body.role is not None:
        store.set_role(username, body.role)
    if body.disabled is not None:
        store.set_disabled(username, body.disabled)
    return UserOut.from_user(store.get_user(username))


@router.post("/users/{username}/password")
async def reset_user_password(
    username: str,
    body: SetPasswordRequest,
    admin: User = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> dict[str, str]:
    """Reset another account's password. Admin only. Revokes that account's sessions."""
    try:
        store.change_password(username, body.password)
    except UserNotFoundError as error:
        raise HTTPException(status_code=404, detail="User not found") from error
    return {"detail": "Password reset"}


@router.delete("/users/{username}", status_code=204)
async def delete_user(
    username: str,
    admin: User = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> None:
    """Delete an account. Admin only. Refuses to delete yourself or the last admin."""
    if username == admin.username:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    target = store.get_user(username)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role == Role.ADMIN and store.count_enabled_admins() <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last admin")

    store.delete_user(username)


@router.get("/audit")
async def list_audit_log(
    admin: User = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
    limit: int = 200,
) -> list[LoginEventOut]:
    """The most recent login events, newest first. Admin only."""
    return [LoginEventOut.from_event(event) for event in store.list_login_events(limit=limit)]
