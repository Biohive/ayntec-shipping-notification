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


def _m002_add_check_logs_and_summary_configs(conn: Connection) -> None:
    """Add check_logs and summary_configs tables for daily summary feature."""
    from sqlalchemy import inspect
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    if "check_logs" not in existing_tables:
        conn.execute(text(
            "CREATE TABLE check_logs ("
            "  id INTEGER PRIMARY KEY,"
            "  user_id INTEGER NOT NULL REFERENCES users(id),"
            "  checked_at DATETIME NOT NULL"
            ")"
        ))

    if "summary_configs" not in existing_tables:
        conn.execute(text(
            "CREATE TABLE summary_configs ("
            "  id INTEGER PRIMARY KEY,"
            "  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),"
            "  enabled BOOLEAN NOT NULL DEFAULT 0,"
            "  delivery_hour INTEGER NOT NULL DEFAULT 20,"
            "  delivery_minute INTEGER NOT NULL DEFAULT 0,"
            "  use_discord BOOLEAN NOT NULL DEFAULT 1,"
            "  use_email BOOLEAN NOT NULL DEFAULT 1,"
            "  use_ntfy BOOLEAN NOT NULL DEFAULT 1,"
            "  last_sent_at DATETIME"
            ")"
        ))


def _m003_add_summary_timezone_and_fix_defaults(conn: Connection) -> None:
    """Add timezone column to summary_configs and fix channel defaults to false."""
    from sqlalchemy import inspect
    insp = inspect(conn)
    existing_tables = insp.get_table_names()
    if "summary_configs" in existing_tables:
        existing_cols = {c["name"] for c in insp.get_columns("summary_configs")}
        if "timezone" not in existing_cols:
            conn.execute(text(
                "ALTER TABLE summary_configs ADD COLUMN timezone TEXT NOT NULL DEFAULT 'America/New_York'"
            ))
        # Fix any existing rows that had all-true defaults for use_* columns
        # (only when all three are true and the config was never enabled — treat
        #  those as "just created with bad defaults" and reset them to false).
        conn.execute(text(
            "UPDATE summary_configs "
            "SET use_discord = 0, use_email = 0, use_ntfy = 0 "
            "WHERE enabled = 0 AND use_discord = 1 AND use_email = 1 AND use_ntfy = 1"
        ))


def _m004_add_device_type_to_orders(conn: Connection) -> None:
    """Add device_type column to orders for product-specific range matching."""
    from sqlalchemy import inspect
    insp = inspect(conn)
    existing = {c["name"] for c in insp.get_columns("orders")}
    if "device_type" not in existing:
        conn.execute(text("ALTER TABLE orders ADD COLUMN device_type TEXT"))


# Ordered list of migrations.  Index 0 → version 1, index 1 → version 2, etc.
MIGRATIONS: list = [
    _m001_add_notification_tested_columns,
    _m002_add_check_logs_and_summary_configs,
    _m003_add_summary_timezone_and_fix_defaults,
    _m004_add_device_type_to_orders,
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
