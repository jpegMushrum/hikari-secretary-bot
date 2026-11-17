import unittest
import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from app.keyboards import draft_keyboard
from app.formatting import rich_photos
from app.config import load_settings
from app.handlers.publications import PublicationHandlers
from aiogram.types import RichMessage


class MiniappHandoffTests(unittest.TestCase):
    def test_button_opens_exact_draft_and_keeps_fallback_callbacks(self):
        settings = SimpleNamespace(targets=(), miniapp_url="https://club.example")
        keyboard = draft_keyboard(42, set(), settings)
        buttons = [b for row in keyboard.inline_keyboard for b in row]
        self.assertEqual(buttons[0].web_app.url, "https://club.example/admin/publications/42")
        self.assertEqual([b.callback_data for b in buttons[1:]], ["event:42", "now:42", "schedule:42", "cancel:42"])

    def test_unconfigured_miniapp_keeps_existing_keyboard(self):
        keyboard = draft_keyboard(42, set(), SimpleNamespace(targets=()))
        self.assertFalse(any(b.web_app for row in keyboard.inline_keyboard for b in row))

    def test_photo_order_matches_nested_rich_blocks(self):
        small={"file_id":"small","width":10,"height":10}
        large={"file_id":"large","width":100,"height":100}
        other={"file_id":"other","width":50,"height":50}
        rich={"blocks":[{"type":"photo","photo":[small,large]},{"type":"list","items":[{"blocks":[{"type":"photo","photo":[other]}]}]}]}
        self.assertEqual([p["file_id"] for p in rich_photos(rich)],["large","other"])
        self.assertEqual(rich["blocks"][0]["photo"],[small,large])

    def test_invalid_miniapp_urls_fail_configuration(self):
        for value in ["http://localhost:5173", "https://club.example/app", "https://club.example/?token=x", "https://user:pass@club.example", "javascript:alert(1)"]:
            with self.subTest(value=value), patch.dict("os.environ", {"MINIAPP_URL":value}, clear=True):
                with self.assertRaisesRegex(ValueError,"MINIAPP_URL"):
                    load_settings()

    def test_preview_download_failure_does_not_break_bot_draft(self):
        rich=RichMessage.model_validate({"blocks":[{"type":"photo","photo":[{"file_id":"photo","file_unique_id":"unique","width":100,"height":100}]}]})
        message=SimpleNamespace(rich_message=rich,text=None,caption=None,entities=None,caption_entities=None,photo=[],from_user=SimpleNamespace(id=123),chat=SimpleNamespace(id=123))
        with tempfile.TemporaryDirectory() as directory:
            context=SimpleNamespace(settings=SimpleNamespace(media_dir=Path(directory)),bot=SimpleNamespace(download=AsyncMock(side_effect=RuntimeError("unavailable"))))
            service=SimpleNamespace(create_draft=AsyncMock(return_value=42))
            handler=PublicationHandlers(context,None,service)
            handler.show_draft=AsyncMock()
            asyncio.run(handler._create_draft([message]))
            self.assertEqual(service.create_draft.await_args.args[3],[])
            self.assertEqual(service.create_draft.await_args.args[4],rich.model_dump(mode="json",exclude_none=True))
            handler.show_draft.assert_awaited_once_with(123,42)
