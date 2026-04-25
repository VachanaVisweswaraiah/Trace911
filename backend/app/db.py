"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.models.orm import Base

engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    future=True,
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    """Create tables if missing. Demo-grade; swap for Alembic if it grows."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    await engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Yields a session; commits on success, rolls back on error."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
