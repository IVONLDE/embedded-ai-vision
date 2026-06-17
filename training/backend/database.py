from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


Base = declarative_base()


def create_backend_engine(database_path: Path | str):
    database_file = Path(database_path)
    database_file.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{database_file}",
        connect_args={"check_same_thread": False},
        future=True,
    )


def create_session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


def initialize_backend_database(engine) -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
