"""Validation and generation of request correlation identifiers."""

from __future__ import annotations

import re
from uuid import uuid4

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def normalize_request_id(candidate: object) -> str:
    """Return a safe caller-provided ID or generate a fresh one."""
    value = str(candidate or "").strip()
    if _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return uuid4().hex
