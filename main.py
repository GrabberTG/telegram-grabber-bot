"""MyGrab Free. Project: https://t.me/mygrab_tg | Premium: @every_manager.

Public free build. Advertising appears only in the management interface.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sys
import tempfile

from aiogram import Bot, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.exceptions import MessageNotModified
from telethon import TelegramClient, events, utils
from telethon.tl.types import Channel, Chat, PeerChannel

from core import Engine, Store
from i18n import COPY
from settings import app_root, load_config

VERSION = 'Free 2026.10.17'
CHANNEL_URL = 'https://t.me/mygrab_tg'
PREMIUM_URL = 'https://t.me/every_manager'
log = logging.getLogger('mygrab')


class ProcessLock:
    """Prevent concurrent runtime/authorization against the same local session."""
    def __enter__(self):
        self.handle = open(app_root() / '.mygrab.lock', 'a+b')
        self.handle.seek(0, 2)
        if not self.handle.tell():
            self.handle.write(b'0')
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise ValueError('Another instance is running / Другой экземпляр уже запущен') from None
        return self

    def __exit__(self, *args):
        try:
            self.handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()


class Application:
    def __init__(self, config, store, client, bot):
        self.config, self.store, self.client, self.bot = config, store, client, bot
        self.engine = Engine(store, client, config)
        self.engine.on_queued = self.preview
        self.waiting = None
        self.copy_task, self.cancel_copy = None, asyncio.Event()

    def tr(self, key, **values):
        return COPY[self.config['language']][key].format(**values)

    def owner(self, actor):
        return actor is not None and int(actor.id) == self.config['my_id']

    def keyboard(self):
        k = InlineKeyboardMarkup(row_width=2)
        for labels in [('source_add', 'destination_add'), ('sources', 'destinations'), ('route', 'routes')]:
            k.row(*[InlineKeyboardButton(self.tr(label), callback_data=label) for label in labels])
        k.add(InlineKeyboardButton(self.tr('mode', state=self.tr('on' if self.store.moderation else 'off')), callback_data='mode'))
        for name in ['pending', 'clear', 'cancel_button', 'help_button']:
            k.add(InlineKeyboardButton(self.tr(name), callback_data=name))
        k.row(InlineKeyboardButton(self.tr('premium'), url=PREMIUM_URL),
              InlineKeyboardButton('@mygrab_tg', url=CHANNEL_URL))
        return k

    async def reply(self, target, text, **kwargs):
        for start in range(0, max(1, len(text)), 3500):
            await target.answer(text[start:start + 3500], **(kwargs if start + 3500 >= len(text) else {}))

    async def resolve_channel(self, value):
        if not self.client.is_connected():
            raise ValueError(self.tr('offline'))
        value = value.strip()
        if re.fullmatch(r'\d+', value):
            value = PeerChannel(int(value))
        elif re.fullmatch(r'-\d+', value):
            value = int(value)
        entity = await self.client.get_entity(value)
        if not isinstance(entity, (Channel, Chat)):
            raise ValueError('Not a channel/group / Это не канал или группа')
        identifier = utils.get_peer_id(entity)
        if identifier == self.config['technical_channel_id']:
            raise ValueError('The moderation channel cannot be a route / Технический канал нельзя добавлять в маршруты')
        return identifier, entity.title

    async def add(self, message, kind, value):
        identifier, title = await self.resolve_channel(value)
        self.store.add(identifier, title, kind)
        await message.answer(self.tr('added', title=title, id=identifier), reply_markup=self.keyboard())

    async def list_channels(self, message, kind, page=0):
        items = list(self.store.channels(kind).items())
        page = max(0, int(page))
        selected = items[page * 10:(page + 1) * 10]
        k = InlineKeyboardMarkup(row_width=1)
        for identifier, title in selected:
            k.add(InlineKeyboardButton('❌ ' + title[:35] + ' ' + str(identifier), callback_data=f'delete:{kind}:{identifier}'))
        if page:
            k.add(InlineKeyboardButton('←', callback_data=f'list:{kind}:{page - 1}'))
        if len(items) > (page + 1) * 10:
            k.add(InlineKeyboardButton('→', callback_data=f'list:{kind}:{page + 1}'))
        k.add(InlineKeyboardButton(self.tr('home'), callback_data='home'))
        await message.answer('\n'.join(f'{identifier} — {title}' for identifier, title in selected) or self.tr('empty'), reply_markup=k)

    async def list_routes(self, message):
        routes = self.store.routes()
        await self.reply(message, '\n'.join(f'{source} → {target}' for source, target in routes.items()) or self.tr('empty'))

    async def show_pending(self, message):
        records = self.store.pending()
        if not records:
            await message.answer(self.tr('empty'))
        for record in records:
            await self.bot.send_message(message.chat.id, self.tr('pending_title', **record), reply_markup=self.pending_keyboard(record['id']))

    def pending_keyboard(self, identifier):
        return InlineKeyboardMarkup(row_width=2).row(
            InlineKeyboardButton(self.tr('approve'), callback_data=f'approve:{identifier}'),
            InlineKeyboardButton(self.tr('reject'), callback_data=f'reject:{identifier}'))

    async def preview(self, identifier, messages, text):
        rows = self.store.pending(identifier)
        if not rows or rows[0]['status'] != 'pending':
            return
        record = rows[0]
        technical = self.config['technical_channel_id']
        if technical:
            sent = await self.engine.send(technical, messages, text)
            sent = sent if isinstance(sent, (list, tuple)) else [sent]
            payload = record['payload']
            payload['preview_ids'] = [m.id for m in sent if m]
            self.store.pending_update(identifier, payload=payload)
        await self.bot.send_message(technical or self.config['my_id'], self.tr('pending_title', **record), reply_markup=self.pending_keyboard(identifier))

    async def on_message(self, message):
        if not self.owner(message.from_user):
            await message.answer(self.tr('denied'), disable_web_page_preview=True)
            return
        text = (message.text or '').strip()
        command, _, args = text.partition(' ')
        command = command.split('@', 1)[0].lower()
        try:
            if command == '/cancel':
                self.waiting = None
                await message.answer(self.tr('cancelled'), reply_markup=self.keyboard())
            elif command in {'/start', '/help'}:
                self.waiting = None
                await self.reply(message, self.tr('welcome' if command == '/start' else 'help'), reply_markup=self.keyboard(), disable_web_page_preview=True)
            elif command == '/add_channel':
                await self.add(message, 'source', args)
            elif command == '/add_destination_channel':
                await self.add(message, 'destination', args)
            elif command in {'/remove_channel', '/remove_destination_channel'}:
                kind = 'source' if command == '/remove_channel' else 'destination'
                self.store.remove(int(args), kind)
                await message.answer(self.tr('removed'))
            elif command in {'/list_channels', '/list_destination_channels'}:
                await self.list_channels(message, 'source' if command == '/list_channels' else 'destination')
            elif command in {'/set_channel_mapping', '/map'}:
                source, target = map(int, args.split())
                self.store.set_route(source, target)
                await message.answer(self.tr('saved'))
            elif command == '/show_mapping':
                await self.list_routes(message)
            elif command == '/pending':
                await self.show_pending(message)
            elif command == '/last_messages':
                await self.start_history(message, args)
            elif command == '/cancel_copy':
                self.cancel_copy.set()
                await message.answer(self.tr('copy_cancel'))
            elif self.waiting in {'source', 'destination'}:
                kind = self.waiting
                await self.add(message, kind, text)
                self.waiting = None
            elif self.waiting == 'route':
                source, target = map(int, text.split())
                self.store.set_route(source, target)
                self.waiting = None
                await message.answer(self.tr('saved'), reply_markup=self.keyboard())
            else:
                await message.answer(self.tr('title'), reply_markup=self.keyboard())
        except Exception as exc:
            log.exception('Management command failed')
            await message.answer(self.tr('error', error=safe_error(exc, self.config)))

    async def on_callback(self, callback):
        if not self.owner(callback.from_user):
            await callback.answer(self.tr('denied'), show_alert=True)
            return
        await callback.answer()
        data, message = callback.data or '', callback.message
        try:
            if data in {'home', 'help_button'}:
                self.waiting = None
                await self.reply(message, self.tr('help' if data == 'help_button' else 'title'), reply_markup=self.keyboard(), disable_web_page_preview=True)
            elif data in {'source_add', 'destination_add'}:
                self.waiting = 'source' if data == 'source_add' else 'destination'
                await message.answer(self.tr('ask_channel'))
            elif data in {'sources', 'destinations'}:
                await self.list_channels(message, 'source' if data == 'sources' else 'destination')
            elif data.startswith('list:'):
                _, kind, page = data.split(':')
                await self.list_channels(message, kind, int(page))
            elif data.startswith('delete:'):
                _, kind, identifier = data.split(':')
                self.store.remove(int(identifier), kind)
                await message.answer(self.tr('removed'))
            elif data == 'route':
                self.waiting = 'route'
                await message.answer(self.tr('ask_route'))
            elif data == 'routes':
                await self.list_routes(message)
            elif data == 'clear':
                k = InlineKeyboardMarkup().add(InlineKeyboardButton(self.tr('confirm_clear'), callback_data='clear_confirm'))
                await message.answer(self.tr('clear'), reply_markup=k)
            elif data == 'clear_confirm':
                self.store.clear_routes()
                await message.answer(self.tr('cleared'))
            elif data == 'mode':
                if not self.config['technical_channel_id']:
                    await message.answer(self.tr('need_tech'))
                    return
                self.store.moderation = not self.store.moderation
                await message.answer(self.tr('title'), reply_markup=self.keyboard())
            elif data == 'pending':
                await self.show_pending(message)
            elif data == 'cancel_button':
                self.cancel_copy.set()
                await message.answer(self.tr('copy_cancel'))
            elif data.startswith(('approve:', 'reject:')):
                action, identifier = data.split(':')
                result = await (self.engine.approve(int(identifier)) if action == 'approve' else self.engine.reject(int(identifier)))
                await message.answer(self.tr('pending_result', result=self.tr(result)))
                if result in {'sent', 'rejected', 'closed', 'skipped'}:
                    try:
                        await message.edit_reply_markup(reply_markup=None)
                    except MessageNotModified:
                        pass
        except Exception as exc:
            log.exception('Management button failed')
            await message.answer(self.tr('error', error=safe_error(exc, self.config)))

    async def start_history(self, message, args):
        if self.copy_task and not self.copy_task.done():
            await message.answer(self.tr('history_busy'))
            return
        parts = args.split()
        if len(parts) not in {1, 2}:
            await message.answer(self.tr('history_usage'))
            return
        try:
            limit = None if parts[-1].lower() == 'all' else int(parts[-1])
            sources = [int(parts[0])] if len(parts) == 2 else list(self.store.routes())
            if limit is not None and limit <= 0:
                raise ValueError
            if not sources or any(self.store.route(source) is None for source in sources):
                raise ValueError(self.tr('no_routes'))
        except ValueError:
            await message.answer(self.tr('history_usage') + '\n' + self.tr('no_routes'))
            return
        if not self.client.is_connected():
            await message.answer(self.tr('offline'))
            return
        self.cancel_copy = asyncio.Event()
        await message.answer(self.tr('history_started'))

        async def job():
            try:
                counts = await self.engine.history(sources, limit, cancel=self.cancel_copy)
                await message.answer(self.tr('history_done', **counts))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception('History job failed')
                try:
                    await message.answer(self.tr('error', error=safe_error(exc, self.config)))
                except Exception:
                    log.exception('Could not report history failure')
        self.copy_task = asyncio.create_task(job())

    async def on_new(self, event):
        if event.message.grouped_id:
            return
        try:
            await self.engine.handle(event.chat_id, [event.message])
        except Exception:
            log.exception('Live post failed: source=%s id=%s', event.chat_id, event.message.id)

    async def on_album(self, event):
        try:
            await self.engine.handle(event.chat_id, event.messages)
        except Exception:
            log.exception('Live album failed: source=%s', event.chat_id)


def safe_error(error, config):
    text = str(error)
    for key in ['bot_token', 'api_hash']:
        if config.get(key):
            text = text.replace(str(config[key]), '[redacted]')
    return text[:900]


def logging_setup(config):
    class Secrets(logging.Filter):
        def filter(self, record):
            record.msg, record.args = safe_error(record.getMessage(), config), ()
            return True
    handlers = [logging.StreamHandler(), RotatingFileHandler('mygrab.log', maxBytes=2_000_000, backupCount=2, encoding='utf-8')]
    for handler in handlers:
        handler.addFilter(Secrets())
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.basicConfig(level=logging.WARNING, handlers=handlers)
    log.setLevel(logging.INFO)


async def run(config):
    logging_setup(config)
    store = Store('mygrab_free.db')
    client = TelegramClient('MyGrab_Free', config['api_id'], config['api_hash'],
                            catch_up=False, connection_retries=3, retry_delay=3)
    bot = Bot(config['bot_token'], timeout=30)
    import socket
    bot._connector_init['family'] = socket.AF_INET
    dp = Dispatcher(bot)
    app = Application(config, store, client, bot)
    dp.register_message_handler(app.on_message, content_types=['text'])
    dp.register_callback_query_handler(app.on_callback)
    client.add_event_handler(app.on_new, events.NewMessage())
    client.add_event_handler(app.on_album, events.Album())

    async def account_loop():
        while True:
            try:
                await asyncio.wait_for(client.connect(), timeout=30)
                if not await client.is_user_authorized():
                    log.warning('Run authorization first / Сначала пройдите авторизацию через 2_authorize.bat')
                    await client.disconnect()
                    await asyncio.sleep(30)
                    continue
                await asyncio.wait_for(client.get_dialogs(), timeout=45)
                log.info('Telegram account connected; only new posts / Аккаунт подключён; только новые посты')
                await client.run_until_disconnected()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('Account connection failed; retry in 5 seconds')
            await asyncio.sleep(5)

    async def bot_loop():
        while True:
            try:
                await dp.start_polling(timeout=20)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('Bot API unavailable; retry in 5 seconds')
            await asyncio.sleep(5)

    tasks = [asyncio.create_task(account_loop()), asyncio.create_task(bot_loop())]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks + ([app.copy_task] if app.copy_task else []):
            task.cancel()
        await asyncio.gather(*tasks, *([app.copy_task] if app.copy_task else []), return_exceptions=True)
        await client.disconnect()
        await (await bot.get_session()).close()


async def authorize(config):
    client = TelegramClient('MyGrab_Free', config['api_id'], config['api_hash'], connection_retries=3)
    try:
        await client.start()
        print('Authorized. Start 3_start.bat / Авторизация выполнена. Запустите 3_start.bat.')
    finally:
        await client.disconnect()


def cli():
    parser = argparse.ArgumentParser(description='MyGrab Free — @mygrab_tg | Premium @every_manager')
    parser.add_argument('--authorize', action='store_true')
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--check-config', action='store_true')
    parser.add_argument('--version', action='store_true')
    args = parser.parse_args()
    if args.version:
        print(VERSION)
        return 0
    if args.self_check:
        import aiogram, telethon
        from telethon.sessions import MemorySession
        async def constructors():
            account = TelegramClient(MemorySession(), 12345, 'f' * 32)
            control_bot = Bot('123456789:' + 'A' * 35)
            try:
                await control_bot.get_session()
            finally:
                await account.disconnect()
                await (await control_bot.get_session()).close()
        asyncio.run(constructors())
        with tempfile.TemporaryDirectory(prefix='mygrab-check-') as folder:
            check = Store(Path(folder) / 'check.db')
            assert not check.routes() and not check.moderation
        print(json.dumps(dict(version=VERSION, aiogram=aiogram.__version__, telethon=telethon.__version__, sqlite='ok', imports='ok', constructors='ok')))
        return 0
    os.chdir(app_root())
    try:
        config = load_config()
        if args.check_config:
            print('Configuration OK / Настройки заполнены')
            return 0
        with ProcessLock():
            asyncio.run(authorize(config) if args.authorize else run(config))
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(safe_error(exc, locals().get('config', {})), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
