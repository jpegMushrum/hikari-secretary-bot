from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from aiogram.types import InputRichMessage

from ..backend import BackendClient


@dataclass(frozen=True, slots=True)
class VocabularyItem:
    japanese: str
    reading: str
    translation: str


@dataclass(frozen=True, slots=True)
class GrammarPoint:
    pattern: str
    explanation: str
    example: str
    translation: str


@dataclass(frozen=True, slots=True)
class TopicGenerationOptions:
    jlpt_level: str
    admin_comment: str | None = None


@dataclass(frozen=True, slots=True)
class DailyTopic:
    title: str
    vocabulary_theme: str
    introduction: str
    questions: tuple[str, ...]
    vocabulary: tuple[VocabularyItem, ...]
    grammar: tuple[GrammarPoint, ...]
    jlpt_level: str = "N3"

    def as_json_value(self) -> dict:
        return asdict(self)


class DailyTopicRenderer:
    TELEGRAM_TEXT_LIMIT = 4096

    def render(self, topic: DailyTopic) -> str:
        self._validate(topic)
        lines = [f"🗣 Тема дня: {topic.title}", "", topic.introduction]
        lines.extend(("", "💬 Вопросы для обсуждения:"))
        lines.extend(f"• {question}" for question in topic.questions)
        lines.extend(("", "📚 Полезная лексика:"))
        lines.extend(
            f"• {item.japanese}（{item.reading}）— {item.translation}"
            for item in topic.vocabulary
        )
        lines.extend(("", "🧩 Грамматика:"))
        for item in topic.grammar:
            lines.extend((
                f"• {item.pattern} — {item.explanation}",
                f"  {item.example}",
                f"  {item.translation}",
            ))
        text = "\n".join(lines)
        if len(text) > self.TELEGRAM_TEXT_LIMIT:
            raise ValueError("Сгенерированная тема превышает лимит Telegram")
        return text

    def rich_message(self, topic: DailyTopic) -> dict:
        self._validate(topic)
        vocabulary = "\n".join(
            f"• {item.japanese}（{item.reading}）— {item.translation}"
            for item in topic.vocabulary
        )
        grammar_parts: list[str] = []
        for item in topic.grammar:
            grammar_parts.append(
                f"• {item.pattern} — {item.explanation}\n"
                f"  {item.example}\n"
                f"  {item.translation}"
            )
        value = {
            "blocks": [
                {"type": "heading", "text": "🗣 Тема дня", "size": 2},
                {
                    "type": "paragraph",
                    "text": f"{topic.title}\n\n{topic.introduction}",
                },
                {
                    "type": "heading",
                    "text": "💬 Вопросы на обсуждение",
                    "size": 2,
                },
                {
                    "type": "paragraph",
                    "text": "\n".join(
                        f"• {question}" for question in topic.questions
                    ),
                },
                {
                    "type": "details",
                    "summary": "📚 Полезная лексика",
                    "blocks": [{"type": "paragraph", "text": vocabulary}],
                    "is_open": False,
                },
                {
                    "type": "details",
                    "summary": "🧩 Полезная грамматика",
                    "blocks": [{
                        "type": "paragraph",
                        "text": "\n\n".join(grammar_parts),
                    }],
                    "is_open": False,
                },
            ]
        }
        return InputRichMessage.model_validate(value).model_dump(
            mode="json", exclude_none=True
        )

    @staticmethod
    def _validate(topic: DailyTopic) -> None:
        if topic.jlpt_level not in {"N5", "N4", "N3", "N2", "N1"}:
            raise ValueError("Некорректный уровень JLPT в сгенерированной теме")
        if not topic.title.strip() or len(topic.title) > 160:
            raise ValueError("Название темы должно содержать от 1 до 160 символов")
        if not topic.introduction.strip():
            raise ValueError("У темы должно быть вступление")
        if not topic.vocabulary_theme.strip() or len(topic.vocabulary_theme) > 160:
            raise ValueError("Тема лексики должна содержать от 1 до 160 символов")
        if not 1 <= len(topic.questions) <= 8:
            raise ValueError("Нужно от 1 до 8 вопросов")
        if any(not question.strip() for question in topic.questions):
            raise ValueError("Вопросы не должны быть пустыми")
        if not 1 <= len(topic.vocabulary) <= 20:
            raise ValueError("Нужно от 1 до 20 слов")
        if any(
            not value.strip()
            for item in topic.vocabulary
            for value in (item.japanese, item.reading, item.translation)
        ):
            raise ValueError("Поля словаря не должны быть пустыми")
        if not 1 <= len(topic.grammar) <= 8:
            raise ValueError("Нужно от 1 до 8 грамматических конструкций")
        if any(
            not value.strip()
            for item in topic.grammar
            for value in (
                item.pattern,
                item.explanation,
                item.example,
                item.translation,
            )
        ):
            raise ValueError("Поля грамматики не должны быть пустыми")


class DailyTopicService:
    """Thin Telegram adapter for learning-content operations owned by backend."""

    def __init__(
        self,
        client: BackendClient,
        renderer: DailyTopicRenderer | None = None,
    ):
        self.client = client
        self.renderer = renderer or DailyTopicRenderer()
        self.available = False

    async def refresh_capabilities(self) -> None:
        value = await self.client.request(
            "GET", "/internal/bot/v1/ai-topics/capabilities"
        )
        self.available = bool(value.get("enabled"))

    async def generate(
        self,
        options: TopicGenerationOptions | None = None,
        *,
        exclude_post_id: int | None = None,
    ) -> DailyTopic:
        payload = await self.client.request(
            "POST",
            "/internal/bot/v1/ai-topics/generate",
            json={
                "options": {
                    "jlpt_level": options.jlpt_level,
                    "admin_comment": options.admin_comment,
                } if options else None,
                "exclude_publication_id": exclude_post_id,
            },
        )
        topic = self._from_json(payload)
        self.renderer.render(topic)
        return topic

    async def schedule(
        self,
        topic: DailyTopic,
        *,
        creator_id: int,
        scheduled_at: datetime,
        idempotency_key: str,
    ) -> int:
        result = await self.client.request(
            "POST",
            "/internal/bot/v1/ai-topics/publications",
            json={
                "topic": topic.as_json_value(),
                "creator_id": creator_id,
                "scheduled_at": scheduled_at.isoformat(),
                "source_key": idempotency_key,
            },
        )
        return int(result["id"])

    async def replace_scheduled(self, post_id: int, topic: DailyTopic) -> bool:
        result = await self.client.request(
            "PUT",
            f"/internal/bot/v1/ai-topics/publications/{post_id}",
            json={"topic": topic.as_json_value()},
        )
        return bool(result["replaced"])

    @staticmethod
    def _from_json(value: dict) -> DailyTopic:
        return DailyTopic(
            title=value["title"],
            vocabulary_theme=value["vocabulary_theme"],
            introduction=value["introduction"],
            questions=tuple(value["questions"]),
            vocabulary=tuple(VocabularyItem(**item) for item in value["vocabulary"]),
            grammar=tuple(GrammarPoint(**item) for item in value["grammar"]),
            jlpt_level=value["jlpt_level"],
        )
