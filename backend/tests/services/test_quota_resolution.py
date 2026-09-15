"""Which number applies to an account, and where it came from.

Four tiers, most specific first: the account's own override, its group, the
default group, then a built-in constant. NULL at any tier means "inherit",
which is the only way "clear this override" can be said at all.
"""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session

from app.core.config import settings
from app.models import User, UserGroup
from app.services import quota
from tests.utils.kb import create_user_with_password


def _group(db: Session, **limits: int | None) -> UserGroup:
    group = UserGroup(
        slug=f"g-{uuid.uuid4().hex[:8]}",
        name=f"Group {uuid.uuid4().hex[:8]}",
        **limits,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def _assign(db: Session, user: User, group: UserGroup | None) -> None:
    user.group_id = group.id if group else None
    db.add(user)
    db.commit()


def test_an_account_with_nothing_set_gets_the_default_groups_number(
    db: Session,
) -> None:
    user, _ = create_user_with_password(db)
    assert quota.resolve_limits(db, user).max_pages == 100


def test_a_groups_number_applies_to_everyone_in_it(db: Session) -> None:
    user, _ = create_user_with_password(db)
    _assign(db, user, _group(db, max_pages=250))
    assert quota.resolve_limits(db, user).max_pages == 250


def test_an_accounts_own_number_beats_its_groups(db: Session) -> None:
    user, _ = create_user_with_password(db)
    _assign(db, user, _group(db, max_pages=250))
    user.max_pages = 7
    db.add(user)
    db.commit()
    assert quota.resolve_limits(db, user).max_pages == 7


def test_a_group_that_sets_nothing_falls_through_to_the_defaults(
    db: Session,
) -> None:
    """Not past them to the constant: the default group is the floor for all."""
    user, _ = create_user_with_password(db)
    _assign(db, user, _group(db, max_pages=None))

    fallback = quota.default_group(db)
    assert fallback is not None
    original = fallback.max_pages
    fallback.max_pages = 321
    db.add(fallback)
    db.commit()
    try:
        detail = {d.key: d for d in quota.resolve_detail(db, user)}
        assert detail["max_pages"].value == 321
        assert detail["max_pages"].source == "default_group"
    finally:
        # The default group is shared by every test in the session, so a test
        # that moves it has to move it back.
        fallback.max_pages = original
        db.add(fallback)
        db.commit()


def test_a_limit_of_zero_is_a_real_answer_not_an_absent_one(db: Session) -> None:
    """`0` means "may not create pages"; it must not be read as "inherit"."""
    user, _ = create_user_with_password(db)
    user.max_pages = 0
    db.add(user)
    db.commit()
    assert quota.resolve_limits(db, user).max_pages == 0


def test_clearing_an_override_goes_back_to_inheriting(db: Session) -> None:
    user, _ = create_user_with_password(db)
    _assign(db, user, _group(db, max_pages=250))
    user.max_pages = 7
    db.add(user)
    db.commit()

    quota.apply_overrides(user, {})
    db.add(user)
    db.commit()
    assert quota.resolve_limits(db, user).max_pages == 250


def test_deleting_a_group_returns_its_members_to_the_defaults(
    db: Session,
) -> None:
    user, _ = create_user_with_password(db)
    group = _group(db, max_pages=250)
    _assign(db, user, group)
    assert quota.resolve_limits(db, user).max_pages == 250

    db.delete(group)
    db.commit()
    db.refresh(user)
    assert user.group_id is None
    assert quota.resolve_limits(db, user).max_pages == 100


def test_the_defaults_survive_the_default_group_being_deleted(
    db: Session,
) -> None:
    """A missing configuration row must never be read as "no pages allowed"."""
    user, _ = create_user_with_password(db)
    fallback = quota.default_group(db)
    assert fallback is not None
    db.delete(fallback)
    db.commit()

    assert quota.resolve_limits(db, user).max_pages == settings.MAX_PAGES_PER_USER
    quota.ensure_default_group(db)  # put it back for the rest of the session


def test_a_second_group_cannot_claim_to_be_the_default(db: Session) -> None:
    db.add(
        UserGroup(slug=f"x-{uuid.uuid4().hex[:8]}", name="Impostor", is_default=True)
    )
    with pytest.raises(Exception):  # noqa: B017 - the driver's IntegrityError
        db.commit()
    db.rollback()


def test_an_unknown_limit_is_refused_rather_than_silently_stored(
    db: Session,
) -> None:
    user, _ = create_user_with_password(db)
    with pytest.raises(ValueError, match="Unknown limit"):
        quota.apply_overrides(user, {"max_bananas": 3})


def test_the_two_older_limits_resolve_the_same_way(db: Session) -> None:
    """They were per-account columns; they are now part of the same chain."""
    user, _ = create_user_with_password(db)
    assert quota.resolve_limits(db, user).max_shares_per_document == 50

    _assign(db, user, _group(db, max_shares_per_document=3))
    assert quota.resolve_limits(db, user).max_shares_per_document == 3
