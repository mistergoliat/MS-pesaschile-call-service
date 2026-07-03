from sqlalchemy.engine import Engine

from app.db.database import init_db


def run_mvp_migrations(engine: Engine) -> None:
    """MVP bootstrap migration strategy using SQLAlchemy metadata."""
    init_db(engine)
