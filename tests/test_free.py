import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from telethon.errors import FloodWaitError
from telethon.tl.types import (Channel, ChatPhotoEmpty, MessageEntityBold, MessageEntityCustomEmoji,
                              MessageMediaWebPage, WebPageEmpty)
from core import Store, Engine, transform_html, caption
import main
from settings import load_config

A, B, X, Y = -1000000000001, -1000000000002, -1000000000101, -1000000000102
BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
CONFIG = dict(api_id=12345, api_hash='f' * 32, bot_token='123456789:' + 'A' * 35,
              my_id=111, technical_channel_id=-1000000000999, new_link='', new_username='', language='ru')


def post(identifier=1, text='Post', grouped=None, media=None, date=None, entities=None):
    return NS(id=identifier, message=text, entities=entities or [], grouped_id=grouped,
              media=media, date=date or BASE + timedelta(seconds=1), action=None)


def ui_message(text='/start', uid=111):
    return NS(text=text, from_user=NS(id=uid), chat=NS(id=uid), answer=AsyncMock(), edit_reply_markup=AsyncMock())


class FreeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.db'
        self.store = Store(self.path)
        for identifier, title, kind in [(A, 'A', 'source'), (B, 'B', 'source'), (X, 'X', 'destination'), (Y, 'Y', 'destination')]:
            self.store.add(identifier, title, kind)
        self.store.set_route(A, X)
        self.store.set_route(B, Y)
        self.data = {A: [], B: []}
        async def get(source, ids=None, limit=None, **kwargs):
            records = self.data.get(source, [])
            if ids is not None:
                return [next((m for m in records if m.id == i), None) for i in ids]
            return list(sorted(records, key=lambda m: m.id, reverse=True))[:limit]
        self.client = NS(get_messages=AsyncMock(side_effect=get),
                         send_message=AsyncMock(return_value=post()), send_file=AsyncMock(return_value=post()),
                         is_connected=lambda: True, get_entity=AsyncMock())
        self.sleep = AsyncMock()
        self.engine = Engine(self.store, self.client, dict(CONFIG), started=BASE, sleep=self.sleep)
        self.bot = NS(send_message=AsyncMock())
        self.app = main.Application(dict(CONFIG), self.store, self.client, self.bot)

    def tearDown(self):
        self.temp.cleanup()

    async def test_history_selected_source_only_uses_its_destination(self):
        self.data[A] = [post(text='Only A')]
        counts = await self.engine.history([A], 1)
        self.assertEqual(counts['sent'], 1)
        self.assertEqual([c.args[0] for c in self.client.send_message.await_args_list], [X])

    async def test_equal_message_ids_in_different_channels_are_preserved(self):
        self.data[A], self.data[B] = [post(text='Only A')], [post(text='Only B')]
        counts = await self.engine.history([A, B], 1)
        self.assertEqual(counts['sent'], 2)
        self.assertEqual([(c.args[0], c.args[1]) for c in self.client.send_message.await_args_list], [(X, 'Only A'), (Y, 'Only B')])

    async def test_albums_are_grouped_per_source_and_boundary_completed(self):
        self.data[A] = [post(1, 'Caption', grouped=50, media='p1'), post(2, '', grouped=50, media='p2')]
        counts = await self.engine.history([A], 1)
        self.assertEqual(counts['sent'], 1)
        self.client.send_file.assert_awaited_once()
        self.assertEqual(self.client.send_file.await_args.args, (X, ['p1', 'p2']))

    async def test_empty_history_reports_zero(self):
        result = await self.engine.history([A], 5)
        self.assertEqual((result['sent'], result['failed']), (0, 0))

    async def test_negative_and_zero_limits_rejected(self):
        for value in [-1, 0]:
            with self.assertRaises(ValueError):
                await self.engine.history([A], value)
        self.client.get_messages.assert_not_awaited()

    async def test_history_all_streams_chronologically(self):
        async def iterator(source, reverse):
            self.assertTrue(reverse)
            for i in [1, 2, 3]:
                yield post(i, str(i))
        self.client.iter_messages = iterator
        counts = await self.engine.history([A], None)
        self.assertEqual(counts['sent'], 3)
        self.assertEqual([c.args[1] for c in self.client.send_message.await_args_list], ['1', '2', '3'])

    async def test_all_history_can_be_cancelled(self):
        cancel = asyncio.Event()
        cancel.set()
        async def iterator(*args, **kwargs):
            yield post()
        self.client.iter_messages = iterator
        counts = await self.engine.history([A], None, cancel=cancel)
        self.assertTrue(counts['cancelled'])
        self.client.send_message.assert_not_awaited()

    async def test_removed_destination_stops_live_and_history(self):
        self.store.remove(X, 'destination')
        self.assertNotIn(A, self.store.routes())
        self.assertEqual(await self.engine.handle(A, [post()]), 'skipped')
        self.client.send_message.assert_not_awaited()

    async def test_removed_source_stops_live(self):
        self.store.remove(A, 'source')
        self.assertEqual(await self.engine.handle(A, [post()]), 'skipped')
        self.client.send_message.assert_not_awaited()

    async def test_added_route_is_effective_without_restarting_engine(self):
        self.store.clear_routes()
        self.assertEqual(await self.engine.handle(A, [post()]), 'skipped')
        self.store.set_route(A, X)
        self.assertEqual(await self.engine.handle(A, [post()]), 'sent')

    async def test_route_change_applies_to_new_posts(self):
        self.store.set_route(A, Y)
        await self.engine.handle(A, [post()])
        self.assertEqual(self.client.send_message.await_args.args[0], Y)

    async def test_no_self_route_or_multi_step_cycle(self):
        self.store.add(A, 'A', 'destination')
        self.store.add(X, 'X', 'source')
        with self.assertRaises(ValueError):
            self.store.set_route(A, A)
        with self.assertRaises(ValueError):
            self.store.set_route(X, A)

    async def test_start_boundary_old_equal_and_unknown_dates_skipped(self):
        for date in [BASE, BASE - timedelta(days=30)]:
            self.assertEqual(await self.engine.handle(A, [post(date=date)]), 'skipped')
        unknown = post()
        unknown.date = None
        self.assertEqual(await self.engine.handle(A, [unknown]), 'skipped')
        self.client.send_message.assert_not_awaited()

    async def test_same_event_and_concurrent_duplicate_send_once(self):
        result = await asyncio.gather(self.engine.handle(A, [post()]), self.engine.handle(A, [post()]))
        self.assertEqual(sorted(result), ['duplicate', 'sent'])
        self.client.send_message.assert_awaited_once()

    async def test_duplicate_guard_survives_restart(self):
        await self.engine.handle(A, [post()])
        restarted = Engine(Store(self.path), self.client, CONFIG, started=BASE)
        self.assertEqual(await restarted.handle(A, [post()]), 'duplicate')

    async def test_failed_send_does_not_claim_success(self):
        self.client.send_message.side_effect = RuntimeError('send failed')
        with self.assertRaises(RuntimeError):
            await self.engine.handle(A, [post()])
        self.client.send_message.side_effect = None
        self.assertEqual(await self.engine.handle(A, [post()]), 'sent')

    async def test_floodwait_retries_current_post_after_wait(self):
        self.client.send_message.side_effect = [FloodWaitError(None, capture=3), post()]
        self.assertEqual(await self.engine.handle(A, [post()]), 'sent')
        self.sleep.assert_awaited_once_with(3)
        self.assertEqual(self.client.send_message.await_count, 2)

    async def test_failed_history_post_does_not_stop_other_posts(self):
        self.data[A] = [post(1, 'A'), post(2, 'B')]
        self.client.send_message.side_effect = [RuntimeError('send failed'), post()]
        result = await self.engine.history([A], 2)
        self.assertEqual((result['sent'], result['failed']), (1, 1))

    async def test_media_without_caption_is_sent(self):
        self.assertEqual(await self.engine.handle(A, [post(text='', media='photo')]), 'sent')
        self.assertIsNone(self.client.send_file.await_args.kwargs['caption'])

    async def test_webpage_is_sent_as_text_not_media_file(self):
        await self.engine.handle(A, [post(text='https://example.org', media=MessageMediaWebPage(WebPageEmpty(1)))])
        self.client.send_message.assert_awaited_once()
        self.client.send_file.assert_not_awaited()

    async def test_non_owner_commands_and_callbacks_never_mutate(self):
        for command in ['/start', f'/remove_channel {A}', f'/set_channel_mapping {A} {Y}', '/last_messages 1']:
            await self.app.on_message(ui_message(command, uid=999))
        for data in ['clear_confirm', f'delete:source:{A}', 'mode', 'approve:1', 'reject:1', 'source_add']:
            cb = NS(data=data, from_user=NS(id=999), answer=AsyncMock(), message=ui_message(uid=999))
            await self.app.on_callback(cb)
            cb.answer.assert_awaited_once()
        self.assertEqual(self.store.routes(), {A: X, B: Y})
        self.assertFalse(self.store.moderation)
        self.assertIsNone(self.app.waiting)
        self.assertIsNone(self.app.copy_task)

    async def test_non_owner_cannot_use_owners_pending_input(self):
        self.app.waiting = 'source'
        await self.app.on_message(ui_message('@untrusted', uid=999))
        self.client.get_entity.assert_not_awaited()

    async def test_username_source_id_is_normalized(self):
        self.client.get_entity.return_value = Channel(id=123, title='Source', photo=ChatPhotoEmpty(), date=BASE)
        await self.app.on_message(ui_message('/add_channel @source'))
        self.assertIn(-1000000000123, self.store.channels('source'))
        self.assertNotIn(123, self.store.channels('source'))

    async def test_technical_channel_cannot_be_source_or_destination(self):
        channel_id = abs(CONFIG['technical_channel_id']) - 1_000_000_000_000
        self.client.get_entity.return_value = Channel(id=channel_id, title='Technical', photo=ChatPhotoEmpty(), date=BASE)
        with self.assertRaises(ValueError):
            await self.app.resolve_channel('@technical')

    async def test_moderation_state_and_pending_survive_restart(self):
        self.store.moderation = True
        await self.engine.handle(A, [post()])
        restarted = Store(self.path)
        self.assertTrue(restarted.moderation)
        self.assertEqual(len(restarted.pending()), 1)
        self.client.send_message.assert_not_awaited()

    async def test_double_approval_publishes_once(self):
        self.store.moderation = True
        item = post()
        self.data[A] = [item]
        await self.engine.handle(A, [item])
        identifier = self.store.pending()[0]['id']
        result = await asyncio.gather(self.engine.approve(identifier), self.engine.approve(identifier))
        self.assertEqual(sorted(result), ['closed', 'sent'])
        self.client.send_message.assert_awaited_once()

    async def test_rejected_post_cannot_be_published(self):
        self.store.moderation = True
        await self.engine.handle(A, [post()])
        identifier = self.store.pending()[0]['id']
        await self.engine.reject(identifier)
        self.assertEqual(await self.engine.approve(identifier), 'closed')
        self.client.send_message.assert_not_awaited()

    async def test_removed_route_cancels_pending_post(self):
        self.store.moderation = True
        await self.engine.handle(A, [post()])
        identifier = self.store.pending()[0]['id']
        self.store.clear_routes()
        self.assertEqual(await self.engine.approve(identifier), 'closed')

    async def test_preview_failure_keeps_pending_available(self):
        self.store.moderation = True
        self.engine.on_queued = AsyncMock(side_effect=RuntimeError('Bot API down'))
        self.assertEqual(await self.engine.handle(A, [post()]), 'queued')
        self.assertEqual(len(self.store.pending()), 1)

    async def test_edit_moderation_preview_updates_published_text(self):
        self.store.moderation = True
        self.data[A] = [post(text='Original')]
        await self.engine.handle(A, self.data[A])
        record = self.store.pending()[0]
        record['payload']['preview_ids'] = [90]
        self.store.pending_update(record['id'], payload=record['payload'])
        self.data[CONFIG['technical_channel_id']] = [post(90, 'Edited')]
        await self.engine.approve(record['id'])
        self.assertEqual(self.client.send_message.await_args.args[1], 'Edited')

    async def test_free_keeps_unicode_but_not_custom_emoji_entity(self):
        item = post(text='🙂 Bonus', entities=[MessageEntityCustomEmoji(0, 2, 123456789)])
        text = caption([item], CONFIG)
        self.assertEqual(text, '🙂 Bonus')
        self.assertNotIn('<emoji', text)

    async def test_owner_advertising_is_not_in_reposted_text(self):
        await self.engine.handle(A, [post(text='Original text')])
        self.assertEqual(self.client.send_message.await_args.args[1], 'Original text')
        welcome = ui_message('/start')
        await self.app.on_message(welcome)
        text = welcome.answer.await_args.args[0]
        self.assertIn('@mygrab_tg', text)
        self.assertIn('@every_manager', text)
        self.assertNotIn('my_grab', text)

    async def test_menu_and_texts_invite_github_star(self):
        from i18n import COPY
        for language in ['ru', 'en']:
            for key in ['welcome', 'help']:
                self.assertIn('github.com/GrabberTG/telegram-grabber-bot', COPY[language][key])
        buttons = [b for row in self.app.keyboard().inline_keyboard for b in row]
        self.assertIn(main.GITHUB_URL, [b.url for b in buttons])
        await self.engine.handle(A, [post(text='Plain')])
        self.assertNotIn('github', self.client.send_message.await_args.args[1])

    async def test_both_languages_have_identical_keys(self):
        from i18n import COPY
        self.assertEqual(COPY['en'].keys(), COPY['ru'].keys())
        self.app.config['language'] = 'en'
        message = ui_message('/help')
        await self.app.on_message(message)
        self.assertIn('MyGrab Free commands', message.answer.await_args.args[0])

    async def test_invalid_config_reports_keys_not_secrets(self):
        path = Path(self.temp.name) / 'config.json'
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'bot_token'):
            load_config(path)
        path.write_text(json.dumps(CONFIG))
        self.assertEqual(load_config(path)['my_id'], 111)

    async def test_plain_and_html_links_preserve_labels_and_query(self):
        text = '<a href="https://old.example?a=1&amp;b=2">Read</a> https://old.example?a=1&amp;b=2, t.me/old'
        self.assertEqual(transform_html(text, 'https://new.example?q=1&x=2'),
            '<a href="https://new.example?q=1&amp;x=2">Read</a> https://new.example?q=1&amp;x=2, https://new.example?q=1&amp;x=2')

    async def test_username_replacement_does_not_rewrite_email(self):
        self.assertEqual(transform_html('mail@example.org @source', username='@new_name'), 'mail@example.org @new_name')

    async def test_username_replacement_does_not_rewrite_url_parameters(self):
        self.assertEqual(transform_html('https://example.org/?user=@source @source', username='@new_name'),
                         'https://example.org/?user=@source @new_name')

    async def test_empty_replacement_config_keeps_original(self):
        self.assertEqual(transform_html('<b>Text</b> https://example.org @source'), '<b>Text</b> https://example.org @source')

    async def test_route_removed_while_send_waits_is_not_used(self):
        lock = self.engine.destination_locks.setdefault(X, asyncio.Lock())
        await lock.acquire()
        job = asyncio.create_task(self.engine.handle(A, [post()]))
        await asyncio.sleep(0)
        self.store.remove(X, 'destination')
        lock.release()
        self.assertEqual(await job, 'skipped')
        self.client.send_message.assert_not_awaited()

    async def test_rewrite_preview_does_not_restore_custom_emoji_in_free(self):
        self.store.moderation = True
        self.data[A] = [post()]
        await self.engine.handle(A, self.data[A])
        record = self.store.pending()[0]
        record['payload']['preview_ids'] = [90]
        self.store.pending_update(record['id'], payload=record['payload'])
        self.data[CONFIG['technical_channel_id']] = [post(90, '🙂', entities=[MessageEntityCustomEmoji(0, 2, 123456789)])]
        await self.engine.approve(record['id'])
        self.assertEqual(self.client.send_message.await_args.args[1], '🙂')

    async def test_bot_api_outage_does_not_stop_account_connection(self):
        connected = asyncio.Event()
        client = NS(connect=AsyncMock(), is_user_authorized=AsyncMock(return_value=True),
                    get_dialogs=AsyncMock(), disconnect=AsyncMock(), add_event_handler=Mock())
        async def stay_connected():
            connected.set()
            await asyncio.Event().wait()
        client.run_until_disconnected = stay_connected
        bot = NS(_connector_init={}, get_session=AsyncMock(return_value=NS(close=AsyncMock())))
        dispatcher = NS(register_message_handler=Mock(), register_callback_query_handler=Mock(),
                        start_polling=AsyncMock(side_effect=RuntimeError('Bot API down')))
        with patch.object(main, 'TelegramClient', return_value=client), patch.object(main, 'Bot', return_value=bot), \
             patch.object(main, 'Dispatcher', return_value=dispatcher), patch.object(main, 'Store', return_value=self.store), \
             patch.object(main, 'logging_setup'):
            task = asyncio.create_task(main.run(CONFIG))
            await asyncio.wait_for(connected.wait(), timeout=2)
            self.assertTrue(dispatcher.start_polling.called)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_account_outage_does_not_stop_bot_menu(self):
        polled = asyncio.Event()
        client = NS(connect=AsyncMock(side_effect=RuntimeError('Account offline')),
                    disconnect=AsyncMock(), add_event_handler=Mock())
        async def polling(**kwargs):
            polled.set()
            await asyncio.Event().wait()
        bot = NS(_connector_init={}, get_session=AsyncMock(return_value=NS(close=AsyncMock())))
        dispatcher = NS(register_message_handler=Mock(), register_callback_query_handler=Mock(), start_polling=polling)
        with patch.object(main, 'TelegramClient', return_value=client), patch.object(main, 'Bot', return_value=bot), \
             patch.object(main, 'Dispatcher', return_value=dispatcher), patch.object(main, 'Store', return_value=self.store), \
             patch.object(main, 'logging_setup'):
            task = asyncio.create_task(main.run(CONFIG))
            await asyncio.wait_for(polled.wait(), timeout=2)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_local_addon_code_block_is_not_corrupted(self):
        from addon import CustomHTML
        text, entities = CustomHTML.parse('<pre><code class="language-python">print(1)</code></pre>')
        decoded, _ = CustomHTML.parse(CustomHTML.unparse(text, entities))
        self.assertEqual(decoded, 'print(1)')


if __name__ == '__main__':
    unittest.main()
