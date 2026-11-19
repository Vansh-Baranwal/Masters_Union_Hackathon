"""FastAPI dependency injectors."""
from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.store import Store


async def get_store() -> AsyncGenerator[Store, None]:
    async with get_session() as session:
        yield Store(session)
