from sqlmodel import Session, create_engine, select

from app import crud
from app.core.config import settings
from app.models import User, UserCreate, get_datetime_utc
from app.services.quota import SUPERUSER_PAGE_ALLOWANCE, ensure_default_group

engine = create_engine(str(settings.DATABASE_URL), pool_pre_ping=True)


# make sure all SQLModel models are imported (app.models) before initializing DB
# otherwise, SQLModel might fail to initialize relationships properly
# for more details: https://github.com/fastapi/full-stack-fastapi-template/issues/28


def init_db(session: Session) -> None:
    # Before the superuser, because resolving anybody's limits needs it. Seeded
    # here as well as by the migration: the tests truncate `usergroup`, so a
    # migration-only seed would survive exactly one run.
    ensure_default_group(session)

    # Tables should be created with Alembic migrations
    # But if you don't want to use migrations, create
    # the tables un-commenting the next lines
    # from sqlmodel import SQLModel

    # This works because the models are already imported and registered from app.models
    # SQLModel.metadata.create_all(engine)

    user = session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    if not user:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        user = crud.create_user(session=session, user_create=user_in)
        # A visible allowance rather than a hidden exemption: it appears in the
        # admin table as an override and can be lowered like any other.
        user.max_pages = SUPERUSER_PAGE_ALLOWANCE
        # The administrator is created by the operator, not by someone filling
        # in a form, so there is no address to confirm and nobody to confirm it.
        user.email_verified_at = get_datetime_utc()
        session.add(user)
        session.commit()
