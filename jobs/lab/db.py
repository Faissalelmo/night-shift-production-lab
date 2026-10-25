import psycopg

from lab import config


def connect() -> psycopg.Connection:
    # autocommit: every `with conn.transaction():` block is then a real BEGIN/COMMIT.
    # Without it psycopg opens an implicit transaction on the first query and nested
    # transaction() blocks become mere savepoints — the import would archive a file
    # before its rows were actually committed.
    return psycopg.connect(config.DATABASE_URL, connect_timeout=5, autocommit=True)


def fault(conn: psycopg.Connection, name: str) -> float:
    """Value of an injected fault switch (see lab_faults), 0 when not set."""
    row = conn.execute("SELECT value FROM lab_faults WHERE name = %s", (name,)).fetchone()
    return float(row[0]) if row else 0.0
