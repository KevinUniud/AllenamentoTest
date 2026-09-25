"""Runtime configuration helpers (environment-driven) and logging setup.

Keep this module intentionally small: it exposes a few runtime defaults and
a convenience `configure_logging()` to initialize module loggers uniformly.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from .constants import DEFAULT_PROLOG_DIR


def _integer_environment(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} deve essere un numero intero") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} deve essere compreso tra {minimum} e {maximum}")
    return value


def _log_level_environment(name: str = "LOG_LEVEL", default: str = "INFO") -> str:
    value = (os.getenv(name) or default).strip().upper()
    allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
    if value not in allowed:
        raise RuntimeError(f"{name} deve essere uno tra: {', '.join(sorted(allowed))}")
    return value


def _csv_environment(name: str, default: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, default).split(",") if value.strip())


def _cors_origins_environment(name: str, default: str) -> tuple[str, ...]:
    origins: list[str] = []
    for raw_origin in _csv_environment(name, default):
        if raw_origin == "*":
            raise RuntimeError(f"{name} non puo contenere wildcard")
        parsed = urlsplit(raw_origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"Origine CORS non valida in {name}: {raw_origin!r}")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise RuntimeError(f"Origine CORS non valida in {name}: {raw_origin!r}")
        normalized = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        if normalized not in origins:
            origins.append(normalized)
    if not origins:
        raise RuntimeError(f"{name} deve contenere almeno un'origine")
    return tuple(origins)


SWI_PROLOG_PATH: str = (os.getenv("SWI_PROLOG_PATH") or "swipl").strip()
"""Path or executable name used to run SWI-Prolog."""

DEFAULT_TIMEOUT: int = _integer_environment("DEFAULT_TIMEOUT", 10, minimum=1, maximum=120)
"""Default timeout (seconds) used by bridge/run operations."""

PROLOG_DIR: Path = Path(os.getenv("PROLOG_DIR", str(DEFAULT_PROLOG_DIR))).resolve()
"""Directory containing Prolog sources used by the bridge."""

LOG_LEVEL: str = _log_level_environment()
MAX_BATCH_SIZE: int = _integer_environment("MAX_BATCH_SIZE", 50, minimum=1, maximum=1_000)


CORS_ORIGINS: tuple[str, ...] = _cors_origins_environment(
    "CORS_ORIGINS",
    "http://localhost:12345,http://127.0.0.1:12345",
)


def configure_logging(level: int | str = LOG_LEVEL) -> None:
    """Configure basic logging for the application when invoked.

    This is intentionally minimal; callers (e.g. server) can call this once on
    startup to enable module loggers.
    """
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
