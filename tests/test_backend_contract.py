import unittest
from datetime import datetime, timezone

from app.backend import BackendDatabase
from app.contracts import CapacityLimitReached


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    async def close(self):
        pass


class BackendPublicationContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_due_maps_backend_snake_case_delivery(self):
        database = BackendDatabase(FakeClient([{
            "id": 4, "publication_id": 9, "creator_telegram_id": 12,
            "target_key": "chat", "target_name": "Chat", "destination": "-100",
            "message_thread_id": 42, "text": "text", "entities": [],
            "rich_message": None, "media_paths": ["/app/data/a.jpg"],
            "attempts": 1, "event_enabled": True,
        }]))
        delivery = await database.claim_due()
        self.assertEqual(4, delivery.id)
        self.assertEqual(9, delivery.post_id)
        self.assertEqual(12, delivery.creator_id)
        self.assertEqual(42, delivery.message_thread_id)
        self.assertTrue(delivery.event_enabled)

    async def test_claim_due_handles_empty_queue(self):
        self.assertIsNone(await BackendDatabase(FakeClient([None])).claim_due())

    async def test_schedule_sends_utc_time_and_turns_capacity_into_domain_error(self):
        from app.backend import BackendError
        client = FakeClient([BackendError(409, "capacity_limit")])
        database = BackendDatabase(client)
        with self.assertRaises(CapacityLimitReached):
            await database.schedule(7, datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
        self.assertEqual("POST", client.calls[0][0])
        self.assertEqual("/internal/bot/v1/publications/7/schedule", client.calls[0][1])


if __name__ == "__main__":
    unittest.main()
