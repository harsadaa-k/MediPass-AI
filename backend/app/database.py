"""
Database engine + session setup.

Dev default: SQLite file (medipass.db) next to this package -- zero config.
Production path: set the MEDIPASS_DATABASE_URL env var to a Postgres URL, e.g.
  postgresql+psycopg2://user:password@host:5432/medipass
and nothing else in this file needs to change.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.environ.get(
    "MEDIPASS_DATABASE_URL",
    "sqlite:///./medipass.db",
)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a DB session, always closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def add_missing_columns(tables) -> None:
    """
    create_all() makes new tables but never adds columns to existing ones.
    For the named tables, add any nullable model column the database lacks
    (dev stand-in for an Alembic migration). Existing data is untouched.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    with engine.begin() as conn:
        for name in tables:
            if not inspector.has_table(name):
                continue
            have = {c["name"] for c in inspector.get_columns(name)}
            for column in Base.metadata.tables[name].columns:
                if column.name not in have and column.nullable:
                    col_type = column.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE {name} ADD COLUMN "{column.name}" {col_type}'))
