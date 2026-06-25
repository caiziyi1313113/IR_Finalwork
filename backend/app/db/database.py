from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(
    settings.sqlite_url,
    connect_args={"check_same_thread": False} if settings.sqlite_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _ensure_sqlite_user_columns() -> None:
    if not settings.sqlite_url.startswith("sqlite"):
        return

    required_columns = {
        "identity": "VARCHAR(30) DEFAULT '本科生'",
        "college": "VARCHAR(100) DEFAULT ''",
        "major": "VARCHAR(100) DEFAULT ''",
        "interest_tags": "TEXT DEFAULT '[]'",
        "search_need": "TEXT DEFAULT ''",
        "search_need_text": "TEXT DEFAULT ''",
        "ai_behavior_profile": "TEXT DEFAULT '{}'",
        "ai_behavior_summary": "TEXT DEFAULT ''",
        "ai_behavior_source_hash": "VARCHAR(64) DEFAULT ''",
        "ai_behavior_status": "VARCHAR(20) DEFAULT 'idle'",
        "ai_behavior_error": "TEXT DEFAULT ''",
        "ai_behavior_query_count": "INTEGER DEFAULT 0",
        "ai_behavior_updated_at": "DATETIME",
    }

    with engine.begin() as connection:
        table_info = connection.execute(text("PRAGMA table_info(users)")).fetchall()
        if not table_info:
            return

        existing_columns = {row[1] for row in table_info}
        for column_name, definition in required_columns.items():
            if column_name not in existing_columns:
                connection.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {definition}"))
                existing_columns.add(column_name)

        if "search_need" in existing_columns and "search_need_text" in existing_columns:
            connection.execute(
                text(
                    """
                    UPDATE users
                    SET search_need_text = COALESCE(NULLIF(search_need_text, ''), search_need, '')
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE users
                    SET search_need = COALESCE(NULLIF(search_need, ''), search_need_text, '')
                    """
                )
            )

        if "interest_tags" in existing_columns:
            connection.execute(
                text(
                    """
                    UPDATE users
                    SET interest_tags = '[]'
                    WHERE interest_tags IS NULL OR TRIM(interest_tags) = ''
                    """
                )
            )


def init_db() -> None:
    from app.models import click_log, query_log, user  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_user_columns()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
