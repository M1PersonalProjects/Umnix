from __future__ import annotations

from typing import Optional

import asyncpg

from config import settings
from logger_config import logger


class Database:
    """Управляет общим пулом подключений PostgreSQL."""

    def __init__(self) -> None:
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        if self.pool is not None:
            return
        try:
            self.pool = await asyncpg.create_pool(
                dsn=settings.database_url,
                min_size=1,
                max_size=20,
                command_timeout=60,
            )
        except Exception as exc:
            logger.critical("database_connect_failed error=%s", type(exc).__name__)
            raise
        logger.info("database_connected")

    async def disconnect(self) -> None:
        if self.pool is None:
            return
        await self.pool.close()
        self.pool = None
        logger.info("database_disconnected")


db = Database()
