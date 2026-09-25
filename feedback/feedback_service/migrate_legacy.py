"""Explicit migration of legacy per-receipt JSON files into SQLite.

Nothing imports legacy data during normal service startup. Run this module as a
separate operator action, preferably with ``--dry-run`` first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from feedback_service.config import load_settings
from feedback_service.schemas import FeedbackReport
from feedback_service.storage import (
    FeedbackPayloadError,
    FeedbackQuotaExceededError,
    FeedbackStorageError,
    FeedbackStore,
    IdempotencyConflictError,
)

LOGGER = logging.getLogger(__name__)


def _invalid_json_constant(value: str) -> None:
    raise ValueError(f"Costante JSON non valida: {value}")


@dataclass(frozen=True, slots=True)
class MigrationSummary:
    scanned_files: int = 0
    valid_files: int = 0
    imported_receipts: int = 0
    duplicate_receipts: int = 0
    invalid_files: int = 0
    conflicting_files: int = 0
    quota_rejected_files: int = 0
    expired_files: int = 0
    future_dated_files: int = 0
    purged_receipts: int = 0
    dry_run: bool = False


def _legacy_id(filename: str) -> str:
    """Preserve canonical UUIDv4 names and map other names deterministically."""

    stem = Path(filename).stem
    try:
        parsed = UUID(stem)
    except ValueError:
        parsed = None
    if parsed is not None and parsed.version == 4 and str(parsed) == stem:
        return str(parsed)

    digest = bytearray(
        hashlib.sha256(f"testlogica-feedback-legacy:{filename}".encode()).digest()[:16]
    )
    digest[6] = (digest[6] & 0x0F) | 0x40
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(digest)))


def _read_valid_report(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        payload = json.load(stream, parse_constant=_invalid_json_constant)
    if not isinstance(payload, dict):
        raise ValueError("La radice JSON non e un oggetto")
    FeedbackReport.model_validate(payload)
    return payload


def _legacy_created_at(path: Path, payload: dict[str, Any], *, now: float) -> float:
    """Prefer the report timestamp, falling back to a bounded file mtime."""

    initial = payload.get("Initial Data")
    raw = initial.get("Tempo inizio esercitazione") if isinstance(initial, dict) else None
    timestamp: float | None = None
    if isinstance(raw, str) and raw.strip():
        for pattern in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                timestamp = datetime.strptime(raw.strip(), pattern).replace(tzinfo=UTC).timestamp()
                break
            except ValueError:
                continue
    if timestamp is None:
        timestamp = path.stat().st_mtime
    if timestamp > now + 300:
        raise ValueError("La ricevuta legacy ha una data futura")
    return timestamp


def migrate_legacy_directory(
    source_directory: Path,
    store: FeedbackStore,
    *,
    dry_run: bool = False,
) -> MigrationSummary:
    """Validate and optionally import direct ``*.json`` children.

    Symlinks and nested directories are intentionally ignored. The source files
    are never modified or removed. A dry run does not initialise or write the
    destination database.
    """

    source = source_directory.resolve()
    if not source.is_dir():
        raise ValueError("La sorgente legacy non e una directory")
    paths = sorted(
        path
        for path in source.glob("*.json")
        if path.is_file() and not path.is_symlink()
    )
    now = time.time()
    cutoff = now - (store.retention_days * 86_400)
    valid: list[tuple[Path, dict[str, Any], float]] = []
    invalid_files = 0
    future_dated_files = 0
    expired_files = 0
    for path in paths:
        try:
            payload = _read_valid_report(path)
        except (OSError, UnicodeError, ValueError, RecursionError, ValidationError):
            invalid_files += 1
            LOGGER.warning("File legacy feedback non valido ignorato: %s", path.name)
            continue
        try:
            created_at = _legacy_created_at(path, payload, now=now)
        except (OSError, ValueError) as exc:
            invalid_files += 1
            if "data futura" in str(exc):
                future_dated_files += 1
            LOGGER.warning("File legacy feedback non valido ignorato: %s", path.name)
            continue
        if created_at < cutoff:
            expired_files += 1
        else:
            valid.append((path, payload, created_at))

    if dry_run:
        return MigrationSummary(
            scanned_files=len(paths),
            valid_files=len(valid) + expired_files,
            invalid_files=invalid_files,
            expired_files=expired_files,
            future_dated_files=future_dated_files,
            dry_run=True,
        )

    purged = store.initialize()
    imported = 0
    duplicates = 0
    conflicts = 0
    quota_rejected = 0
    for path, payload, created_at in valid:
        try:
            receipt = store.save(
                payload,
                _legacy_id(path.name),
                created_at=created_at,
            )
            purged += receipt.purged_receipts
            if receipt.created:
                imported += 1
            else:
                duplicates += 1
        except IdempotencyConflictError as exc:
            purged += exc.purged_receipts
            conflicts += 1
            LOGGER.warning("Conflitto durante la migrazione legacy: %s", path.name)
        except FeedbackQuotaExceededError as exc:
            purged += exc.purged_receipts
            quota_rejected += 1
            LOGGER.warning("Quota raggiunta durante la migrazione legacy: %s", path.name)
        except FeedbackPayloadError as exc:
            purged += getattr(exc, "purged_receipts", 0)
            invalid_files += 1
            LOGGER.warning("File legacy non importabile %s: %s", path.name, exc)
        except (FeedbackStorageError, OSError):
            raise
    purged += store.purge_expired()

    return MigrationSummary(
        scanned_files=len(paths),
        valid_files=len(valid) + expired_files,
        imported_receipts=imported,
        duplicate_receipts=duplicates,
        invalid_files=invalid_files,
        conflicting_files=conflicts,
        quota_rejected_files=quota_rejected,
        expired_files=expired_files,
        future_dated_files=future_dated_files,
        purged_receipts=purged,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migra esplicitamente ricevute JSON legacy nel database feedback SQLite."
    )
    parser.add_argument("source_directory", type=Path)
    parser.add_argument("--storage-dir", type=Path)
    parser.add_argument("--retention-days", type=int)
    parser.add_argument("--max-receipts", type=int)
    parser.add_argument("--max-storage-bytes", type=int)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    settings = load_settings()
    try:
        store = FeedbackStore(
            arguments.storage_dir or settings.storage_dir,
            retention_days=(
                settings.retention_days
                if arguments.retention_days is None
                else arguments.retention_days
            ),
            max_receipts=(
                settings.max_receipts
                if arguments.max_receipts is None
                else arguments.max_receipts
            ),
            max_storage_bytes=(
                settings.max_storage_bytes
                if arguments.max_storage_bytes is None
                else arguments.max_storage_bytes
            ),
            min_free_bytes=settings.min_free_bytes,
        )
        summary = migrate_legacy_directory(
            arguments.source_directory,
            store,
            dry_run=arguments.dry_run,
        )
    except (OSError, ValueError, FeedbackStorageError) as exc:
        LOGGER.error("Migrazione feedback non avviata: %s", exc)
        return 2
    print(json.dumps(asdict(summary), ensure_ascii=False, sort_keys=True))
    failures = (
        summary.invalid_files
        + summary.conflicting_files
        + summary.quota_rejected_files
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
