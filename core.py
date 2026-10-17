"""MyGrab Free: routing, storage and copying. No advertising is added to posts."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
import json
import logging
from pathlib import Path
import re
import sqlite3

from addon import CustomHTML
from telethon.errors import FloodWaitError
from telethon.tl.types import MessageEntityCustomEmoji, MessageMediaWebPage

log = logging.getLogger('mygrab')


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS channel_roles(id INTEGER, kind TEXT, title TEXT, PRIMARY KEY(id,kind));
                CREATE TABLE IF NOT EXISTS routes(source INTEGER PRIMARY KEY, destination INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS processed(key TEXT PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS pending(id INTEGER PRIMARY KEY, source INTEGER NOT NULL,
                    destination INTEGER NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending');
                INSERT OR IGNORE INTO settings VALUES ('moderation', '0');
            ''')

    def db(self):
        return closing_connection(self.path)

    def add(self, identifier, title, kind):
        if kind not in {'source', 'destination'}:
            raise ValueError('Unknown channel kind')
        # One entity may be a source in one route and a destination in another.
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS channel_roles(id INTEGER, kind TEXT, title TEXT, PRIMARY KEY(id,kind))')
            db.execute('INSERT OR REPLACE INTO channel_roles VALUES(?,?,?)', (int(identifier), kind, title))

    def channels(self, kind):
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS channel_roles(id INTEGER, kind TEXT, title TEXT, PRIMARY KEY(id,kind))')
            return dict(db.execute('SELECT id,title FROM channel_roles WHERE kind=? ORDER BY id', (kind,)))

    def remove(self, identifier, kind):
        identifier = int(identifier)
        with self.db() as db:
            db.execute('DELETE FROM channel_roles WHERE id=? AND kind=?', (identifier, kind))
            column = 'source' if kind == 'source' else 'destination'
            db.execute(f'DELETE FROM routes WHERE {column}=?', (identifier,))
            db.execute(f"UPDATE pending SET status='cancelled' WHERE {column}=? AND status='pending'", (identifier,))

    def routes(self):
        with self.db() as db:
            return dict(db.execute('SELECT source,destination FROM routes ORDER BY source'))

    def route(self, source):
        with self.db() as db:
            row = db.execute('''SELECT r.destination FROM routes r
                JOIN channel_roles s ON s.id=r.source AND s.kind='source'
                JOIN channel_roles d ON d.id=r.destination AND d.kind='destination'
                WHERE r.source=?''', (source,)).fetchone()
        return row[0] if row else None

    def set_route(self, source, destination):
        source, destination = int(source), int(destination)
        if source not in self.channels('source') or destination not in self.channels('destination'):
            raise ValueError('Add both channels first / Сначала добавьте оба канала')
        graph = self.routes()
        graph[source] = destination
        current, visited = source, set()
        while current in graph:
            if current in visited:
                raise ValueError('Cyclic route / Циклическое соответствие запрещено')
            visited.add(current)
            current = graph[current]
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO routes VALUES(?,?)', (source, destination))
            db.execute("UPDATE pending SET status='cancelled' WHERE source=? AND destination<>? AND status='pending'", (source, destination))

    def clear_routes(self):
        with self.db() as db:
            db.execute('DELETE FROM routes')
            db.execute("UPDATE pending SET status='cancelled' WHERE status='pending'")

    @property
    def moderation(self):
        with self.db() as db:
            return db.execute("SELECT value FROM settings WHERE key='moderation'").fetchone()[0] == '1'

    @moderation.setter
    def moderation(self, value):
        with self.db() as db:
            db.execute("UPDATE settings SET value=? WHERE key='moderation'", ('1' if value else '0',))

    def claim(self, key):
        with self.db() as db:
            return bool(db.execute('INSERT OR IGNORE INTO processed(key) VALUES(?)', (key,)).rowcount)

    def release(self, key):
        with self.db() as db:
            db.execute('DELETE FROM processed WHERE key=?', (key,))

    def queue(self, source, destination, payload):
        with self.db() as db:
            return db.execute('INSERT INTO pending(source,destination,payload) VALUES(?,?,?)',
                              (source, destination, json.dumps(payload, ensure_ascii=False))).lastrowid

    def pending(self, identifier=None):
        with self.db() as db:
            rows = db.execute('SELECT id,source,destination,payload,status FROM pending' +
                              (' WHERE id=?' if identifier is not None else " WHERE status='pending' ORDER BY id DESC LIMIT 30"),
                              (identifier,) if identifier is not None else ()).fetchall()
        return [dict(id=r[0], source=r[1], destination=r[2], payload=json.loads(r[3]), status=r[4]) for r in rows]

    def pending_update(self, identifier, payload=None, status=None):
        with self.db() as db:
            if payload is not None:
                db.execute('UPDATE pending SET payload=? WHERE id=?', (json.dumps(payload, ensure_ascii=False), identifier))
            if status is not None:
                db.execute('UPDATE pending SET status=? WHERE id=?', (status, identifier))


class closing_connection:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.connection = sqlite3.connect(self.path, timeout=5)
        return self.connection

    def __exit__(self, kind, value, traceback):
        try:
            self.connection.rollback() if kind else self.connection.commit()
        finally:
            self.connection.close()


class ReplacementHTML(HTMLParser):
    def __init__(self, link, username):
        super().__init__(convert_charrefs=True)
        self.link, self.username, self.output = link, username, []

    def handle_starttag(self, tag, attrs):
        parts = []
        for key, value in attrs:
            if key == 'href' and value and self.link and re.match(r'^(https?://|t\.me/)', value, re.I):
                value = self.link
            parts.append(key if value is None else f'{key}="{escape(value, quote=True)}"')
        self.output.append('<' + tag + (' ' + ' '.join(parts) if parts else '') + '>')

    def handle_endtag(self, tag):
        self.output.append('</' + tag + '>')

    def handle_data(self, text):
        # Treat each URL atomically so mention replacement cannot alter a URL query.
        def replace(match):
            if match.group('url') is not None:
                url = match.group('url')
                clean = url.rstrip('.,!?;:')
                return self.link + url[len(clean):] if self.link else url
            return self.username or match.group(0)
        text = re.sub(r'''(?P<url>https?://[^\s<>"')]+|(?<![\w/])t\.me/[^\s<>"')]+)|(?P<mention>(?<![\w/])@[A-Za-z0-9_]{3,32}\b)''', replace, text)
        self.output.append(escape(text, quote=False))


def transform_html(text, link='', username=''):
    parser = ReplacementHTML(link, username)
    parser.feed(text or '')
    parser.close()
    return ''.join(parser.output)


def caption(messages, config):
    # Free keeps the Unicode fallback; animated/custom entities belong to Premium.
    return '\n'.join(transform_html(CustomHTML.unparse(m.message or '',
                                    [e for e in (m.entities or []) if not isinstance(e, MessageEntityCustomEmoji)]),
                                    config.get('new_link', ''), config.get('new_username', ''))
                     for m in messages if m.message)


def post_key(source, messages):
    first = messages[0]
    return f'{source}:album:{first.grouped_id}' if first.grouped_id else f'{source}:message:{first.id}'


class Engine:
    def __init__(self, store, client, config, started=None, sleep=asyncio.sleep):
        self.store, self.client, self.config = store, client, config
        self.started = started or datetime.now(timezone.utc)
        self.sleep = sleep
        self.destination_locks, self.pending_locks = {}, {}
        self.on_queued = None

    def live(self, messages):
        for message in messages:
            date = message.date
            if date is None or (date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date) <= self.started:
                return False
        return True

    async def send(self, destination, messages, text, source=None):
        lock = self.destination_locks.setdefault(destination, asyncio.Lock())
        async with lock:
            while True:
                try:
                    if source is not None and self.store.route(source) != destination:
                        return None
                    media = [m.media for m in messages if m.media and not isinstance(m.media, MessageMediaWebPage)]
                    if media:
                        return await self.client.send_file(destination, media if len(media) > 1 else media[0],
                                                           caption=text or None, parse_mode=CustomHTML())
                    if text.strip():
                        return await self.client.send_message(destination, text, parse_mode=CustomHTML(), link_preview=False)
                    return None
                except FloodWaitError as exc:
                    log.warning('Telegram wait: %s seconds, destination=%s', exc.seconds, destination)
                    await self.sleep(max(1, exc.seconds))

    async def handle(self, source, messages, live=True):
        messages = sorted((m for m in messages if m and not getattr(m, 'action', None)), key=lambda m: m.id)
        destination = self.store.route(source)
        if not messages or destination is None or (live and not self.live(messages)):
            return 'skipped'
        key = post_key(source, messages)
        if live and not self.store.claim(key):
            return 'duplicate'
        try:
            text = caption(messages, self.config)
            if self.store.route(source) != destination:
                return 'skipped'
            if self.store.moderation:
                payload = dict(ids=[m.id for m in messages], text=text, preview_ids=[])
                identifier = self.store.queue(source, destination, payload)
                if self.on_queued:
                    try:
                        await self.on_queued(identifier, messages, text)
                    except Exception:
                        log.exception('Preview failed; queued item %s is saved. Use /pending.', identifier)
                return 'queued'
            sent = await self.send(destination, messages, text, source=source)
            return 'sent' if sent is not None else 'skipped'
        except BaseException:
            if live:
                self.store.release(key)
            raise

    async def approve(self, identifier):
        lock = self.pending_locks.setdefault(identifier, asyncio.Lock())
        async with lock:
            rows = self.store.pending(identifier)
            if not rows or rows[0]['status'] != 'pending':
                return 'closed'
            item = rows[0]
            if self.store.route(item['source']) != item['destination']:
                self.store.pending_update(identifier, status='cancelled')
                return 'closed'
            messages = [m for m in await self.client.get_messages(item['source'], ids=item['payload']['ids']) if m]
            if len(messages) != len(item['payload']['ids']):
                raise ValueError('Source post no longer available / Исходный пост недоступен')
            text = item['payload']['text']
            previews = item['payload'].get('preview_ids', [])
            if previews:
                edited = await self.client.get_messages(self.config['technical_channel_id'], ids=previews)
                if edited and all(edited):
                    text = '\n'.join(CustomHTML.unparse(m.message or '', m.entities or []) for m in edited if m.message)
            # Editing a preview must not re-enable Premium entities in Free.
            clean, entities = CustomHTML.parse(text)
            text = CustomHTML.unparse(clean, [e for e in entities if not isinstance(e, MessageEntityCustomEmoji)])
            sent = await self.send(item['destination'], messages, text, source=item['source'])
            self.store.pending_update(identifier, status='sent' if sent is not None else 'empty')
            return 'sent' if sent is not None else 'skipped'

    async def reject(self, identifier):
        lock = self.pending_locks.setdefault(identifier, asyncio.Lock())
        async with lock:
            rows = self.store.pending(identifier)
            if not rows or rows[0]['status'] != 'pending':
                return 'closed'
            self.store.pending_update(identifier, status='rejected')
            return 'rejected'

    async def history(self, sources, limit, cancel=None, progress=None):
        if limit is not None and (type(limit) is not int or limit <= 0):
            raise ValueError('Count must be positive / Количество должно быть положительным')
        counts = dict(sent=0, queued=0, skipped=0, failed=0, cancelled=False)
        for source in sources:
            if self.store.route(source) is None:
                continue
            if limit is None:
                iterator = self.client.iter_messages(source, reverse=True)
            else:
                records = sorted(await self.client.get_messages(source, limit=limit), key=lambda m: m.id)
                # Complete boundary albums instead of sending one fragment.
                for boundary in list(records[:1] + records[-1:]):
                    if boundary.grouped_id:
                        extra = await self.client.get_messages(source, ids=list(range(max(1, boundary.id - 9), boundary.id + 10)))
                        records = sorted({m.id: m for m in records + [m for m in extra if m and m.grouped_id == boundary.grouped_id]}.values(), key=lambda m: m.id)
                async def local_iterator():
                    for item in records:
                        yield item
                iterator = local_iterator()
            group = []

            async def flush():
                if not group:
                    return
                try:
                    result = await self.handle(source, group, live=False)
                    counts[result if result in counts else 'skipped'] += 1
                except asyncio.CancelledError:
                    raise
                except Exception:
                    counts['failed'] += 1
                    log.exception('History post failed: source=%s id=%s', source, group[0].id)
                if progress:
                    await progress(counts)
                await self.sleep(1)

            async for item in iterator:
                if cancel and cancel.is_set():
                    counts['cancelled'] = True
                    return counts
                if getattr(item, 'action', None):
                    continue
                if group and (not item.grouped_id or item.grouped_id != group[0].grouped_id):
                    await flush()
                    group = []
                group.append(item)
                if not item.grouped_id:
                    await flush()
                    group = []
            await flush()
        return counts
