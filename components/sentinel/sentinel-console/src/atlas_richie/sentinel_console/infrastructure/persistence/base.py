"""SQLAlchemy declarative base for Console-owned relational tables."""

from sqlalchemy.orm import DeclarativeBase


class ConsoleBase(DeclarativeBase):
    """Metadata owner for Console migrations and persistence mappings."""

