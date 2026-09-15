"""An account's own usage, for the person it belongs to.

Deliberately separate from `/admin/usage`, and deliberately not one endpoint
with a role-dependent payload. Cost is absent from `MyUsage` at the type level,
so nothing here can leak what somebody's questions cost to run - the same way
`UserPublic` cannot leak which group an account is in.

What a person gets is what they did: questions asked, searches run, pages
imported, and the tokens behind them.
"""

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, SessionDep
from app.models import MyUsage, UsageFeature
from app.services import usage

router = APIRouter(prefix="/usage", tags=["usage"])

# How each feature reads to the person who used it. The enum values are for
# machines; these are for the dashboard.
FEATURE_LABELS: dict[str, str] = {
    UsageFeature.ask: "Questions",
    UsageFeature.search: "Searches",
    UsageFeature.import_: "Imports",
    UsageFeature.indexing: "Indexing",
    UsageFeature.translation: "Translations",
    UsageFeature.suggestions: "Example searches",
    UsageFeature.agent: "Agents",
}


def resolve(frm: date | None, to: date | None) -> usage.Range:
    """The range asked for, or a 422 saying why it cannot be served."""
    try:
        return usage.resolve_range(frm, to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/me", response_model=MyUsage)
def read_my_usage(
    session: SessionDep,
    current_user: CurrentUser,
    frm: date | None = Query(default=None, alias="from"),
    to: date | None = None,
) -> Any:
    """Everything one account's dashboard needs, in one request.

    Three breakdowns rather than three endpoints: they are read together, they
    come from the same scan, and a dashboard that renders in one round trip has
    no half-drawn state to design for.
    """
    rng = resolve(frm, to)
    q = usage.Query(rng=rng, user_ids=[current_user.id])
    models = usage.by_model(session, q)
    return MyUsage(
        range=usage.public_range(rng),
        totals=usage.public_totals(usage.totals(session, q)),
        by_feature=usage.public_points(
            usage.by_feature(session, q), label=FEATURE_LABELS.get
        ),
        by_day=usage.public_points(usage.by_day(session, q)),
        by_model=usage.public_points(
            usage.model_rows(models), label=usage.model_labels(models).get
        ),
    )
