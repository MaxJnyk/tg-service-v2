"""
Async SQLAlchemy движок и фабрика сессий.

Используем asyncpg как драйвер. Пул коннектов настраивается
через pool_size/max_overflow. pool_pre_ping защищает от мёртвых коннектов.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # True для логирования всех SQL-запросов (очень шумно!)
    pool_size=30,
    max_overflow=30,
    pool_pre_ping=True,
    pool_recycle=3600,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncGenerator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def close_engine() -> None:
    await engine.dispose()
