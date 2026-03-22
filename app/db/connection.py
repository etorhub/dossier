"""Database connection management."""

import os
from typing import Any

from psycopg2 import pool


def get_db_url() -> str:
    """Build DATABASE_URL from env vars or return DATABASE_URL if set."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    user = os.environ.get("POSTGRES_USER", "dossier")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ.get("POSTGRES_DB", "dossier")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


_connection_pool: pool.ThreadedConnectionPool | None = None


def get_pool() -> pool.ThreadedConnectionPool:
    """Get or create the connection pool."""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=get_db_url(),
        )
    return _connection_pool


def get_connection() -> Any:
    """Get a connection from the pool."""
    return get_pool().getconn()


def return_connection(conn: Any) -> None:
    """Return a connection to the pool."""
    get_pool().putconn(conn)
