"""Local, bounded virtual-paper storage configuration (no files opened here)."""

from pathlib import Path, PureWindowsPath
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PaperPersistenceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='PAPER_PERSISTENCE_', frozen=True,
        extra='forbid', allow_inf_nan=False, validate_default=True, revalidate_instances='always')

    enabled: Annotated[bool, Field(strict=True)] = True
    path: Path = Path('./data/paper_runtime.sqlite3')
    checkpoint_history: Annotated[int, Field(strict=True, ge=1, le=256)] = 32
    event_history: Annotated[int, Field(strict=True, ge=1, le=100000)] = 5000
    busy_timeout_ms: Annotated[int, Field(strict=True, ge=1, le=60000)] = 5000
    resume_policy: Literal['strict'] = 'strict'

    @field_validator('enabled', mode='before')
    @classmethod
    def boolean(cls, value: object) -> object:
        return value.lower() == 'true' if isinstance(value, str) and value.lower() in ('true', 'false') else value

    @field_validator('checkpoint_history', 'event_history', 'busy_timeout_ms', mode='before')
    @classmethod
    def integer(cls, value: object) -> object:
        return int(value) if isinstance(value, str) and value.isascii() and value.isdecimal() else value

    @field_validator('path', mode='before')
    @classmethod
    def local_file(cls, value: object) -> Path:
        if not isinstance(value, (str, Path)):
            raise ValueError('persistence path must be a local file')
        text = str(value)
        windows = PureWindowsPath(text)
        if (not text.strip() or any(ord(c) < 32 for c in text) or '://' in text
                or text.startswith(('file:', ':', '~', '\\\\', '//'))
                or windows.drive.startswith('\\\\') or '..' in windows.parts):
            raise ValueError('persistence path must be a local file without traversal or URI')
        path = Path(value)
        if path.suffix.lower() not in ('.sqlite3', '.sqlite', '.db') or path.is_dir():
            raise ValueError('persistence path must name a SQLite file')
        return path
