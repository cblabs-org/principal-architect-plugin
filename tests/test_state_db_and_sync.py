"""Initial test suite for state DB and sync foundation."""

import sqlite3


def test_sqlite_available():
    """Verify sqlite3 is available in python stdlib with WAL support."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    row = cur.fetchone()
    assert row is not None
    conn.close()
