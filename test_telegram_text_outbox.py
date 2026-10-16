import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from telegram.error import BadRequest, RetryAfter, TimedOut
from mobile import telegram_text_outbox as outbox
import monitor


class TelegramTextOutboxTests(unittest.TestCase):
    def setUp(self):
        warnings=patch.object(monitor,'_runtime_delivery_warnings',[])
        warnings.start();self.addCleanup(warnings.stop)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "queue.enc"
        self.patch = patch.object(outbox, "PATH", self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.env = patch.dict(os.environ, {"CONFIG_PASSPHRASE": "isolated-outbox-key", "TELEGRAM_BOT_TOKEN_BACKUP": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.bot = Mock(token="isolated-route-a")
        self.bot.send_photo = AsyncMock(return_value=Mock(message_id=123))
        self.bot.send_message = AsyncMock(return_value=Mock(message_id=124))

    def test_confirmed_photo_rate_limit_retries_text_after_restart_without_photo(self):
        self.bot.send_message.side_effect = RetryAfter(30)
        text = "<b>Изолированный тест</b>\n" + "😀" * 1200
        with patch.object(outbox.time, "time", return_value=1000):
            photo = asyncio.run(monitor.safe_send_telegram(self.bot, 42, text, img="https://example.invalid/photo.jpg"))
            self.assertEqual(123, photo.message_id)
            self.assertEqual(0, asyncio.run(outbox.flush(self.bot, 42)))
        restarted = Mock(token=self.bot.token)
        restarted.send_message = AsyncMock(return_value=Mock(message_id=125))
        with patch.object(outbox.time, "time", return_value=1031):
            self.assertEqual(1, asyncio.run(outbox.flush(restarted, 42)))
            self.assertEqual(0, asyncio.run(outbox.flush(restarted, 42)))
        self.bot.send_photo.assert_awaited_once()
        restarted.send_message.assert_awaited_once()
        self.assertEqual(123, restarted.send_message.await_args.kwargs["reply_to_message_id"])
        self.assertEqual(text, restarted.send_message.await_args.kwargs["text"])
        self.assertIsNone(outbox.warning())

    def test_network_timeout_is_held_without_duplicate_or_silent_success(self):
        outbox.enqueue(self.bot, 42, 123, "text")
        self.bot.send_message.side_effect = TimedOut()
        self.assertEqual(0, asyncio.run(outbox.flush(self.bot, 42)))
        self.assertEqual(0, asyncio.run(outbox.flush(self.bot, 42)))
        self.bot.send_message.assert_awaited_once()
        self.assertIn("1 требуют проверки", outbox.warning())

    def test_interrupted_sending_is_held_after_restart(self):
        identifier = outbox.enqueue(self.bot, 42, 123, "text")
        outbox._update(identifier, status="sending")
        self.assertEqual(0, asyncio.run(outbox.flush(self.bot, 42)))
        self.bot.send_message.assert_not_awaited()
        self.assertIn("1 требуют проверки", outbox.warning())

    def test_route_changes_cannot_send_old_text_to_other_bot_or_recipient(self):
        outbox.enqueue(self.bot, 42, 123, "private body")
        self.assertEqual(0, asyncio.run(outbox.flush(self.bot, 43)))
        other = Mock(token="other-sender", send_message=AsyncMock())
        self.assertEqual(0, asyncio.run(outbox.flush(other, 42)))
        self.assertEqual(1, asyncio.run(outbox.flush(self.bot, 42)))
        other.send_message.assert_not_awaited()

    def test_encryption_authenticated_and_contains_no_credentials_or_body(self):
        outbox.enqueue(self.bot, 42, 123, "private body")
        data = self.path.read_bytes()
        for value in (b"private body", b"isolated-route-a", b"isolated-outbox-key"):
            self.assertNotIn(value, data)
        self.path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        with self.assertRaises(ValueError):
            asyncio.run(outbox.flush(self.bot, 42))
        self.bot.send_message.assert_not_awaited()

    def test_oversized_chunks_resume_only_after_confirmed_last_chunk(self):
        text = '<b>😀' + "😀" * 5000 + '</b><a href="https://example.invalid/lot">Лот</a>'
        identifier = outbox.enqueue(self.bot, 42, 123, text)
        self.bot.send_message.side_effect = [Mock(message_id=124), RetryAfter(1)]
        with patch.object(outbox.time, "time", return_value=1000):
            self.assertEqual(1, asyncio.run(outbox.flush(self.bot, 42)))
        self.assertEqual(1, outbox._load()["entries"][identifier]["next"])
        self.bot.send_message.side_effect = None
        with patch.object(outbox.time, "time", return_value=1002):
            self.assertEqual(2, asyncio.run(outbox.flush(self.bot, 42)))
        calls = self.bot.send_message.await_args_list
        for call in calls:
            self.assertLessEqual(len(call.kwargs["text"].encode("utf-16-le")) // 2, 4096)
            self.assertIsNone(call.kwargs["parse_mode"])
        self.assertIn("https://example.invalid/lot", calls[-1].kwargs["text"])
        self.assertNotEqual(calls[0].kwargs["text"], calls[-1].kwargs["text"])
        self.assertEqual(calls[1].kwargs["text"], calls[2].kwargs["text"])

    def test_concurrent_flushes_claim_each_reply_once(self):
        outbox.enqueue(self.bot, 42, 123, "text")
        async def delayed(**kwargs):
            await asyncio.sleep(0)
            return Mock(message_id=124)
        self.bot.send_message.side_effect = delayed
        async def run():
            return await asyncio.gather(outbox.flush(self.bot, 42), outbox.flush(self.bot, 42))
        self.assertEqual(1, sum(asyncio.run(run())))
        self.bot.send_message.assert_awaited_once()

    def test_definite_bad_request_visible_and_does_not_loop(self):
        outbox.enqueue(self.bot, 42, 123, "text")
        self.bot.send_message.side_effect = BadRequest("photo deleted")
        self.assertEqual(0, asyncio.run(outbox.flush(self.bot, 42)))
        self.assertEqual(0, asyncio.run(outbox.flush(self.bot, 42)))
        self.bot.send_message.assert_awaited_once()
        self.assertIn("1 требуют проверки", outbox.warning())

    def test_unavailable_encrypted_storage_does_not_deliver_incomplete_photo(self):
        with patch.object(outbox, '_save', side_effect=OSError('disk unavailable')):
            result=asyncio.run(monitor.safe_send_telegram(self.bot,42,'😀'*1200,img='https://example.invalid/photo.jpg'))
        self.assertFalse(result)
        self.bot.send_photo.assert_not_awaited()
        self.bot.send_message.assert_not_awaited()
