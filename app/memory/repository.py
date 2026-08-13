from datetime import UTC, datetime

from app.memory.database import Database


class MemoryRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save_conversation(
        self,
        request_id: str,
        role: str,
        content: str,
    ) -> int:
        created_at = datetime.now(UTC).isoformat()

        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO conversations (
                    request_id,
                    role,
                    content,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    request_id,
                    role,
                    content,
                    created_at,
                ),
            )

            return int(cursor.lastrowid)

    def get_conversations(
        self,
        request_id: str,
    ) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    request_id,
                    role,
                    content,
                    created_at
                FROM conversations
                WHERE request_id = ?
                ORDER BY id ASC
                """,
                (request_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    def save_project(
        self,
        name: str,
        description: str | None = None,
    ) -> int:
        now = datetime.now(UTC).isoformat()

        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO projects (
                    name,
                    description,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    name,
                    description,
                    now,
                    now,
                ),
            )

            return int(cursor.lastrowid)

    def get_project(
        self,
        name: str,
    ) -> dict[str, object] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    name,
                    description,
                    created_at,
                    updated_at
                FROM projects
                WHERE name = ?
                """,
                (name,),
            ).fetchone()

        if row is None:
            return None

        return dict(row)

    def update_project(
        self,
        name: str,
        description: str,
    ) -> bool:
        now = datetime.now(UTC).isoformat()

        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE projects
                SET
                    description = ?,
                    updated_at = ?
                WHERE name = ?
                """,
                (
                    description,
                    now,
                    name,
                ),
            )

        return cursor.rowcount > 0

    def save_preference(
        self,
        key: str,
        value: str,
    ) -> int:
        now = datetime.now(UTC).isoformat()

        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO preferences (
                    key,
                    value,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    key,
                    value,
                    now,
                    now,
                ),
            )

            return int(cursor.lastrowid)

    def get_preference(
        self,
        key: str,
    ) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT value
                FROM preferences
                WHERE key = ?
                """,
                (key,),
            ).fetchone()

        if row is None:
            return None

        return str(row["value"])

    def update_preference(
        self,
        key: str,
        value: str,
    ) -> bool:
        now = datetime.now(UTC).isoformat()

        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE preferences
                SET
                    value = ?,
                    updated_at = ?
                WHERE key = ?
                """,
                (
                    value,
                    now,
                    key,
                ),
            )

        return cursor.rowcount > 0