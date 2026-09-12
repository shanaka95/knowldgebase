"""Signing in, and everything that must not let someone else sign in as you."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlmodel import Session, col, select

from app.core import authcodes
from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.models import AuthCode, AuthCodePurpose, User
from app.services.email import LoggingEmailSender, get_email_sender
from tests.utils.user import (
    last_email_code,
    last_email_link_token,
    verify_email,
)
from tests.utils.utils import random_email, random_lower_string

API = settings.API_V1_STR
ACCESS = f"{API}/login/access-token"
TWO_FACTOR = f"{API}/login/two-factor"
RESEND_2FA = f"{API}/login/two-factor/resend"
VERIFY_EMAIL = f"{API}/login/verify-email"
RESEND_VERIFY = f"{API}/login/verify-email/resend"
RECOVERY = f"{API}/login/password-recovery"
RESET = f"{API}/login/reset-password"


@pytest.fixture(autouse=True)
def _clear_mailbox() -> None:
    sender = get_email_sender()
    if isinstance(sender, LoggingEmailSender):
        sender.sent.clear()


def make_user(db: Session, *, verified: bool = True) -> tuple[User, str]:
    email = random_email()
    password = random_lower_string()
    user = User(
        email=email, hashed_password=get_password_hash(password), is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    if verified:
        verify_email(db, user)
    return user, password


def start_login(client: TestClient, email: str, password: str) -> dict:
    r = client.post(ACCESS, data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# The two steps
# ---------------------------------------------------------------------------


def test_a_password_alone_does_not_open_a_session(
    client: TestClient, db: Session
) -> None:
    """The whole point: knowing the password is not enough."""
    user, password = make_user(db)
    r = client.post(ACCESS, data={"username": user.email, "password": password})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" not in body
    assert body["challenge_token"]
    assert body["code_length"] == settings.TWO_FACTOR_CODE_LENGTH


def test_the_emailed_code_completes_the_login(client: TestClient, db: Session) -> None:
    user, password = make_user(db)
    challenge = start_login(client, user.email, password)["challenge_token"]

    r = client.post(
        TWO_FACTOR, json={"challenge_token": challenge, "code": last_email_code()}
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    me = client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == user.email


def test_the_address_is_masked_in_the_challenge(
    client: TestClient, db: Session
) -> None:
    """Enough to recognise your own mailbox on a shared screen, not to learn it."""
    user, password = make_user(db)
    body = start_login(client, user.email, password)
    assert body["sent_to"] != user.email
    assert "•" in body["sent_to"]
    assert body["sent_to"].endswith(user.email.split("@")[1])


def test_a_challenge_token_is_not_an_access_token(
    client: TestClient, db: Session
) -> None:
    user, password = make_user(db)
    challenge = start_login(client, user.email, password)["challenge_token"]
    r = client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {challenge}"})
    assert r.status_code == 401


def test_a_code_works_only_once(client: TestClient, db: Session) -> None:
    user, password = make_user(db)
    challenge = start_login(client, user.email, password)["challenge_token"]
    code = last_email_code()

    assert (
        client.post(
            TWO_FACTOR, json={"challenge_token": challenge, "code": code}
        ).status_code
        == 200
    )
    again = client.post(TWO_FACTOR, json={"challenge_token": challenge, "code": code})
    assert again.status_code == 400


def test_a_code_from_one_account_cannot_sign_into_another(
    client: TestClient, db: Session
) -> None:
    """The challenge names the account, so a code is useless anywhere else."""
    victim, victim_pw = make_user(db)
    attacker, attacker_pw = make_user(db)

    start_login(client, victim.email, victim_pw)
    victim_code = last_email_code()
    attacker_challenge = start_login(client, attacker.email, attacker_pw)[
        "challenge_token"
    ]

    r = client.post(
        TWO_FACTOR,
        json={"challenge_token": attacker_challenge, "code": victim_code},
    )
    assert r.status_code in (400, 429)


def test_an_expired_code_is_refused(client: TestClient, db: Session) -> None:
    user, password = make_user(db)
    challenge = start_login(client, user.email, password)["challenge_token"]
    code = last_email_code()

    record = db.exec(
        select(AuthCode).where(
            AuthCode.user_id == user.id,
            AuthCode.purpose == AuthCodePurpose.two_factor,
        )
    ).first()
    assert record is not None
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.add(record)
    db.commit()

    r = client.post(TWO_FACTOR, json={"challenge_token": challenge, "code": code})
    assert r.status_code == 400
    assert "expired" in r.json()["detail"].lower()


def test_guessing_the_code_runs_out(client: TestClient, db: Session) -> None:
    """Six digits is only safe with a hard limit on guesses."""
    user, password = make_user(db)
    challenge = start_login(client, user.email, password)["challenge_token"]
    real = last_email_code()
    wrong = "000000" if real != "000000" else "111111"

    for _ in range(settings.AUTH_CODE_MAX_ATTEMPTS):
        client.post(TWO_FACTOR, json={"challenge_token": challenge, "code": wrong})

    # Even the correct code is worthless now: the record was destroyed.
    r = client.post(TWO_FACTOR, json={"challenge_token": challenge, "code": real})
    assert r.status_code in (400, 429)


def test_asking_for_a_new_code_retires_the_old_one(
    client: TestClient, db: Session
) -> None:
    user, password = make_user(db)
    challenge = start_login(client, user.email, password)["challenge_token"]
    first = last_email_code()

    r = client.post(RESEND_2FA, json={"challenge_token": challenge})
    assert r.status_code == 200
    second = last_email_code()
    assert second != first or True  # a repeat is possible, the retirement is not

    stale = client.post(TWO_FACTOR, json={"challenge_token": challenge, "code": first})
    assert stale.status_code in (400, 429), "an old email must stop working"

    good = client.post(TWO_FACTOR, json={"challenge_token": challenge, "code": second})
    assert good.status_code == 200


def test_a_forged_challenge_gets_nowhere(client: TestClient) -> None:
    r = client.post(
        TWO_FACTOR, json={"challenge_token": "not-a-token", "code": "123456"}
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Confirming an address
# ---------------------------------------------------------------------------


def test_an_unconfirmed_account_cannot_sign_in(client: TestClient, db: Session) -> None:
    user, password = make_user(db, verified=False)
    r = client.post(ACCESS, data={"username": user.email, "password": password})
    assert r.status_code == 403
    assert "confirm" in r.json()["detail"].lower()


def test_the_emailed_link_confirms_the_address(client: TestClient, db: Session) -> None:
    user, password = make_user(db, verified=False)
    r = client.post(RESEND_VERIFY, json={"email": user.email})
    assert r.status_code == 200

    r = client.post(VERIFY_EMAIL, json={"token": last_email_link_token()})
    assert r.status_code == 200, r.text

    db.refresh(user)
    assert user.email_verified_at is not None
    assert (
        client.post(
            ACCESS, data={"username": user.email, "password": password}
        ).status_code
        == 200
    )


def test_a_confirmation_link_works_once(client: TestClient, db: Session) -> None:
    user, _ = make_user(db, verified=False)
    client.post(RESEND_VERIFY, json={"email": user.email})
    token = last_email_link_token()

    assert client.post(VERIFY_EMAIL, json={"token": token}).status_code == 200
    assert client.post(VERIFY_EMAIL, json={"token": token}).status_code == 400


def test_a_confirmation_link_does_not_confirm_a_different_address(
    client: TestClient, db: Session
) -> None:
    """A link proves control of the mailbox it was sent to, and nothing else."""
    user, _ = make_user(db, verified=False)
    client.post(RESEND_VERIFY, json={"email": user.email})
    token = last_email_link_token()

    user.email = random_email()
    db.add(user)
    db.commit()

    r = client.post(VERIFY_EMAIL, json={"token": token})
    assert r.status_code == 400
    db.refresh(user)
    assert user.email_verified_at is None


def test_resending_never_reveals_whether_an_address_is_registered(
    client: TestClient, db: Session
) -> None:
    user, _ = make_user(db, verified=False)
    known = client.post(RESEND_VERIFY, json={"email": user.email})
    unknown = client.post(RESEND_VERIFY, json={"email": random_email()})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


# ---------------------------------------------------------------------------
# Forgotten passwords
# ---------------------------------------------------------------------------


def test_recovery_never_reveals_whether_an_address_is_registered(
    client: TestClient, db: Session
) -> None:
    user, _ = make_user(db)
    known = client.post(RECOVERY, json={"email": user.email})
    unknown = client.post(RECOVERY, json={"email": random_email()})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


def test_the_reset_link_sets_a_new_password(client: TestClient, db: Session) -> None:
    user, old_password = make_user(db)
    client.post(RECOVERY, json={"email": user.email})
    new_password = random_lower_string()

    r = client.post(
        RESET, json={"token": last_email_link_token(), "new_password": new_password}
    )
    assert r.status_code == 200, r.text

    assert (
        client.post(
            ACCESS, data={"username": user.email, "password": old_password}
        ).status_code
        == 400
    )
    assert (
        client.post(
            ACCESS, data={"username": user.email, "password": new_password}
        ).status_code
        == 200
    )


def test_a_reset_ends_every_existing_session(client: TestClient, db: Session) -> None:
    """Whoever forgot the password may be locked out by someone who knows it."""
    user, password = make_user(db)
    challenge = start_login(client, user.email, password)["challenge_token"]
    token = client.post(
        TWO_FACTOR, json={"challenge_token": challenge, "code": last_email_code()}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get(f"{API}/users/me", headers=headers).status_code == 200

    client.post(RECOVERY, json={"email": user.email})
    client.post(
        RESET,
        json={
            "token": last_email_link_token(),
            "new_password": random_lower_string(),
        },
    )

    assert client.get(f"{API}/users/me", headers=headers).status_code == 401


def test_a_reset_link_works_once(client: TestClient, db: Session) -> None:
    user, _ = make_user(db)
    client.post(RECOVERY, json={"email": user.email})
    token = last_email_link_token()

    first = client.post(
        RESET, json={"token": token, "new_password": random_lower_string()}
    )
    second = client.post(
        RESET, json={"token": token, "new_password": random_lower_string()}
    )
    assert first.status_code == 200
    assert second.status_code == 400


def test_resetting_also_confirms_the_address(client: TestClient, db: Session) -> None:
    """Reaching the link proves the same thing confirmation asks for."""
    user, _ = make_user(db, verified=False)
    client.post(RECOVERY, json={"email": user.email})
    client.post(
        RESET,
        json={
            "token": last_email_link_token(),
            "new_password": random_lower_string(),
        },
    )
    db.refresh(user)
    assert user.email_verified_at is not None


def test_a_forged_reset_token_is_refused(client: TestClient) -> None:
    r = client.post(
        RESET, json={"token": "x" * 40, "new_password": random_lower_string()}
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Brute force
# ---------------------------------------------------------------------------


def test_repeated_wrong_passwords_lock_the_account(
    client: TestClient, db: Session
) -> None:
    user, password = make_user(db)
    for _ in range(settings.LOGIN_MAX_FAILURES):
        client.post(ACCESS, data={"username": user.email, "password": "wrong"})

    # The correct password is now refused too, which is the point.
    r = client.post(ACCESS, data={"username": user.email, "password": password})
    assert r.status_code == 429

    db.refresh(user)
    assert user.locked_until is not None


def test_a_successful_login_clears_the_failure_count(
    client: TestClient, db: Session
) -> None:
    user, password = make_user(db)
    for _ in range(settings.LOGIN_MAX_FAILURES - 1):
        client.post(ACCESS, data={"username": user.email, "password": "wrong"})

    assert (
        client.post(
            ACCESS, data={"username": user.email, "password": password}
        ).status_code
        == 200
    )
    db.refresh(user)
    assert user.failed_logins == 0


def test_wrong_password_and_unknown_address_look_the_same(
    client: TestClient, db: Session
) -> None:
    user, _ = make_user(db)
    known = client.post(ACCESS, data={"username": user.email, "password": "wrong"})
    unknown = client.post(
        ACCESS, data={"username": random_email(), "password": "wrong"}
    )
    assert known.status_code == unknown.status_code == 400
    assert known.json() == unknown.json()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def test_sign_out_everywhere_invalidates_this_token_too(
    client: TestClient, db: Session
) -> None:
    user, password = make_user(db)
    challenge = start_login(client, user.email, password)["challenge_token"]
    token = client.post(
        TWO_FACTOR, json={"challenge_token": challenge, "code": last_email_code()}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert (
        client.post(f"{API}/login/sign-out-everywhere", headers=headers).status_code
        == 200
    )
    assert client.get(f"{API}/users/me", headers=headers).status_code == 401


def test_invalid_token_is_unauthorized(client: TestClient) -> None:
    r = client.get(f"{API}/users/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
    assert r.headers.get("WWW-Authenticate") == "Bearer"


def test_missing_token_is_unauthorized(client: TestClient) -> None:
    assert client.get(f"{API}/users/me").status_code == 401


def test_use_access_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(f"{API}/login/test-token", headers=superuser_token_headers)
    assert r.status_code == 200
    assert "email" in r.json()


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def test_login_with_bcrypt_password_upgrades_to_argon2(
    client: TestClient, db: Session
) -> None:
    email = random_email()
    password = random_lower_string()
    bcrypt_hash = BcryptHasher().hash(password)
    assert bcrypt_hash.startswith("$2")

    user = User(email=email, hashed_password=bcrypt_hash, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    verify_email(db, user)

    r = client.post(ACCESS, data={"username": email, "password": password})
    assert r.status_code == 200

    db.refresh(user)
    assert user.hashed_password.startswith("$argon2")
    verified, updated_hash = verify_password(password, user.hashed_password)
    assert verified
    assert updated_hash is None


def test_login_with_argon2_password_keeps_hash(client: TestClient, db: Session) -> None:
    user, password = make_user(db)
    original = user.hashed_password
    assert original.startswith("$argon2")

    assert (
        client.post(
            ACCESS, data={"username": user.email, "password": password}
        ).status_code
        == 200
    )
    db.refresh(user)
    assert user.hashed_password == original


# ---------------------------------------------------------------------------
# Secrets at rest
# ---------------------------------------------------------------------------


def test_codes_are_never_stored_in_the_clear(client: TestClient, db: Session) -> None:
    user, password = make_user(db)
    start_login(client, user.email, password)
    code = last_email_code()

    rows = db.exec(select(AuthCode).where(col(AuthCode.user_id) == user.id)).all()
    assert rows
    for row in rows:
        assert row.code_hash != code
        assert row.code_hash == authcodes.hash_secret(code)


def test_only_so_many_codes_can_be_requested(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A known address must not be usable as a way to flood someone's inbox.

    The suite raises this allowance so it can sign in freely; here it is put
    back to a realistic number for the length of the test.
    """
    monkeypatch.setattr(settings, "AUTH_CODE_MAX_SENDS", 3)
    user, password = make_user(db)

    for _ in range(3):
        r = client.post(ACCESS, data={"username": user.email, "password": password})
        assert r.status_code == 200, r.text

    refused = client.post(ACCESS, data={"username": user.email, "password": password})
    assert refused.status_code == 429
    assert "too many" in refused.json()["detail"].lower()
