"""Codee Phase 1a entry point.

Runs:
  - PoolsIngestor (cron loop, 60 min)
  - FastAPI/uvicorn HTTP server (sync within the asyncio loop via uvicorn.Server)
    Serves both the JSON API and the static dashboard from web/
"""
import asyncio
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config.config import settings
from db.sqlite_client import SqliteClient
from services.api.router import router as api_router, set_db
from services.pools.ingestor import PoolsIngestor


def _make_app() -> FastAPI:
    app = FastAPI(title="Codee API", version="0.1.0")
    app.include_router(api_router)
    # Serve the dashboard built in Task 18 from web/ at the site root.
    # html=True makes / -> /index.html; the API stays on /api/codee/*.
    web_dir = Path(__file__).resolve().parent / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


async def _main():
    logging.basicConfig(
        level=settings.CODEE_LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    log = logging.getLogger("codee.main")

    db = SqliteClient()
    await db.connect()
    await db.apply_migrations()
    set_db(db)
    log.info("DB ready at %s", db.db_path)

    app = _make_app()
    server = uvicorn.Server(uvicorn.Config(app, host=settings.API_HOST, port=settings.API_PORT, log_level="info"))
    ingestor = PoolsIngestor(db)

    try:
        await asyncio.gather(
            ingestor.run(),
            server.serve(),
            return_exceptions=False,
        )
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(_main())
