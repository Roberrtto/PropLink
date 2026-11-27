"""Encryption of personal data at rest.

Phone numbers and names are stored encrypted (Fernet: AES-128-CBC + HMAC-SHA256). Because encrypted
values can't be searched, phone numbers also get a "blind index": a keyed hash used only for lookups.

Key rotation: put the new key first in FIELD_ENCRYPTION_KEY, keeping the old ones after it
(comma-separated). New data is encrypted with the first key; old data still decrypts.
"""
import hashlib, hmac
from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator
import config
import re

_fernet = MultiFernet([Fernet(k.strip().encode()) for k in config.FIELD_ENCRYPTION_KEY.split(",") if k.strip()])
_index_key = config.BLIND_INDEX_KEY.encode()


def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()


def blind_index(value: str) -> str:
    return hmac.new(_index_key, value.encode(), hashlib.sha256).hexdigest()


def hash_secret(value: str) -> str:
    """Keyed hash for short-lived secrets such as one-time codes (never stored in plain text)."""
    return hmac.new(_index_key, b"otp:" + value.encode(), hashlib.sha256).hexdigest()


class EncryptedString(TypeDecorator):
    """A text column that is encrypted before it reaches the database and decrypted when read."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt(str(value))

    def process_result_value(self, value, dialect):
        return None if value is None else decrypt(value)

def clean_id(raw: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper())


def id_index(raw: str) -> str:
    return blind_index("id:" + clean_id(raw))


def norm_name(raw: str) -> str:
    return " ".join((raw or "").casefold().split())