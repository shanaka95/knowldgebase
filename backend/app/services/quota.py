"""What an account is allowed, and whether it has room for one more page.

Every limit resolves through the same four tiers, most specific first:

    the account's own override
      → the group it is in
        → the default group
          → a built-in constant

`NULL` at any tier means "inherit from the one below", which is what makes
"clear this override" expressible at all. A non-null column with a default
cannot say it. Zero is a real answer - "this account may not create pages" -
so every test here is ``is not None`` and never truthiness.

**The default group is the floor for everyone**, not only for accounts with no
group. A group that leaves a number unset falls through to the default group
rather than past it to the constant; otherwise raising the default would not
lift the people it was raised for.

Groups are an administrative device and the people in them are never told.
Nothing in this module is serialised to a non-administrator: `to_user_public`
emits resolved numbers, and the refusal messages below name the limit and never
the group.

Adding a future setting is four lines: a nullable column on `user` and on
`usergroup`, one entry in `LIMITS`, and a field on the admin schemas. The
resolver, the serialiser and the admin API pick it up without changing.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlmodel import Session, col, func, select

from app.core.config import settings
from app.models import (
    Document,
    ImportJob,
    ImportStatus,
    LimitDefinition,
    ResolvedLimit,
    User,
    UserGroup,
)

# The one group the code names. A fixed id rather than a scanned boolean: two
# rows claiming `is_default` would make resolution order-dependent, and zero
# rows would silently drop everybody to the constants.
DEFAULT_GROUP_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_GROUP_SLUG = "default"
DEFAULT_GROUP_NAME = "Default"

# What an administrator's own account starts with.
#
# Not an exemption in the resolver - a plain override, so it shows up in the
# admin table like anybody else's and can be lowered. The operator of an
# installation should not be locked out of it by a product default, and on an
# instance that has been running a while they are the account most likely to be
# past one already.
SUPERUSER_PAGE_ALLOWANCE = 100_000


@dataclass(frozen=True, slots=True)
class LimitSpec:
    """One administrable setting: where it lives and what it falls back to."""

    key: str
    label: str
    description: str
    settings_attr: str
    maximum: int = 1_000_000
    unit: str = ""

    @property
    def fallback(self) -> int:
        return int(getattr(settings, self.settings_attr))


LIMITS: tuple[LimitSpec, ...] = (
    LimitSpec(
        key="max_pages",
        label="Pages",
        description="How many pages an account may create. Deleting a page frees one.",
        settings_attr="MAX_PAGES_PER_USER",
        unit="pages",
    ),
    LimitSpec(
        key="max_shares_per_document",
        label="People per page",
        description="How many people one page may be shared with, counting invitations.",
        settings_attr="SHARE_MAX_RECIPIENTS",
        maximum=10_000,
        unit="people",
    ),
    LimitSpec(
        key="max_members_per_space",
        label="People per space",
        description="How many people one space may have, counting invitations.",
        settings_attr="SHARE_MAX_RECIPIENTS",
        maximum=10_000,
        unit="people",
    ),
    LimitSpec(
        key="monthly_credits",
        label="Credits a month",
        description=(
            "Model work an account may do each calendar month. One credit is "
            "a thousand tokens, ten embeddings, or ten rerank calls."
        ),
        settings_attr="MONTHLY_CREDITS",
        maximum=10_000_000,
        unit="credits",
    ),
)

LIMIT_KEYS = frozenset(spec.key for spec in LIMITS)


class QuotaExceeded(Exception):
    """An account is at one of its limits.

    Deliberately not an ``HTTPException``: the worker calls the same check and
    has to fail a job rather than raise into a request. Routes turn it into a
    409, matching how this codebase already reports state conflicts.
    """


@dataclass(frozen=True, slots=True)
class Limits:
    max_pages: int
    max_shares_per_document: int
    max_members_per_space: int
    monthly_credits: int


# ---------------------------------------------------------------------------
# The default group
# ---------------------------------------------------------------------------


def ensure_default_group(session: Session) -> UserGroup:
    """Make sure the default group exists, and return it.

    Called from `init_db` at every boot as well as being seeded by the
    migration. Two reasons: the tests truncate `usergroup` between runs, so a
    migration-only seed would survive exactly one run; and a resolver that can
    be knocked out by one missing row is not a resolver.
    """
    group = session.get(UserGroup, DEFAULT_GROUP_ID)
    if group is not None:
        return group
    group = UserGroup(
        id=DEFAULT_GROUP_ID,
        slug=DEFAULT_GROUP_SLUG,
        name=DEFAULT_GROUP_NAME,
        description="Applies to everyone who has not been put in another group.",
        is_default=True,
        is_system=True,
        max_pages=settings.MAX_PAGES_PER_USER,
        max_shares_per_document=settings.SHARE_MAX_RECIPIENTS,
        max_members_per_space=settings.SHARE_MAX_RECIPIENTS,
        monthly_credits=settings.MONTHLY_CREDITS,
    )
    session.add(group)
    session.commit()
    session.refresh(group)
    return group


def default_group(session: Session) -> UserGroup | None:
    """The default group, or None if it has somehow gone.

    Callers must treat None as "use the constants" rather than as an error: a
    missing configuration row must never be read as "no pages allowed".
    """
    return session.get(UserGroup, DEFAULT_GROUP_ID)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _tier_values(
    user: User, group: UserGroup | None, fallback: UserGroup | None, spec: LimitSpec
) -> tuple[int, str, int | None, int | None, int]:
    """Resolve one limit, and report the whole chain that produced it."""
    override = getattr(user, spec.key, None)
    group_value = getattr(group, spec.key, None) if group is not None else None
    default_value = getattr(fallback, spec.key, None) if fallback is not None else None
    if default_value is None:
        default_value = spec.fallback

    if override is not None:
        return override, "user", override, group_value, default_value
    if group_value is not None:
        return group_value, "group", None, group_value, default_value
    if fallback is not None and getattr(fallback, spec.key, None) is not None:
        return default_value, "default_group", None, None, default_value
    return spec.fallback, "system", None, None, default_value


def resolve_limits(
    session: Session,
    user: User,
    *,
    groups: dict[uuid.UUID, UserGroup] | None = None,
) -> Limits:
    """Every limit in force for this account.

    Pass ``groups`` when resolving a page of users so this does not issue a
    query per row - there will only ever be a few groups.
    """
    group, fallback = _groups_for(session, user, groups)
    values = {spec.key: _tier_values(user, group, fallback, spec)[0] for spec in LIMITS}
    return Limits(**values)


def resolve_detail(
    session: Session,
    user: User,
    *,
    groups: dict[uuid.UUID, UserGroup] | None = None,
) -> list[ResolvedLimit]:
    """The same answer, with the reasoning attached, for the admin screen."""
    group, fallback = _groups_for(session, user, groups)
    out: list[ResolvedLimit] = []
    for spec in LIMITS:
        value, source, override, group_value, default_value = _tier_values(
            user, group, fallback, spec
        )
        label = None
        if source == "group" and group is not None:
            label = group.name
        elif source == "default_group" and fallback is not None:
            label = fallback.name
        out.append(
            ResolvedLimit(
                key=spec.key,
                label=spec.label,
                value=value,
                source=source,
                source_label=label,
                override=override,
                group_value=group_value,
                default_value=default_value,
            )
        )
    return out


def _groups_for(
    session: Session, user: User, groups: dict[uuid.UUID, UserGroup] | None
) -> tuple[UserGroup | None, UserGroup | None]:
    fallback = (
        groups.get(DEFAULT_GROUP_ID) if groups is not None else default_group(session)
    )
    if user.group_id is None:
        return None, fallback
    group = (
        groups.get(user.group_id)
        if groups is not None
        else session.get(UserGroup, user.group_id)
    )
    return group, fallback


def load_groups(session: Session) -> dict[uuid.UUID, UserGroup]:
    """Every group, keyed by id - for resolving a list of users in one query."""
    return {g.id: g for g in session.exec(select(UserGroup)).all()}


def limit_definitions() -> list[LimitDefinition]:
    """The catalogue an admin form is drawn from."""
    return [
        LimitDefinition(
            key=spec.key,
            label=spec.label,
            description=spec.description,
            default=spec.fallback,
            minimum=0,
            maximum=spec.maximum,
            unit=spec.unit,
        )
        for spec in LIMITS
    ]


# ---------------------------------------------------------------------------
# Counting, and the check itself
# ---------------------------------------------------------------------------

# An import that has not finished is a page that is coming. Counting them is
# what stops somebody queueing five hundred files to get past a limit of a
# hundred - the same reasoning as `sharing.recipient_count` counting invitations.
PENDING_IMPORT_STATUSES = (
    ImportStatus.queued,
    ImportStatus.rendering,
    ImportStatus.parsing,
    ImportStatus.creating,
)


def page_count(session: Session, user_id: uuid.UUID) -> int:
    """How many pages this account has made.

    Exact rather than a stored counter, because pages are hard-deleted: there
    are no tombstones to filter and deleting a page frees its place at once. A
    counter would drift on every delete, every cancelled import and every
    account deletion that orphans a page.
    """
    return int(
        session.exec(
            select(func.count())
            .select_from(Document)
            .where(Document.created_by == user_id)
        ).one()
    )


def pending_page_count(session: Session, user_id: uuid.UUID) -> int:
    """Pages this account has queued but not yet received.

    One per job, however many files it carries: a combined import is several
    files becoming a single page. Finished jobs are excluded because their page
    is already counted by `page_count`.
    """
    return int(
        session.exec(
            select(func.count())
            .select_from(ImportJob)
            .where(
                ImportJob.created_by == user_id,
                col(ImportJob.status).in_(PENDING_IMPORT_STATUSES),
            )
        ).one()
    )


def pages_used(session: Session, user_id: uuid.UUID) -> int:
    return page_count(session, user_id) + pending_page_count(session, user_id)


def pages_used_for(
    session: Session, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """How much every account on a page of users has spent, in two queries.

    The single-account version costs two counts, which is nothing once and two
    thousand queries for a list of a thousand. The admin table asks for all of
    them at once, so it gets them all at once.
    """
    if not user_ids:
        return {}
    wanted = list(user_ids)
    used: dict[uuid.UUID, int] = dict.fromkeys(wanted, 0)

    for owner, count in session.exec(
        select(Document.created_by, func.count())
        .where(col(Document.created_by).in_(wanted))
        .group_by(col(Document.created_by))
    ).all():
        if owner is not None:
            used[owner] = used.get(owner, 0) + int(count)

    for owner, count in session.exec(
        select(ImportJob.created_by, func.count())
        .where(
            col(ImportJob.created_by).in_(wanted),
            col(ImportJob.status).in_(PENDING_IMPORT_STATUSES),
        )
        .group_by(col(ImportJob.created_by))
    ).all():
        if owner is not None:
            used[owner] = used.get(owner, 0) + int(count)

    return used


def lock_user_quota(session: Session, user_id: uuid.UUID) -> None:
    """Serialise this account's quota check against its own concurrent writes.

    Without it two requests can both read 99 and both insert, giving 101. That
    is tolerable for a single page and not tolerable for imports, where two
    twenty-file batches overshoot by forty - so the import paths take this and
    the single-page paths do not.

    A transaction-scoped advisory lock: released at COMMIT or ROLLBACK, so
    there is nothing to clean up. Always taken first and always keyed on the one
    acting account, so no transaction ever holds two and no cycle is
    constructible. Acquire it *after* any upload or network round trip, never
    across one.
    """
    session.exec(
        select(func.pg_advisory_xact_lock(_QUOTA_LOCK_CLASS, _lock_key(user_id)))
    ).one()


# A fixed class id, so this lock can never collide with another advisory lock
# someone adds later.
_QUOTA_LOCK_CLASS = 4711


def _lock_key(user_id: uuid.UUID) -> int:
    """A signed 32-bit key from a uuid, which is what the two-int form takes."""
    return int.from_bytes(user_id.bytes[:4], "big", signed=True)


def ensure_page_capacity(
    session: Session,
    user_id: uuid.UUID | None,
    *,
    wanted: int = 1,
    groups: dict[uuid.UUID, UserGroup] | None = None,
) -> None:
    """Refuse if this account has no room for ``wanted`` more pages.

    ``user_id`` may be None: an import whose owner was deleted mid-flight runs
    to completion and produces a page attributed to nobody. Refusing it would
    punish no one and would turn a deleted account into worker exceptions.
    """
    if user_id is None:
        return
    user = session.get(User, user_id)
    if user is None:
        return

    limit = resolve_limits(session, user, groups=groups).max_pages
    used = pages_used(session, user_id)
    if used + wanted <= limit:
        return

    raise QuotaExceeded(page_limit_message(limit, used, wanted))


def page_limit_message(limit: int, used: int, wanted: int) -> str:
    """Why the refusal happened, in terms the reader can act on.

    Never mentions groups: an account is told its own number, not where the
    number came from.
    """
    pages = "page" if limit == 1 else "pages"
    if limit == 0:
        return (
            "This account cannot create pages. Ask an administrator to raise the limit."
        )
    if wanted > 1:
        return (
            f"This would take you past your limit of {limit} {pages} "
            f"({used} already used, {wanted} more requested). "
            "Delete some pages you no longer need, or ask an administrator to "
            "raise the limit."
        )
    return (
        f"You have reached your limit of {limit} {pages}. "
        "Delete a page you no longer need, or ask an administrator to raise it."
    )


def limits_for_owner(session: Session, owner: User | None) -> Limits:
    """Limits for a space's owner, falling back when the owner has gone.

    Sharing limits belong to whoever owns the space rather than whoever pressed
    the button - it is their content being handed out. A space whose owner no
    longer exists falls back to the constants.
    """
    if owner is None:
        return Limits(
            max_pages=settings.MAX_PAGES_PER_USER,
            max_shares_per_document=settings.SHARE_MAX_RECIPIENTS,
            max_members_per_space=settings.SHARE_MAX_RECIPIENTS,
            monthly_credits=settings.MONTHLY_CREDITS,
        )
    return resolve_limits(session, owner)


def apply_overrides(user: User, overrides: dict[str, int]) -> None:
    """Replace this account's overrides with exactly what was sent.

    A complete map, not a patch: a key that is absent is an override that is
    not set. That is what an empty form field naturally produces, so "blank
    means inherit" needs no special handling in the browser.
    """
    unknown = set(overrides) - LIMIT_KEYS
    if unknown:
        raise ValueError(f"Unknown limit: {', '.join(sorted(unknown))}")
    for spec in LIMITS:
        setattr(user, spec.key, overrides.get(spec.key))


def member_counts(
    session: Session, group_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """How many accounts sit in each group, in one query rather than N."""
    if not group_ids:
        return {}
    rows = session.exec(
        select(User.group_id, func.count())
        .where(col(User.group_id).in_(group_ids))
        .group_by(col(User.group_id))
    ).all()
    return {gid: int(count) for gid, count in rows if gid is not None}
