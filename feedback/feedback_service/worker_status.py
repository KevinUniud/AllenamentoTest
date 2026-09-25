"""Private heartbeat exchanged between the worker and the HTTP process."""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

WorkerState = Literal["starting", "idle", "publishing", "retention", "error"]


@dataclass(frozen=True, slots=True)
class WorkerStatus:
    schema_version: int
    state: WorkerState
    updated_at: float
    last_publication_at: float | None = None
    last_publication_action: str | None = None
    last_retention_at: float | None = None
    last_error_at: float | None = None


class WorkerStatusStore:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    def write(self, status: WorkerStatus) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix=".worker-status-",
            suffix=".tmp",
            dir=self.path.parent,
        )
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(asdict(status), stream, separators=(",", ":"), sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            self._sync_directory()
        finally:
            temporary.unlink(missing_ok=True)

    def read(self) -> WorkerStatus | None:
        if not self.path.is_file() or self.path.is_symlink():
            return None
        try:
            raw = json.loads(self.path.read_bytes())
            status = WorkerStatus(**raw)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if (
            not isinstance(status.schema_version, int)
            or isinstance(status.schema_version, bool)
            or status.schema_version != 1
            or status.state not in {
                "starting",
                "idle",
                "publishing",
                "retention",
                "error",
            }
            or not self._valid_timestamp(status.updated_at)
            or not self._valid_optional_timestamp(status.last_publication_at)
            or not self._valid_optional_timestamp(status.last_retention_at)
            or not self._valid_optional_timestamp(status.last_error_at)
            or (
                status.last_publication_action is not None
                and status.last_publication_action
                not in {"published", "unchanged", "insufficient"}
            )
        ):
            return None
        return status

    def is_fresh(self, *, maximum_age_seconds: int, now: float | None = None) -> bool:
        status = self.read()
        if (
            status is None
            or status.state in {"starting", "error"}
            or status.last_error_at is not None
        ):
            return False
        current = time.time() if now is None else now
        age = current - status.updated_at
        return -5 <= age <= maximum_age_seconds

    def remove(self) -> None:
        """Remove a process lease without following a replacement symlink."""

        try:
            if self.path.is_symlink():
                return
            self.path.unlink(missing_ok=True)
            self._sync_directory()
        except FileNotFoundError:
            return

    @staticmethod
    def _valid_timestamp(value: object) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )

    @classmethod
    def _valid_optional_timestamp(cls, value: object) -> bool:
        return value is None or cls._valid_timestamp(value)

    def _sync_directory(self) -> None:
        descriptor = os.open(
            self.path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
