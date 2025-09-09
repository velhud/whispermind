import json
import os

DEFAULT_SETTINGS_FILE = 'settings.json'

REQUIRED_FIELDS = ['name', 'goal', 'style', 'length']


def validate_personal_info(personal_info: dict) -> None:
    for field in REQUIRED_FIELDS:
        if not personal_info.get(field):
            raise ValueError(f"Personal info field '{field}' cannot be empty")


def save_settings(settings: dict, filename: str = DEFAULT_SETTINGS_FILE) -> None:
    personal_info = settings.get('personal_info', {})
    validate_personal_info(personal_info)
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)


def load_settings(filename: str = DEFAULT_SETTINGS_FILE) -> dict:
    if not os.path.exists(filename):
        return {}
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)
