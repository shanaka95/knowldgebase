import logging
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import EmailStr
from sqlmodel import col, func, select

from app import crud
from app.api.deps import (
    AuthDep,
    CurrentUser,
    SessionDep,
    SessionUser,
    get_current_active_superuser,
)
from app.api.routes.login import send_verification_email
from app.api.serializers import user_ref
from app.core import authcodes
from app.core.config import settings
from app.core.security import (
    create_access_token,
    get_password_hash,
    verify_password,
)
from app.models import (
    AuthCodePurpose,
    Message,
    TokenMessage,
    UpdatePassword,
    User,
    UserCreate,
    UserLookup,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from app.services.email import (
    Email,
    EmailError,
    get_email_sender,
    password_changed_email,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])

# The same answer whether or not the address was already registered.
SIGNUP_REPLY = (
    "Check your inbox. If that address can be registered, a confirmation "
    "link is on its way."
)


async def _deliver_quietly(message: Email) -> None:
    """Send a notification whose failure must not fail the request.

    The password really has changed by this point; a mail outage should not
    be reported to the caller as though it had not.
    """
    try:
        await get_email_sender().send(message)
    except EmailError as exc:
        logger.error("could not send %r: %s", message.subject, exc)


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UsersPublic,
)
def read_users(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    """
    Retrieve users.
    """

    count_statement = select(func.count()).select_from(User)
    count = session.exec(count_statement).one()

    statement = (
        select(User).order_by(col(User.created_at).desc()).offset(skip).limit(limit)
    )
    users = session.exec(statement).all()

    users_public = [UserPublic.model_validate(user) for user in users]
    return UsersPublic(data=users_public, count=count)


@router.post(
    "/", dependencies=[Depends(get_current_active_superuser)], response_model=UserPublic
)
def create_user(*, session: SessionDep, user_in: UserCreate) -> Any:
    """
    Create new user.
    """
    user = crud.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )

    user = crud.create_user(session=session, user_create=user_in)
    return user


@router.patch("/me", response_model=UserPublic)
async def update_user_me(
    *, session: SessionDep, user_in: UserUpdateMe, current_user: SessionUser
) -> Any:
    """Update own user.

    Moving to a different address leaves that address **unconfirmed** until a
    link sent to it is answered, exactly as at sign-up. Being signed in proves
    control of the account, never of an address somebody typed into it - and
    the address is the account's identity everywhere else: sharing looks
    accounts up by it, so an address accepted on an authenticated PATCH alone
    would let anyone claim somebody else's and be handed their pages.
    """
    moved = bool(user_in.email) and user_in.email != current_user.email
    if user_in.email:
        existing_user = crud.get_user_by_email(session=session, email=user_in.email)
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
    user_data = user_in.model_dump(exclude_unset=True)
    current_user.sqlmodel_update(user_data)
    if moved:
        current_user.email_verified_at = None
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    if moved and (
        authcodes.recent_send_count(
            session, current_user.id, AuthCodePurpose.verify_email
        )
        < settings.AUTH_CODE_MAX_SENDS
    ):
        # Capped like every other send: the address is whatever the caller just
        # typed, so without this, changing it in a loop points the product's own
        # mail at somebody else's inbox.
        await send_verification_email(session, current_user)
    return current_user


@router.patch("/me/password", response_model=TokenMessage)
async def update_password_me(
    *, session: SessionDep, body: UpdatePassword, current_user: SessionUser
) -> Any:
    """
    Update own password.
    """
    verified, _ = verify_password(body.current_password, current_user.hashed_password)
    if not verified:
        raise HTTPException(status_code=400, detail="Incorrect password")
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=400, detail="New password cannot be the same as the current one"
        )
    current_user.hashed_password = get_password_hash(body.new_password)
    # Changing a password is also how someone reacts to thinking it leaked, so
    # it has to end the sessions that password could have opened. This token is
    # reissued below rather than leaving the caller signed out of their own
    # browser as a reward for good security hygiene.
    current_user.session_epoch += 1
    session.add(current_user)
    session.commit()
    session.refresh(current_user)

    await _deliver_quietly(password_changed_email(current_user.email))
    return TokenMessage(
        message="Password updated. Every other session has been signed out.",
        access_token=create_access_token(
            current_user.id,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            session_epoch=current_user.session_epoch,
        ),
    )


@router.get("/lookup", response_model=UserLookup)
def lookup_user(
    session: SessionDep,
    auth: AuthDep,  # noqa: ARG001 - signed in, so this cannot be probed anonymously
    email: EmailStr,
) -> Any:
    """Does this exact address have a confirmed account here?

    Confirmed, because that is what sharing will do with the answer: an address
    whose account never answered a confirmation gets an invitation, not access,
    and a dialog that promised otherwise would be lying about where the page is
    about to go.

    Used by the share dialog to show who a page is about to go to. **Exact
    matches only, never prefixes**: confirming one address somebody already
    typed is what sharing needs, while a prefix search would turn this into a
    way to read the user list. Signed in, for the same reason.

    An address with no account is not an error - it can still be invited.
    """
    address = email.strip().lower()
    user = crud.get_confirmed_user_by_email(session=session, email=address)
    return UserLookup(
        email=address,
        exists=user is not None,
        user=user_ref(user) if user is not None else None,
    )


@router.get("/me", response_model=UserPublic)
def read_user_me(current_user: CurrentUser) -> Any:
    """
    Get current user.
    """
    return current_user


@router.delete("/me", response_model=Message)
def delete_user_me(session: SessionDep, current_user: SessionUser) -> Any:
    """
    Delete own user.
    """
    if current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    session.delete(current_user)
    session.commit()
    return Message(message="User deleted successfully")


@router.post("/signup", response_model=Message)
async def register_user(session: SessionDep, user_in: UserRegister) -> Any:
    """Create an account and email a confirmation link.

    The account exists immediately but cannot sign in until the address is
    confirmed, so registering with someone else's address gains nothing.

    The reply is the same whether or not the address was already taken. An
    unauthenticated endpoint that distinguishes the two is a way to test whether
    a given person has an account here, and the person who really owns the
    address learns the truth from their inbox either way.
    """
    existing = crud.get_user_by_email(session=session, email=user_in.email)
    if existing is not None:
        if existing.email_verified_at is None and existing.is_active:
            # Very likely the same person registering again after losing the
            # first message, so send another rather than stranding them.
            await send_verification_email(session, existing)
        return Message(message=SIGNUP_REPLY)

    user_create = UserCreate.model_validate(user_in)
    user = crud.create_user(session=session, user_create=user_create)
    await send_verification_email(session, user)
    return Message(message=SIGNUP_REPLY)


@router.get("/{user_id}", response_model=UserPublic)
def read_user_by_id(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """
    Get a specific user by id.
    """
    user = session.get(User, user_id)
    if user == current_user:
        return user
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges",
        )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
)
def update_user(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    user_in: UserUpdate,
) -> Any:
    """
    Update a user.
    """

    db_user = session.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )
    if user_in.email:
        existing_user = crud.get_user_by_email(session=session, email=user_in.email)
        if existing_user and existing_user.id != user_id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )

    db_user = crud.update_user(session=session, db_user=db_user, user_in=user_in)
    return db_user


@router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
def delete_user(
    session: SessionDep, current_user: CurrentUser, user_id: uuid.UUID
) -> Message:
    """
    Delete a user.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user == current_user:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    session.delete(user)
    session.commit()
    return Message(message="User deleted successfully")
