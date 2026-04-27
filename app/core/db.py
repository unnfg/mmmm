import logging

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine, select

from app import crud
from app.core.config import settings
from app.models import User, UserCreate

logger = logging.getLogger(__name__)

# Log SQL queries only during development; disable in production to avoid data exposure.
engine = create_engine(settings.sqlalchemy_database_uri, echo=settings.debug)


# make sure all SQLModel models are imported (app.models) before initializing DB
# otherwise, SQLModel might fail to initialize relationships properly
# for more details: https://github.com/fastapi/full-stack-fastapi-template/issues/28


def init_db(session: Session) -> None:
    # Tables should be created with Alembic migrations
    # But if you don't want to use migrations, create
    # the tables un-commenting the next lines
    # from sqlmodel import SQLModel

    # This works because the models are already imported and registered from app.models
    # SQLModel.metadata.create_all(engine)

    user = session.exec(
        select(User).where(User.phone_number == settings.first_superuser)
    ).first()
    if not user:
        phone_number, password = settings.require_superuser_credentials()
        try:
            user_in = UserCreate(
                phone_number=phone_number,
                password=password,
                is_superuser=True,
            )
            crud.create_user(session=session, user_create=user_in)
            logger.info("Superuser created: %s", settings.first_superuser)

        except IntegrityError:
            session.rollback()
            # Guard superuser bootstrap against startup race (TOCTOU) by concurrent startup
            # Another worker has already been inserted, ignore this.
            logger.info("Superuser already exists (race condition handled)")
    else:
        logger.info("Superuser already exists, skipping init")
