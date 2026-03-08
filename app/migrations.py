"""Lightweight version-based schema migrations.

Each migration is a function registered in MIGRATIONS with a sequential version
number.  On startup, ``run_migrations`` compares the stored schema version
against the latest migration and applies any that haven't run yet, in order.

To add a new migration:
    1. Write a function that accepts a SQLAlchemy ``Connection``.
    2. Append it to the ``MIGRATIONS`` list.
    The list index + 1 is used as the version number.
"""

import logging
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema-version bookkeeping
# ---------------------------------------------------------------------------

_VERSION_TABLE = "schema_version"


def _ensure_version_table(conn: Connection) -> None:
    conn.execute(text(
        f"CREATE TABLE IF NOT EXISTS {_VERSION_TABLE} "
        "(id INTEGER PRIMARY KEY, version INTEGER NOT NULL DEFAULT 0)"
    ))
    row = conn.execute(text(f"SELECT version FROM {_VERSION_TABLE} WHERE id = 1")).fetchone()
    if row is None:
        conn.execute(text(f"INSERT INTO {_VERSION_TABLE} (id, version) VALUES (1, 0)"))


def _get_version(conn: Connection) -> int:
    row = conn.execute(text(f"SELECT version FROM {_VERSION_TABLE} WHERE id = 1")).fetchone()
    return row[0] if row else 0


def _set_version(conn: Connection, version: int) -> None:
    conn.execute(text(f"UPDATE {_VERSION_TABLE} SET version = :v WHERE id = 1"), {"v": version})


# ---------------------------------------------------------------------------
# Migration functions — append new migrations to the end of the list
# ---------------------------------------------------------------------------

def _m001_add_notification_tested_columns(conn: Connection) -> None:
    """Add discord_tested, email_tested, ntfy_tested to notification_settings."""
    from sqlalchemy import inspect
    insp = inspect(conn)
    existing = {c["name"] for c in insp.get_columns("notification_settings")}
    for col in ("discord_tested", "email_tested", "ntfy_tested"):
        if col not in existing:
            conn.execute(text(
                f"ALTER TABLE notification_settings ADD COLUMN {col} BOOLEAN DEFAULT 0"
            ))


# Ordered list of migrations.  Index 0 → version 1, index 1 → version 2, etc.
MIGRATIONS: list = [
    _m001_add_notification_tested_columns,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_migrations(engine: Engine) -> None:
    """Apply any pending migrations inside a single transaction per migration."""
    with engine.begin() as conn:
        _ensure_version_table(conn)
        current = _get_version(conn)

    for idx, migration_fn in enumerate(MIGRATIONS):
        version = idx + 1
        if version <= current:
            continue
        logger.info("Applying migration %d: %s", version, migration_fn.__doc__ or migration_fn.__name__)
        with engine.begin() as conn:
            migration_fn(conn)
            _set_version(conn, version)

    latest = len(MIGRATIONS)
    if current < latest:
        logger.info("Migrations complete — schema now at version %d", latest)
    else:
        logger.debug("Schema up to date at version %d", latest)
