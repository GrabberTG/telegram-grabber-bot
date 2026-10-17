# -*- coding: utf-8 -*-

"""
Simple HTML -> Telegram entity parser with button handling.
"""
from collections import deque
from html import escape
from html.parser import HTMLParser
from typing import Iterable, Tuple, List, Optional

from telethon.helpers import add_surrogate, del_surrogate, within_surrogate, strip_text
from telethon.tl import TLObject
from telethon.tl.types import (
    MessageEntityBold, MessageEntityItalic, MessageEntityCode,
    MessageEntityPre, MessageEntityTextUrl, MessageEntityMentionName,
    MessageEntityStrike, MessageEntityCustomEmoji, MessageEntitySpoiler,
    MessageEntityBlockquote, MessageEntityUnderline, TypeMessageEntity,
    MessageEntityEmail, MessageEntityUrl, Message, ReplyInlineMarkup,
    KeyboardButtonCallback, KeyboardButtonUrl
)


ENTITY_TO_FORMATTER = {
    MessageEntityBold: ('<strong>', '</strong>'),
    MessageEntityItalic: ('<em>', '</em>'),
    MessageEntityCode: ('<code>', '</code>'),
    MessageEntityUnderline: ('<u>', '</u>'),
    MessageEntityStrike: ('<del>', '</del>'),
    MessageEntitySpoiler: ('<spoiler>', '</spoiler>'),
    MessageEntityPre: lambda e, _: ("<pre><code class='language-{}'>".format(e.language), "</code></pre>"),
    MessageEntityEmail: lambda _, t: ('<a href="mailto:{}">'.format(t), '</a>'),
    MessageEntityUrl: lambda _, t: ('<a href="{}">'.format(t), '</a>'),
    MessageEntityTextUrl: lambda e, _: ('<a href="{}">'.format(escape(e.url)), '</a>'),
    MessageEntityMentionName: lambda e, _: ('<a href="tg://user?id={}">'.format(e.user_id), '</a>'),
    MessageEntityCustomEmoji: lambda e, _: ('<emoji id="{}">'.format(e.document_id), '</emoji>'),
    MessageEntityBlockquote: lambda e, _: ('<blockquote collapsed="{}">'.format(e.collapsed), '</blockquote>'),
}


class HTMLToTelegramParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = ''
        self.entities = []
        self._building_entities = {}
        self._open_tags = deque()
        self._open_tags_meta = deque()

    def handle_starttag(self, tag, attrs):
        self._open_tags.appendleft(tag)
        self._open_tags_meta.appendleft(None)

        attrs = dict(attrs)
        EntityType = None
        args = {}
        if tag == 'strong' or tag == 'b':
            EntityType = MessageEntityBold
        elif tag == 'em' or tag == 'i':
            EntityType = MessageEntityItalic
        elif tag == 'u':
            EntityType = MessageEntityUnderline
        elif tag == 'del' or tag == 's':
            EntityType = MessageEntityStrike
        elif tag == 'spoiler':
            EntityType = MessageEntitySpoiler
        elif tag == 'code':
            try:
                pre = self._building_entities['pre']
                try:
                    pre.language = attrs['class'][len('language-'):]
                except KeyError:
                    pass
            except KeyError:
                EntityType = MessageEntityCode
        elif tag == 'pre':
            EntityType = MessageEntityPre
            args['language'] = ''
        elif tag == 'a':
            try:
                url = attrs['href']
            except KeyError:
                return
            if url.startswith('mailto:'):
                url = url[len('mailto:'):]
                EntityType = MessageEntityEmail
            else:
                if self.get_starttag_text() == url:
                    EntityType = MessageEntityUrl
                else:
                    EntityType = MessageEntityTextUrl
                    args['url'] = del_surrogate(url)
                    url = None
            self._open_tags_meta.popleft()
            self._open_tags_meta.appendleft(url)
        elif tag == 'emoji':
            try:
                document_id = attrs['id']
            except KeyError:
                return
            EntityType = MessageEntityCustomEmoji
            args['document_id'] = int(del_surrogate(document_id))
        elif tag == 'blockquote':
            try:
                collapsed = attrs['collapsed']
            except KeyError:
                return
            EntityType = MessageEntityBlockquote
            args['collapsed'] = True if del_surrogate(collapsed) == "True" else False

        if EntityType and tag not in self._building_entities:
            self._building_entities[tag] = EntityType(
                offset=len(self.text),
                length=0,
                **args)

    def handle_data(self, text):
        previous_tag = self._open_tags[0] if len(self._open_tags) > 0 else ''
        if previous_tag == 'a':
            url = self._open_tags_meta[0]
            if url:
                text = url

        for tag, entity in self._building_entities.items():
            entity.length += len(text)

        self.text += text

    def handle_endtag(self, tag):
        try:
            self._open_tags.popleft()
            self._open_tags_meta.popleft()
        except IndexError:
            pass
        entity = self._building_entities.pop(tag, None)
        if entity:
            self.entities.append(entity)


