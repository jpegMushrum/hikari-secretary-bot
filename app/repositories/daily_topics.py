from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..backend import BackendClient
from ..services.daily_topics import TopicGenerationOptions, TopicHistoryItem


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _language_values(topic: dict, collection: str, field: str) -> tuple[str, ...]:
    values = topic.get(collection, [])
    return tuple(value for item in values if isinstance(item, dict) and isinstance((value := item.get(field)), str) and (value := value.strip())) if isinstance(values, list) else ()


@dataclass(frozen=True, slots=True)
class DailyTopicJob:
    id: int
    scheduled_for: datetime
    attempts: int
    prompt_version: str | None


class DailyTopicRepository:
    """Durable AI queue accessed exclusively through the private backend API."""

    def __init__(self, client: BackendClient): self.client = client

    async def enqueue(self, scheduled_for: datetime, prompt_version: str, *, available_at: datetime | None = None) -> int:
        data = await self.client.request("POST", "/internal/bot/v1/ai-topics/jobs", json={"scheduled_for": scheduled_for.astimezone(timezone.utc).isoformat(), "available_at": (available_at or scheduled_for).astimezone(timezone.utc).isoformat(), "prompt_version": prompt_version})
        return int(data["id"])

    async def preferences(self) -> TopicGenerationOptions:
        data = await self.client.request("GET", "/internal/bot/v1/ai-topics/preferences")
        return TopicGenerationOptions(data["jlpt_level"], data.get("admin_comment"))

    async def save_preferences(self, options: TopicGenerationOptions, updated_by: int) -> None:
        await self.client.request("PUT", "/internal/bot/v1/ai-topics/preferences", json={"jlpt_level": options.jlpt_level, "admin_comment": options.admin_comment, "updated_by": updated_by})

    async def claim_due(self, now: datetime | None = None) -> DailyTopicJob | None:
        data = await self.client.request("POST", "/internal/bot/v1/ai-topics/jobs/claim")
        if data is None: return None
        return DailyTopicJob(int(data["id"]), datetime.fromisoformat(data["scheduled_for"]), int(data["attempts"]), data.get("prompt_version"))

    async def mark_scheduled(self, job_id: int, post_id: int, topic: dict) -> None:
        await self.client.request("POST", f"/internal/bot/v1/ai-topics/jobs/{job_id}/scheduled", json={"publication_id": post_id, "topic": topic})

    async def mark_failed(self, job_id: int, error: str, *, retry_at: datetime | None) -> None:
        await self.client.request("POST", f"/internal/bot/v1/ai-topics/jobs/{job_id}/failed", json={"error": error[:1000], "retry_at": retry_at.astimezone(timezone.utc).isoformat() if retry_at else None})

    async def recent_history(self, limit: int | None = None, *, exclude_post_id: int | None = None) -> list[TopicHistoryItem]:
        items = await self.client.request("GET", "/internal/bot/v1/ai-topics/history")
        history=[]
        for topic in items[:limit] if limit else items:
            if not isinstance(topic,dict): continue
            title=str(topic.get("title","")).strip(); theme=str(topic.get("vocabulary_theme","")).strip()
            if title and theme: history.append(TopicHistoryItem(title,theme,_language_values(topic,"grammar","pattern"),_language_values(topic,"vocabulary","japanese")))
        return history

    async def replace_topic_for_post(self, post_id: int, topic: dict) -> bool:
        return bool((await self.client.request("POST", f"/internal/bot/v1/ai-topics/history/{post_id}", json={"topic":topic}))["replaced"])

    async def record_manual_publication(self, post_id: int, topic: dict, prompt_version: str = "admin-v1") -> int:
        return post_id
