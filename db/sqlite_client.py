"""Async SQLite client. Single point of DB access — never open aiosqlite directly elsewhere.

`apply_migrations()` is idempotent (uses IF NOT EXISTS). Call once at startup.
"""
from pathlib import Path

import aiosqlite

from config.config import settings


_MIGRATION_PATH = Path(__file__).resolve().parent / "migrations" / "001_initial_schema.sql"


class SqliteClient:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or settings.CODEE_DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.db_path, timeout=5)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def apply_migrations(self) -> None:
        assert self._conn is not None, "call connect() first"
        sql = _MIGRATION_PATH.read_text(encoding="utf-8")
        await self._conn.executescript(sql)
        await self._conn.commit()

    async def execute(self, sql: str, params: tuple | dict | None = None) -> None:
        assert self._conn is not None
        await self._conn.execute(sql, params or ())
        await self._conn.commit()

    async def executemany(self, sql: str, rows: list) -> None:
        assert self._conn is not None
        await self._conn.executemany(sql, rows)
        await self._conn.commit()

    async def fetch_one(self, sql: str, params: tuple | dict | None = None):
        assert self._conn is not None
        cur = await self._conn.execute(sql, params or ())
        row = await cur.fetchone()
        await cur.close()
        return row

    async def fetch_all(self, sql: str, params: tuple | dict | None = None):
        assert self._conn is not None
        cur = await self._conn.execute(sql, params or ())
        rows = await cur.fetchall()
        await cur.close()
        return rows
