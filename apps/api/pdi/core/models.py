"""Shared SQLAlchemy registry for PDI's persistent domain models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Stable model registry; domain modules own the tables registered here."""
