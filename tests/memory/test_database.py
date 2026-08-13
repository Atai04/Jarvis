import sqlite3

from app.memory.database import Database


def test_database_initializes_tables(tmp_path):
    database = Database(tmp_path / "jarvis.db")

    database.initialize()

    with database.connect() as connection:
        tables = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        ).fetchall()

    table_names = [row["name"] for row in tables]

    assert "conversations" in table_names
    assert "projects" in table_names
    assert "preferences" in table_names


def test_database_uses_sqlite_file(tmp_path):
    database_path = tmp_path / "jarvis.db"
    database = Database(database_path)

    database.initialize()

    assert database_path.exists()

    with database.connect() as connection:
        assert isinstance(connection, sqlite3.Connection)


def test_database_connection_uses_row_factory(tmp_path):
    database = Database(tmp_path / "jarvis.db")

    connection = database.connect()

    try:
        assert connection.row_factory is sqlite3.Row
    finally:
        connection.close()