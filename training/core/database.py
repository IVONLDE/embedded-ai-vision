from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Legacy database URL — kept for test compatibility.
# New application code should use backend.database instead.
SQLALCHEMY_DATABASE_URL = "sqlite:///./data/isg.sqlite3"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

from .models import *  # noqa: E402,F401 — legacy model registration

# Also register the new backend schema
from backend.database import Base as BackendBase  # noqa: E402


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    BackendBase.metadata.create_all(bind=engine)
