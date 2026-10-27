"""Pesan dan tombol Telegram yang dipakai bersama oleh semua fitur."""
from dataclasses import dataclass, field
import json


def button(text, data):
    return {"text": text, "callback_data": data}


def navigation():
    return [[button("🏠 Menu", "menu"), button("➕ Catat", "add")]]


@dataclass
class Document:
    filename: str
    content: bytes
    caption: str
    mime_type: str = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


@dataclass
class Reply:
    text: str
    buttons: list = field(default_factory=navigation)
    document: Document | None = None
    clear_cutoff: int | None = None
    backup_request: bool = False

    @property
    def markup(self):
        return {"inline_keyboard": self.buttons}

    def to_json(self):
        return json.dumps({"text":self.text,"buttons":self.buttons,"clear_cutoff":self.clear_cutoff,
                           "backup_request":self.backup_request},
                          ensure_ascii=False)

    @classmethod
    def from_json(cls, value):
        return cls(**json.loads(value))