class CustomHTML:
    def __init__(self):
        self.button_handler = TelegramButtonHandler()

    async def parse_message(self, client, message: Message) -> Tuple[str, List[TypeMessageEntity], Optional[ReplyInlineMarkup]]:
        text = message.text or ''
        entities = message.entities or []
        reply_markup = message.reply_markup if hasattr(message, 'reply_markup') and isinstance(message.reply_markup, ReplyInlineMarkup) else None
        return text, entities, reply_markup

    async def repost_message(self, client, message: Message, target_channel: str, processed_text: str = None) -> None:
        text, entities, reply_markup = await self.parse_message(client, message)
        text = processed_text if processed_text is not None else text

        buttons_info = self.button_handler.extract_buttons(message)
        print(f"Извлеченные кнопки: {buttons_info}")

        custom_markup = None
        if buttons_info:
            buttons = []
            for btn in buttons_info:
                if btn.get('url'):
                    buttons.append([KeyboardButtonUrl(text=btn['text'], url=btn['url'])])
                elif btn.get('callback_data'):
                    buttons.append([KeyboardButtonCallback(text=btn['text'], data=btn['callback_data'].encode('utf-8'))])
            if buttons:
                custom_markup = ReplyInlineMarkup(rows=buttons)
                print(f"Создана кастомная разметка: {custom_markup}")
            else:
                print("Кнопки не созданы, custom_markup остался None")

        print(f"Текст для отправки: {text}")
        print(f"Сущности для отправки: {entities}")
        print(f"Используемая разметка: {custom_markup}")

        if not text:
            print("Текст пустой, пропускаем отправку")
            return

        try:
            sent_message = await client.send_message(
                entity=target_channel,
                message=text,
                buttons=custom_markup  # Используем только custom_markup
            )
            print(f"Отправленное сообщение: {sent_message.text}, buttons: {sent_message.reply_markup}")
        except Exception as e:
            print(f"Ошибка при отправке сообщения: {e}")

    @staticmethod
    def parse(html: str) -> Tuple[str, List[TypeMessageEntity]]:
        if not html:
            return html, []

        parser = HTMLToTelegramParser()
        parser.feed(add_surrogate(html))
        text = strip_text(parser.text, parser.entities)
        parser.entities.reverse()
        parser.entities.sort(key=lambda entity: entity.offset)
        return del_surrogate(text), parser.entities

    @staticmethod
    def unparse(text: str, entities: Iterable[TypeMessageEntity]) -> str:
        if not text:
            return text
        elif not entities:
            return escape(text)

        if isinstance(entities, TLObject):
            entities = (entities,)

        text = add_surrogate(text)
        insert_at = []
        for i, entity in enumerate(entities):
            s = entity.offset
            e = entity.offset + entity.length
            delimiter = ENTITY_TO_FORMATTER.get(type(entity), None)
            if delimiter:
                if callable(delimiter):
                    delimiter = delimiter(entity, text[s:e])
                insert_at.append((s, i, delimiter[0]))
                insert_at.append((e, -i, delimiter[1]))

        insert_at.sort(key=lambda t: (t[0], t[1]))
        next_escape_bound = len(text)
        while insert_at:
            at, _, what = insert_at.pop()
            while within_surrogate(text, at):
                at += 1

            text = text[:at] + what + escape(text[at:next_escape_bound]) + text[next_escape_bound:]
            next_escape_bound = at

        text = escape(text[:next_escape_bound]) + text[next_escape_bound:]

        return del_surrogate(text)


class TelegramButtonHandler:
    @staticmethod
    def extract_buttons(message: Message) -> Optional[List[dict]]:
        if not hasattr(message, 'reply_markup') or not isinstance(message.reply_markup, ReplyInlineMarkup):
            return None

        buttons = []
        for row in message.reply_markup.rows:
            for button in row.buttons:
                if isinstance(button, KeyboardButtonCallback):
                    buttons.append({
                        'text': button.text,
                        'callback_data': button.data.decode('utf-8') if button.data else None,
                        'url': None
                    })
                elif isinstance(button, KeyboardButtonUrl):
                    buttons.append({
                        'text': button.text,
                        'callback_data': None,
                        'url': button.url
                    })
        return buttons
