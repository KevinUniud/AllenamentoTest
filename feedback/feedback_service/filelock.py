"""Small Linux file locks used to coordinate feedback processes."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import IO


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[IO[bytes]]:
    """Hold an exclusive advisory lock on a user-owned file."""

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    stream = os.fdopen(descriptor, "r+b", buffering=0)
    try:
        os.fchmod(stream.fileno(), 0o600)
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield stream
    finally:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


class SingleInstanceLock:
    """Non-blocking process lifetime lock for the periodic worker."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._stream: IO[bytes] | None = None

    def acquire(self) -> bool:
        if self._stream is not None:
            return True
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        stream = os.fdopen(descriptor, "r+b", buffering=0)
        os.fchmod(stream.fileno(), 0o600)
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            stream.close()
            return False
        self._stream = stream
        return True

    def release(self) -> None:
        if self._stream is None:
            return
        fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        self._stream.close()
        self._stream = None

    def __enter__(self) -> SingleInstanceLock:
        if not self.acquire():
            raise RuntimeError("Un altro worker feedback e gia attivo")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        self.release()
