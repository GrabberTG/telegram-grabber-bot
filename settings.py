"""MyGrab Free configuration. Personal credentials are never distributed."""
import json
from pathlib import Path
import re
import sys


def app_root():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def load_config(path=None):
    path = Path(path) if path else app_root() / 'config.json'
    if not path.exists():
        raise ValueError('Copy config.example.json to config.json and fill it in. / Скопируйте config.example.json в config.json и заполните.')
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        raise ValueError('Invalid config.json / Ошибка формата config.json') from None
    if not isinstance(data, dict):
        raise ValueError('config.json must be an object / Нужен JSON-объект')
    defaults = dict(technical_channel_id=0, new_link='', new_username='', language='ru')
    for key, value in defaults.items():
        data.setdefault(key, value)
    errors = []
    for key in ['api_id', 'my_id']:
        if type(data.get(key)) is not int or data[key] <= 0:
            errors.append(key)
    if not re.fullmatch(r'[A-Fa-f0-9]{32}', str(data.get('api_hash', ''))):
        errors.append('api_hash')
    if not re.fullmatch(r'\d{5,}:[A-Za-z0-9_-]{30,}', str(data.get('bot_token', ''))):
        errors.append('bot_token')
    if type(data['technical_channel_id']) is not int or data['technical_channel_id'] > 0:
        errors.append('technical_channel_id')
    if not isinstance(data['new_link'], str) or (data['new_link'] and not re.fullmatch(r'https?://[^\s<>"\']+', data['new_link'])):
        errors.append('new_link')
    if not isinstance(data['new_username'], str) or (data['new_username'] and not re.fullmatch(r'@[A-Za-z0-9_]{3,32}', data['new_username'])):
        errors.append('new_username')
    if data['language'] not in {'ru', 'en'}:
        errors.append('language')
    if errors:
        raise ValueError('Fill or correct / Заполните или исправьте: ' + ', '.join(errors))
    return data
