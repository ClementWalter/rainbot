"""SQLite database connection management."""

import logging
import os
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Thread-local storage for connections
_local = threading.local()

# Default database path
DEFAULT_DB_PATH = "data/rainbot.db"


def get_db_path() -> str:
    """Get the database path from environment or default."""
    return os.getenv("SQLITE_DB_PATH", DEFAULT_DB_PATH)


def get_connection() -> sqlite3.Connection:
    """
    Get a thread-local SQLite connection.

    Returns a connection that is reused within the same thread.
    This ensures thread safety while avoiding connection overhead.
    """
    if not hasattr(_local, "connection") or _local.connection is None:
        db_path = get_db_path()
        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        _local.connection = sqlite3.connect(db_path, check_same_thread=False)
        _local.connection.row_factory = sqlite3.Row
        # Enable foreign keys
        _local.connection.execute("PRAGMA foreign_keys = ON")
        logger.debug(f"Created new SQLite connection for thread {threading.current_thread().name}")

    return _local.connection


def init_database() -> None:
    """
    Initialize the database schema.

    Creates tables if they don't exist. Safe to call multiple times.
    """
    conn = get_connection()
    schema_path = Path(__file__).parent / "schema.sql"

    with open(schema_path) as f:
        schema_sql = f.read()

    conn.executescript(schema_sql)
    conn.commit()
    logger.info(f"Database initialized at {get_db_path()}")


def close_connection() -> None:
    """Close the thread-local connection if it exists."""
    if hasattr(_local, "connection") and _local.connection is not None:
        _local.connection.close()
        _local.connection = None
        logger.debug(f"Closed SQLite connection for thread {threading.current_thread().name}")
