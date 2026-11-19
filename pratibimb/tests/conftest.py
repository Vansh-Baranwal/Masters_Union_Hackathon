"""
Shared pytest fixtures.
Uses an in-memory SQLite database — no file left behind after each test.
"""
from __future__ import annotations

import os
import pytest
import pytest_asyncio

# Point every module that reads DATABASE_URL at an in-memory SQLite
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SARVAM_API_KEY", "test-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "0:test")
os.environ.setdefault("RAW_IMAGE_DIR", "/tmp/pratibimb_test_images")

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from core.models import Base
from core.store import Store


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s
        await s.rollback()


@pytest_asyncio.fixture
async def store(session):
    return Store(session)
