import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.backend import BackendDatabase
from app.db import Database
from migrations.runner import migrate


class _FakeBackendClient:
    def __init__(self):
        self.flows: dict[tuple[int, str], dict] = {}

    async def request(self, method: str, path: str, **kwargs):
        if method == "GET" and path == "/internal/bot/v1/events/7/registrations/200":
            return {"status": "registered", "attended": True}
        if method == "PUT" and path == "/internal/bot/v1/flows/200/feedback":
            self.flows[(200, "feedback")] = kwargs["json"]
            return {"stored": True}
        raise AssertionError(f"Unexpected backend request: {method} {path}")


class BackendDatabaseTests(unittest.TestCase):
    def test_feedback_flow_uses_backend_attendance_without_local_registration(self):
        asyncio.run(self._test_feedback_flow_uses_backend_attendance_without_local_registration())

    async def _test_feedback_flow_uses_backend_attendance_without_local_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bot.sqlite3"
            migrate(path, create_backup=False)
            local = Database(path)
            await local.initialize()
            async with local.connect() as connection:
                now = datetime.now(timezone.utc).isoformat()
                await connection.execute(
                    """INSERT INTO posts(
                           id,creator_id,text,created_at
                       ) VALUES(?,?,?,?)""",
                    (7, 200, "Тестовое мероприятие", now),
                )
                await connection.execute(
                    """INSERT INTO user_profiles(
                           user_id,surname,given_name,full_name,created_at,updated_at
                       ) VALUES(?,?,?,?,?,?)""",
                    (200, "Тестов", "Тест", "Тест Тестов", now, now),
                )
                await connection.commit()
            client = _FakeBackendClient()
            database = BackendDatabase(local, client)

            self.assertTrue(await database.begin_feedback_flow(200, 7))
            self.assertEqual(
                client.flows[(200, "feedback")],
                {"publication_id": 7, "stage": None},
            )
            self.assertIsNone(await local.feedback_flow(200))


if __name__ == "__main__":
    unittest.main()
