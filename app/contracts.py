from __future__ import annotations

from dataclasses import dataclass

EVENT_REGISTRATION_SORTS = frozenset({"name", "pass", "registered_at"})
PERSON_STATISTICS_SORTS = frozenset({"name", "visits", "last_visit"})


class CapacityLimitReached(RuntimeError):
    def __init__(self, limit: int, subject: str):
        self.limit = limit
        self.subject = subject
        super().__init__(f"Превышен лимит: не более {limit} {subject}")


@dataclass(slots=True)
class Delivery:
    id: int
    post_id: int
    creator_id: int
    target_key: str
    target_name: str
    destination: str
    message_thread_id: int | None
    text: str
    entities: list[dict]
    rich_message: dict | None
    media_paths: list[str]
    attempts: int
    event_enabled: bool = False


@dataclass(slots=True)
class Page:
    items: list[dict]
    page: int
    page_size: int
    total: int

    @property
    def pages(self) -> int:
        return max(1, (self.total + self.page_size - 1) // self.page_size)
