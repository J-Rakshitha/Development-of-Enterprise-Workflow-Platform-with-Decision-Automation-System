"""
Alembic migration runner — applies additive schema changes without deleting data.

Startup flow: create_all() ensures base tables exist, then Alembic applies any
new columns/indexes idempotently (safe for existing SQLite databases).
"""
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger("migrations")

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def run_migrations() -> None:
    """Run Alembic upgrade to head (sync — call via asyncio.to_thread)."""
    ini_path = _BACKEND_DIR / "alembic.ini"
    if not ini_path.exists():
        logger.warning("alembic.ini not found — skipping migrations")
        return
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    try:
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext
        from sqlalchemy import create_engine
        from app.core.config import settings

        db_url = settings.DATABASE_URL.replace("+aiosqlite", "")
        engine = create_engine(db_url)
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current = context.get_current_revision()
        head = ScriptDirectory.from_config(cfg).get_current_head()
        if current == head:
            logger.info("Database already at migration head (%s) — skipping upgrade", head)
            return
    except Exception as exc:
        logger.warning("Could not check migration revision (will run upgrade): %s", exc)

    command.upgrade(cfg, "head")
    logger.info("Database migrations applied (head)")
