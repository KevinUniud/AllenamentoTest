"""Private SQLite storage for feedback receipts.

The browser payload is stored as JSON and decoded without model-driven
normalisation. SQLite transactions make an ``Idempotency-Key`` safe across
threads and across multiple service processes sharing the same database.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sqlite3
import stat
import struct
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from feedback_service.filelock import exclusive_file_lock

DATABASE_FILENAME = "feedback.sqlite3"
SCHEMA_VERSION = 3
DEFAULT_MAX_RECEIPTS = 100_000
DEFAULT_MAX_STORAGE_BYTES = 1_073_741_824
DEFAULT_MIN_FREE_BYTES = 67_108_864
_SQLITE_APPLICATION_ID = 0x544C4642  # "TLFB"
_COMPACTION_MARKER_FILENAME = ".compaction-required"
_COMPACTION_LOCK_FILENAME = ".compaction.lock"
_MAX_DATASET_REVISION = (1 << 63) - 1
_DATASET_DIGEST_DOMAIN = b"testlogica-feedback-dataset-v1\0"
_SOURCE_TOKEN_DOMAIN = b"testlogica-feedback-source-token-v1\0"


def _invalid_json_constant(value: str) -> None:
    raise ValueError(f"Costante JSON non valida: {value}")


@dataclass(frozen=True, slots=True)
class FeedbackReceipt:
    receipt_id: UUID
    # Kept for compatibility with the existing HTTP response. It is a logical
    # receipt name: SQLite does not create a JSON file with this name.
    filename: str
    purged_receipts: int = 0
    created: bool = True


@dataclass(frozen=True, slots=True)
class FeedbackStorageStatistics:
    receipt_count: int
    byte_count: int


@dataclass(frozen=True, slots=True)
class FeedbackDatasetSnapshot:
    """One consistent dataset plus an opaque identity for chart publication."""

    payloads: list[dict[str, Any]]
    revision: int
    digest: str
    source_token: str


@dataclass(frozen=True, slots=True)
class _DatasetState:
    dataset_id: UUID
    revision: int
    digest: str | None


class FeedbackSaveError(Exception):
    """A save failed after a possible retention purge."""

    def __init__(self, message: str, *, purged_receipts: int) -> None:
        super().__init__(message)
        self.purged_receipts = purged_receipts


class IdempotencyConflictError(FeedbackSaveError):
    """The same receipt id was previously used for a different report."""


class FeedbackPayloadError(FeedbackSaveError):
    """The parsed payload or idempotency key cannot be persisted safely."""


class FeedbackStorageError(FeedbackSaveError):
    """The private receipt store failed while writing or reading a receipt."""


class FeedbackQuotaExceededError(FeedbackStorageError):
    """A configured logical receipt or payload-byte quota was reached."""

    def __init__(
        self,
        message: str,
        *,
        purged_receipts: int,
        quota: Literal["receipts", "bytes", "disk", "free"],
        limit: int,
        current: int,
        attempted: int,
    ) -> None:
        super().__init__(message, purged_receipts=purged_receipts)
        self.quota = quota
        self.limit = limit
        self.current = current
        self.attempted = attempted


class FeedbackStore:
    def __init__(
        self,
        directory: Path,
        *,
        retention_days: int,
        max_receipts: int = DEFAULT_MAX_RECEIPTS,
        max_storage_bytes: int = DEFAULT_MAX_STORAGE_BYTES,
        min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    ) -> None:
        if retention_days < 1:
            raise ValueError("retention_days deve essere almeno 1")
        if max_receipts < 1:
            raise ValueError("max_receipts deve essere almeno 1")
        if max_storage_bytes < 1:
            raise ValueError("max_storage_bytes deve essere almeno 1")
        if min_free_bytes < 0:
            raise ValueError("min_free_bytes non puo essere negativo")
        self.directory = directory.resolve()
        self.database_path = self.directory / DATABASE_FILENAME
        self.retention_days = retention_days
        self.max_receipts = max_receipts
        self.max_storage_bytes = max_storage_bytes
        self.min_free_bytes = min_free_bytes
        self.compaction_marker_path = self.directory / _COMPACTION_MARKER_FILENAME
        self.compaction_lock_path = self.directory / _COMPACTION_LOCK_FILENAME
        self._lock = threading.RLock()
        self._integrity_signature: tuple[tuple[int, int], ...] | None = None

    def initialize(self) -> int:
        with self._lock:
            try:
                self._initialize_locked()
                return self._purge_expired_locked(time.time())
            except (OSError, sqlite3.Error) as exc:
                raise FeedbackStorageError(
                    "Archivio feedback non inizializzabile",
                    purged_receipts=0,
                ) from exc

    def save(
        self,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        *,
        created_at: float | None = None,
    ) -> FeedbackReceipt:
        """Persist the original parsed JSON object without a Pydantic dump.

        ``created_at`` exists for the explicit legacy migration command. HTTP
        submissions leave it unset and always receive the service clock time.
        """

        with self._lock:
            purged = 0
            try:
                self._initialize_locked()
                purged = self._purge_expired_locked(time.time())
                receipt_id = self._receipt_id(idempotency_key)
                encoded = self._encode_payload(payload, purged_receipts=purged)
                timestamp = time.time() if created_at is None else created_at
                if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
                    raise FeedbackPayloadError(
                        "Data della ricevuta non valida",
                        purged_receipts=purged,
                    )

                connection = self._connect()
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    existing = connection.execute(
                        """
                        SELECT payload_json, payload_sha256
                        FROM receipts
                        WHERE receipt_id = ?
                        """,
                        (str(receipt_id),),
                    ).fetchone()
                    if existing is not None:
                        existing_payload = bytes(existing[0])
                        if hashlib.sha256(existing_payload).hexdigest() != existing[1]:
                            connection.rollback()
                            raise FeedbackStorageError(
                                "Ricevuta idempotente esistente corrotta",
                                purged_receipts=purged,
                            )
                        try:
                            existing_object = json.loads(
                                existing_payload,
                                parse_constant=_invalid_json_constant,
                            )
                        except (UnicodeError, ValueError, RecursionError) as exc:
                            connection.rollback()
                            raise FeedbackStorageError(
                                "Ricevuta idempotente esistente illeggibile",
                                purged_receipts=purged,
                            ) from exc
                        # Match the original file store's logical JSON equality:
                        # key order and alternate JSON number spelling do not
                        # turn a safe retry into an idempotency conflict.
                        if existing_object != payload:
                            connection.rollback()
                            raise IdempotencyConflictError(
                                "Idempotency-Key gia usata con un payload diverso",
                                purged_receipts=purged,
                            )
                        connection.commit()
                        return FeedbackReceipt(
                            receipt_id=receipt_id,
                            filename=f"{receipt_id}.json",
                            purged_receipts=purged,
                            created=False,
                        )

                    statistics = self._statistics_from_connection(connection)
                    if statistics.receipt_count >= self.max_receipts:
                        connection.rollback()
                        raise FeedbackQuotaExceededError(
                            "Numero massimo di ricevute feedback raggiunto",
                            purged_receipts=purged,
                            quota="receipts",
                            limit=self.max_receipts,
                            current=statistics.receipt_count,
                            attempted=1,
                        )
                    if statistics.byte_count + len(encoded) > self.max_storage_bytes:
                        connection.rollback()
                        raise FeedbackQuotaExceededError(
                            "Spazio logico massimo per i feedback raggiunto",
                            purged_receipts=purged,
                            quota="bytes",
                            limit=self.max_storage_bytes,
                            current=statistics.byte_count,
                            attempted=len(encoded),
                        )
                    attempted_physical_bytes = self._estimated_insert_physical_bytes(
                        connection,
                        len(encoded),
                    )
                    physical_bytes = self._chargeable_physical_database_bytes(connection)
                    if physical_bytes + attempted_physical_bytes > self.max_storage_bytes:
                        connection.rollback()
                        raise FeedbackQuotaExceededError(
                            "Dimensione fisica massima del database feedback raggiunta",
                            purged_receipts=purged,
                            quota="disk",
                            limit=self.max_storage_bytes,
                            current=physical_bytes,
                            attempted=attempted_physical_bytes,
                        )
                    free_bytes = shutil.disk_usage(self.directory).free
                    if free_bytes - attempted_physical_bytes < self.min_free_bytes:
                        connection.rollback()
                        raise FeedbackQuotaExceededError(
                            "Spazio libero minimo per i feedback non disponibile",
                            purged_receipts=purged,
                            quota="free",
                            limit=self.min_free_bytes,
                            current=free_bytes,
                            attempted=attempted_physical_bytes,
                        )

                    connection.execute(
                        """
                        INSERT INTO receipts (
                            receipt_id,
                            payload_json,
                            payload_sha256,
                            byte_count,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            str(receipt_id),
                            encoded,
                            hashlib.sha256(encoded).hexdigest(),
                            len(encoded),
                            float(timestamp),
                        ),
                    )
                    self._record_dataset_mutation(connection)
                    connection.commit()
                except FeedbackSaveError:
                    raise
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()
                    self._secure_database_files()

                if self._integrity_signature is not None:
                    self._integrity_signature = self._storage_signature()
                return FeedbackReceipt(
                    receipt_id=receipt_id,
                    filename=f"{receipt_id}.json",
                    purged_receipts=purged,
                )
            except FeedbackSaveError:
                raise
            except (UnicodeError, ValueError, RecursionError) as exc:
                raise FeedbackPayloadError(
                    "Payload feedback non serializzabile",
                    purged_receipts=purged,
                ) from exc
            except (OSError, sqlite3.Error) as exc:
                raise FeedbackStorageError(
                    "Archivio feedback non disponibile",
                    purged_receipts=purged,
                ) from exc

    @staticmethod
    def _receipt_id(idempotency_key: str | None) -> UUID:
        if idempotency_key is None:
            return uuid4()
        try:
            receipt_id = UUID(idempotency_key)
        except (AttributeError, ValueError) as exc:
            raise ValueError("Idempotency-Key non valida") from exc
        if receipt_id.version != 4 or str(receipt_id) != idempotency_key:
            raise ValueError("Idempotency-Key non valida")
        return receipt_id

    @staticmethod
    def _encode_payload(payload: dict[str, Any], *, purged_receipts: int) -> bytes:
        if not isinstance(payload, dict):
            raise FeedbackPayloadError(
                "La radice del payload deve essere un oggetto JSON",
                purged_receipts=purged_receipts,
            )
        try:
            return json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, UnicodeError, ValueError, RecursionError) as exc:
            raise FeedbackPayloadError(
                "Payload feedback non serializzabile",
                purged_receipts=purged_receipts,
            ) from exc

    def snapshot_payloads(self) -> list[dict[str, Any]]:
        """Return one consistent, integrity-checked decoded snapshot."""

        return self.snapshot_dataset().payloads

    def snapshot_dataset(self) -> FeedbackDatasetSnapshot:
        """Read rows and persistent dataset state from one SQLite snapshot.

        Mutations invalidate the stored digest in their own transaction. This
        method repairs that cache only if the revision is still unchanged after
        the read transaction, so an API write never gets labelled with an older
        digest and a crash can only leave a safely recoverable ``NULL`` digest.
        """

        with self._lock:
            try:
                self._initialize_locked()
                connection = self._connect()
                try:
                    connection.execute("BEGIN")
                    state = self._dataset_state_from_connection(connection)
                    rows = connection.execute(
                        """
                        SELECT
                            receipt_id,
                            payload_json,
                            payload_sha256,
                            byte_count,
                            created_at
                        FROM receipts
                        ORDER BY created_at, receipt_id
                        """
                    ).fetchall()
                    payloads, calculated_digest = self._decode_dataset_rows(rows)
                    if state.digest is not None and state.digest != calculated_digest:
                        raise sqlite3.DatabaseError("Digest persistente del dataset incoerente")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()

                if state.digest is None:
                    self._persist_dataset_digest_if_current(state, calculated_digest)
                self._integrity_signature = self._storage_signature()
                return FeedbackDatasetSnapshot(
                    payloads=payloads,
                    revision=state.revision,
                    digest=calculated_digest,
                    source_token=self._source_token(state, calculated_digest),
                )
            except FeedbackSaveError:
                raise
            except (
                OSError,
                sqlite3.Error,
                UnicodeError,
                ValueError,
                RecursionError,
            ) as exc:
                raise FeedbackStorageError(
                    "Archivio feedback non disponibile",
                    purged_receipts=0,
                ) from exc

    def purge_expired(self, *, now: float | None = None) -> int:
        with self._lock:
            try:
                self._initialize_locked()
                return self._purge_expired_locked(time.time() if now is None else now)
            except (OSError, sqlite3.Error) as exc:
                raise FeedbackStorageError(
                    "Retention feedback non eseguibile",
                    purged_receipts=0,
                ) from exc

    def statistics(self) -> FeedbackStorageStatistics:
        with self._lock:
            try:
                self._initialize_locked()
                connection = self._connect()
                try:
                    return self._statistics_from_connection(connection)
                finally:
                    connection.close()
            except (OSError, sqlite3.Error) as exc:
                raise FeedbackStorageError(
                    "Statistiche feedback non disponibili",
                    purged_receipts=0,
                ) from exc

    def oldest_created_at(self) -> float | None:
        """Return the oldest retained receipt timestamp for worker scheduling."""

        with self._lock:
            try:
                self._initialize_locked()
                connection = self._connect()
                try:
                    row = connection.execute("SELECT MIN(created_at) FROM receipts").fetchone()
                finally:
                    connection.close()
                if row is None or row[0] is None:
                    return None
                value = float(row[0])
                return value if math.isfinite(value) else None
            except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
                raise FeedbackStorageError(
                    "Data delle ricevute feedback non disponibile",
                    purged_receipts=0,
                ) from exc

    def stats(self) -> FeedbackStorageStatistics:
        """Short alias useful to metrics collectors."""

        return self.statistics()

    def observe_statistics(self) -> FeedbackStorageStatistics:
        """Read statistics without creating, migrating or purging the store."""

        if not self.database_path.is_file() or self.database_path.is_symlink():
            return FeedbackStorageStatistics(receipt_count=0, byte_count=0)
        try:
            connection = sqlite3.connect(
                f"{self.database_path.as_uri()}?mode=ro",
                uri=True,
                timeout=1.0,
                isolation_level=None,
            )
            try:
                self._validate_schema(connection)
                return self._statistics_from_connection(connection)
            finally:
                connection.close()
        except (OSError, sqlite3.Error) as exc:
            raise FeedbackStorageError(
                "Statistiche feedback non disponibili",
                purged_receipts=0,
            ) from exc

    def backup_to(self, destination: Path) -> Path:
        """Create one consistent user-owned SQLite backup without stopping writes.

        Existing destinations are never overwritten. The SQLite backup API
        includes committed WAL content and therefore avoids copying a database
        file that is only partially checkpointed.
        """

        raw_target = destination.expanduser()
        if raw_target.exists() or raw_target.is_symlink():
            raise FileExistsError(f"Il backup esiste gia: {raw_target}")
        target = raw_target.resolve()
        if target == self.database_path:
            raise ValueError("Il backup non puo coincidere con il database attivo")
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Il backup esiste gia: {target}")

        with self._lock:
            temporary: Path | None = None
            source: sqlite3.Connection | None = None
            backup: sqlite3.Connection | None = None
            try:
                self._initialize_locked()
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                descriptor, name = tempfile.mkstemp(
                    prefix=f".{target.name}-",
                    suffix=".tmp",
                    dir=target.parent,
                )
                os.fchmod(descriptor, 0o600)
                os.close(descriptor)
                temporary = Path(name)

                source = self._connect()
                backup = sqlite3.connect(temporary)
                source.backup(backup)
                journal_mode = backup.execute("PRAGMA journal_mode=DELETE").fetchone()
                if journal_mode is None or str(journal_mode[0]).lower() != "delete":
                    raise sqlite3.OperationalError("Journal del backup non consolidabile")
                self._validate_schema(backup)
                self._validate_payload_integrity(backup)
                self._synchronize_dataset_digest(backup)
                backup.commit()
                integrity = backup.execute("PRAGMA quick_check(1)").fetchone()
                if integrity is None or integrity[0] != "ok":
                    raise sqlite3.DatabaseError("Backup SQLite non integro")

                cutoff = time.time() - (self.retention_days * 86_400)
                backup.execute("PRAGMA secure_delete=ON")
                cursor = backup.execute(
                    "DELETE FROM receipts WHERE created_at < ?",
                    (cutoff,),
                )
                if cursor.rowcount > 0:
                    self._record_dataset_mutation(backup)
                self._synchronize_dataset_digest(backup)
                backup.commit()
                backup.execute("VACUUM")
                self._validate_schema(backup)
                self._validate_payload_integrity(backup)
                integrity = backup.execute("PRAGMA quick_check(1)").fetchone()
                if integrity is None or integrity[0] != "ok":
                    raise sqlite3.DatabaseError("Backup SQLite non integro")
                backup.close()
                backup = None
                source.close()
                source = None

                descriptor = os.open(temporary, os.O_RDONLY)
                try:
                    os.fchmod(descriptor, 0o600)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                os.link(temporary, target, follow_symlinks=False)
                temporary.unlink()
                temporary = None
                self._sync_directory(target.parent)
                return target
            except FileExistsError:
                raise
            except (OSError, sqlite3.Error) as exc:
                raise FeedbackStorageError(
                    "Backup feedback non riuscito",
                    purged_receipts=0,
                ) from exc
            finally:
                if backup is not None:
                    backup.close()
                if source is not None:
                    source.close()
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    def compact(self) -> None:
        """Checkpoint and compact free SQLite pages after a retention purge."""

        with self._lock:
            try:
                with exclusive_file_lock(self.compaction_lock_path):
                    self._initialize_locked()
                    connection = self._connect()
                    try:
                        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        connection.execute("VACUUM")
                    finally:
                        connection.close()
                    self._secure_database_files()
                    self.compaction_marker_path.unlink(missing_ok=True)
                    self._sync_directory(self.directory)
            except (OSError, sqlite3.Error) as exc:
                raise FeedbackStorageError(
                    "Compattazione feedback non riuscita",
                    purged_receipts=0,
                ) from exc

    def compaction_required(self) -> bool:
        """Return whether a committed purge still requires physical compaction."""

        with self._lock:
            try:
                information = self.compaction_marker_path.stat(follow_symlinks=False)
            except FileNotFoundError:
                return False
            if not stat.S_ISREG(information.st_mode):
                raise FeedbackStorageError(
                    "Indicatore di compattazione feedback non valido",
                    purged_receipts=0,
                )
            return True

    def _mark_compaction_required(self) -> None:
        with exclusive_file_lock(self.compaction_lock_path):
            flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
            flags |= getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self.compaction_marker_path, flags, 0o600)
            try:
                os.fchmod(descriptor, 0o600)
                os.write(descriptor, f"{time.time_ns()}\n".encode("ascii"))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._sync_directory(self.directory)

    def restore_from(self, source: Path) -> Path:
        """Restore a verified backup only when no active database exists."""

        raw_source = source.expanduser()
        if raw_source.is_symlink():
            raise ValueError("Il backup non puo essere un collegamento simbolico")
        backup_path = raw_source.resolve(strict=True)
        if not backup_path.is_file():
            raise ValueError("Il backup non e un file regolare")

        with self._lock:
            temporary: Path | None = None
            source_connection: sqlite3.Connection | None = None
            restored: sqlite3.Connection | None = None
            try:
                self._ensure_directory()
                if any(
                    path.exists() or path.is_symlink()
                    for path in (
                        self.database_path,
                        Path(f"{self.database_path}-wal"),
                        Path(f"{self.database_path}-shm"),
                    )
                ):
                    raise FileExistsError(
                        "Il database attivo esiste: arrestare i servizi e spostarlo prima del restore"
                    )
                backup_size = backup_path.stat().st_size
                self._require_restore_free_space(backup_size)

                descriptor, name = tempfile.mkstemp(
                    prefix=".feedback-restore-",
                    suffix=".tmp",
                    dir=self.directory,
                )
                os.fchmod(descriptor, 0o600)
                os.close(descriptor)
                temporary = Path(name)
                source_connection = sqlite3.connect(
                    f"{backup_path.as_uri()}?mode=ro",
                    uri=True,
                    timeout=5.0,
                    isolation_level=None,
                )
                restored = sqlite3.connect(temporary)
                source_connection.backup(restored)
                journal_mode = restored.execute("PRAGMA journal_mode=DELETE").fetchone()
                if journal_mode is None or str(journal_mode[0]).lower() != "delete":
                    raise sqlite3.OperationalError("Journal del restore non consolidabile")
                restored.execute("PRAGMA secure_delete=ON")
                self._validate_schema(restored)
                self._validate_payload_integrity(restored)
                self._synchronize_dataset_digest(restored)
                restored.commit()
                integrity = restored.execute("PRAGMA quick_check(1)").fetchone()
                if integrity is None or integrity[0] != "ok":
                    raise sqlite3.DatabaseError("Backup SQLite non integro")

                cutoff = time.time() - (self.retention_days * 86_400)
                restored.execute("BEGIN IMMEDIATE")
                restored.execute("DELETE FROM receipts WHERE created_at < ?", (cutoff,))
                # Every restore is a new dataset instance. Rotating this private
                # identity prevents a pre-existing chart sidecar from matching
                # merely because the backup carried the same revision number.
                self._record_dataset_mutation(restored, rotate_identity=True)
                self._synchronize_dataset_digest(restored)
                restored.commit()
                self._validate_restore_logical_quotas(restored)
                self._require_restore_free_space(temporary.stat().st_size)
                restored.execute("VACUUM")
                self._validate_schema(restored)
                self._validate_payload_integrity(restored)
                integrity = restored.execute("PRAGMA quick_check(1)").fetchone()
                if integrity is None or integrity[0] != "ok":
                    raise sqlite3.DatabaseError("Backup SQLite non integro")
                self._validate_restore_logical_quotas(restored)
                restored.close()
                restored = None
                source_connection.close()
                source_connection = None

                restored_bytes = temporary.stat().st_size
                if restored_bytes > self.max_storage_bytes:
                    raise FeedbackQuotaExceededError(
                        "Dimensione fisica del restore superiore alla quota configurata",
                        purged_receipts=0,
                        quota="disk",
                        limit=self.max_storage_bytes,
                        current=restored_bytes,
                        attempted=0,
                    )
                self._require_restore_free_space(0)

                descriptor = os.open(temporary, os.O_RDONLY)
                try:
                    os.fchmod(descriptor, 0o600)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                os.link(temporary, self.database_path, follow_symlinks=False)
                temporary.unlink()
                temporary = None
                self._sync_directory(self.directory)
                self._secure_database_files()
                self._integrity_signature = None
                return self.database_path
            except FileExistsError:
                raise
            except (OSError, sqlite3.Error) as exc:
                raise FeedbackStorageError(
                    "Ripristino feedback non riuscito",
                    purged_receipts=0,
                ) from exc
            finally:
                if restored is not None:
                    restored.close()
                if source_connection is not None:
                    source_connection.close()
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    def _validate_restore_logical_quotas(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        statistics = self._statistics_from_connection(connection)
        if statistics.receipt_count > self.max_receipts:
            raise FeedbackQuotaExceededError(
                "Il restore supera il numero massimo di ricevute configurato",
                purged_receipts=0,
                quota="receipts",
                limit=self.max_receipts,
                current=statistics.receipt_count,
                attempted=0,
            )
        if statistics.byte_count > self.max_storage_bytes:
            raise FeedbackQuotaExceededError(
                "Il restore supera lo spazio logico massimo configurato",
                purged_receipts=0,
                quota="bytes",
                limit=self.max_storage_bytes,
                current=statistics.byte_count,
                attempted=0,
            )

    def _require_restore_free_space(self, attempted: int) -> None:
        free_bytes = shutil.disk_usage(self.directory).free
        if free_bytes - attempted < self.min_free_bytes:
            raise FeedbackQuotaExceededError(
                "Spazio libero insufficiente per ripristinare il backup",
                purged_receipts=0,
                quota="free",
                limit=self.min_free_bytes,
                current=free_bytes,
                attempted=attempted,
            )

    def check_ready(self) -> bool:
        """Check schema/integrity and obtain a real SQLite write lock."""

        with self._lock:
            probe: Path | None = None
            try:
                self._initialize_locked()
                descriptor, name = tempfile.mkstemp(prefix=".ready-", dir=self.directory)
                os.fchmod(descriptor, 0o600)
                os.close(descriptor)
                probe = Path(name)
                probe.unlink()

                connection = self._connect()
                try:
                    # BEGIN IMMEDIATE is itself the writeability probe. Rolling
                    # it back avoids appending a no-op frame to the WAL on every
                    # readiness request.
                    connection.execute("BEGIN IMMEDIATE")
                    integrity = connection.execute("PRAGMA quick_check(1)").fetchone()
                    if integrity is None or integrity[0] != "ok":
                        connection.rollback()
                        return False
                    self._validate_schema(connection)
                    signature = self._storage_signature()
                    if signature != self._integrity_signature:
                        self._validate_payload_integrity(connection)
                        self._synchronize_dataset_digest(
                            connection,
                            persist_if_dirty=False,
                        )
                        stable_signature = self._storage_signature()
                        if stable_signature != signature:
                            connection.rollback()
                            return False
                        self._integrity_signature = stable_signature
                    connection.rollback()
                finally:
                    connection.close()
                self._secure_database_files()
                return True
            except (
                FeedbackSaveError,
                OSError,
                sqlite3.Error,
                UnicodeError,
                ValueError,
                RecursionError,
            ):
                if probe is not None:
                    probe.unlink(missing_ok=True)
                return False

    def _initialize_locked(self) -> None:
        self._ensure_directory()
        self._precreate_database()
        connection = self._connect(configure_wal=False)
        try:
            journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()
            if journal_mode is None or str(journal_mode[0]).lower() != "wal":
                raise sqlite3.OperationalError("SQLite WAL non disponibile")
            connection.execute("PRAGMA synchronous=FULL")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise sqlite3.DatabaseError(
                    f"Schema feedback {version} piu recente di quello supportato"
                )
            if version == 0:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS schema_metadata (
                            key TEXT PRIMARY KEY,
                            value TEXT NOT NULL
                        ) WITHOUT ROWID
                        """
                    )
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS receipts (
                            receipt_id TEXT PRIMARY KEY CHECK (length(receipt_id) = 36),
                            payload_json BLOB NOT NULL CHECK (typeof(payload_json) = 'blob'),
                            payload_sha256 TEXT NOT NULL CHECK (
                                length(payload_sha256) = 64
                                AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
                            ),
                            byte_count INTEGER NOT NULL CHECK (
                                byte_count >= 0 AND byte_count = length(payload_json)
                            ),
                            created_at REAL NOT NULL CHECK (
                                typeof(created_at) IN ('real', 'integer')
                            )
                        ) WITHOUT ROWID
                        """
                    )
                    connection.execute(
                        "CREATE INDEX IF NOT EXISTS receipts_created_at_idx ON receipts(created_at)"
                    )
                    self._create_dataset_state_table(connection)
                    self._insert_initial_dataset_state(
                        connection,
                        digest=hashlib.sha256(_DATASET_DIGEST_DOMAIN).hexdigest(),
                    )
                    connection.execute(
                        "INSERT OR REPLACE INTO schema_metadata (key, value) VALUES ('schema_version', ?)",
                        (str(SCHEMA_VERSION),),
                    )
                    connection.execute(f"PRAGMA application_id={_SQLITE_APPLICATION_ID}")
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            elif version == 1:
                self._migrate_v1_to_v2(connection)
                self._integrity_signature = None
                version = 2
            if version == 2:
                self._migrate_v2_to_v3(connection)
                self._integrity_signature = None
            self._validate_schema(connection)
        finally:
            connection.close()
            self._secure_database_files()

    def _connect(self, *, configure_wal: bool = True) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=5.0,
            isolation_level=None,
        )
        try:
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA secure_delete=ON")
            if configure_wal:
                journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
                if journal_mode is None or str(journal_mode[0]).lower() != "wal":
                    raise sqlite3.OperationalError("SQLite WAL non attivo")
            return connection
        except Exception:
            connection.close()
            raise

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != SCHEMA_VERSION:
            raise sqlite3.DatabaseError(f"Versione schema feedback non supportata: {version}")
        metadata = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()
        if metadata is None or metadata[0] != str(SCHEMA_VERSION):
            raise sqlite3.DatabaseError("Metadati schema feedback incoerenti")
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(receipts)").fetchall()
        }
        expected = {
            "receipt_id",
            "payload_json",
            "payload_sha256",
            "byte_count",
            "created_at",
        }
        if columns != expected:
            raise sqlite3.DatabaseError("Schema tabella ricevute non valido")
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(receipts)").fetchall()
        }
        if "receipts_created_at_idx" not in indexes:
            raise sqlite3.DatabaseError("Indice retention feedback mancante")
        table = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'receipts'"
        ).fetchone()
        definition = "" if table is None or table[0] is None else str(table[0]).lower()
        if "byte_count = length(payload_json)" not in definition:
            raise sqlite3.DatabaseError("Vincolo integrita payload feedback mancante")
        state_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(dataset_state)").fetchall()
        }
        if state_columns != {"singleton", "dataset_id", "revision", "digest"}:
            raise sqlite3.DatabaseError("Schema stato dataset feedback non valido")
        self._dataset_state_from_connection(connection)

    def _migrate_v1_to_v2(self, connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                CREATE TABLE receipts_v2 (
                    receipt_id TEXT PRIMARY KEY CHECK (length(receipt_id) = 36),
                    payload_json BLOB NOT NULL CHECK (typeof(payload_json) = 'blob'),
                    payload_sha256 TEXT NOT NULL CHECK (
                        length(payload_sha256) = 64
                        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
                    ),
                    byte_count INTEGER NOT NULL CHECK (
                        byte_count >= 0 AND byte_count = length(payload_json)
                    ),
                    created_at REAL NOT NULL CHECK (
                        typeof(created_at) IN ('real', 'integer')
                    )
                ) WITHOUT ROWID
                """
            )
            connection.execute(
                """
                INSERT INTO receipts_v2 (
                    receipt_id, payload_json, payload_sha256, byte_count, created_at
                )
                SELECT receipt_id, payload_json, payload_sha256, byte_count, created_at
                FROM receipts
                """
            )
            self._validate_payload_integrity(connection, table="receipts_v2")
            connection.execute("DROP TABLE receipts")
            connection.execute("ALTER TABLE receipts_v2 RENAME TO receipts")
            connection.execute(
                "CREATE INDEX receipts_created_at_idx ON receipts(created_at)"
            )
            connection.execute(
                "UPDATE schema_metadata SET value = ? WHERE key = 'schema_version'",
                ("2",),
            )
            connection.execute("PRAGMA user_version=2")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def _migrate_v2_to_v3(self, connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            self._validate_payload_integrity(connection)
            rows = connection.execute(
                """
                SELECT
                    receipt_id,
                    payload_json,
                    payload_sha256,
                    byte_count,
                    created_at
                FROM receipts
                ORDER BY created_at, receipt_id
                """
            ).fetchall()
            _, digest = self._decode_dataset_rows(rows)
            self._create_dataset_state_table(connection)
            self._insert_initial_dataset_state(connection, digest=digest)
            connection.execute(
                "UPDATE schema_metadata SET value = ? WHERE key = 'schema_version'",
                (str(SCHEMA_VERSION),),
            )
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @staticmethod
    def _create_dataset_state_table(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE dataset_state (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                dataset_id TEXT NOT NULL CHECK (length(dataset_id) = 36),
                revision INTEGER NOT NULL CHECK (
                    typeof(revision) = 'integer' AND revision >= 0
                ),
                digest TEXT CHECK (
                    digest IS NULL OR (
                        length(digest) = 64
                        AND digest NOT GLOB '*[^0-9a-f]*'
                    )
                )
            ) WITHOUT ROWID
            """
        )

    @staticmethod
    def _insert_initial_dataset_state(
        connection: sqlite3.Connection,
        *,
        digest: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO dataset_state (singleton, dataset_id, revision, digest)
            VALUES (1, ?, 0, ?)
            """,
            (str(uuid4()), digest),
        )

    @staticmethod
    def _dataset_state_from_connection(connection: sqlite3.Connection) -> _DatasetState:
        rows = connection.execute(
            "SELECT dataset_id, revision, digest FROM dataset_state WHERE singleton = 1"
        ).fetchall()
        if len(rows) != 1:
            raise sqlite3.DatabaseError("Stato dataset feedback mancante o duplicato")
        raw_dataset_id, raw_revision, raw_digest = rows[0]
        try:
            dataset_id = UUID(str(raw_dataset_id))
        except (AttributeError, ValueError) as exc:
            raise sqlite3.DatabaseError("Identita dataset feedback non valida") from exc
        if dataset_id.version != 4 or str(dataset_id) != raw_dataset_id:
            raise sqlite3.DatabaseError("Identita dataset feedback non canonica")
        if (
            isinstance(raw_revision, bool)
            or not isinstance(raw_revision, int)
            or raw_revision < 0
            or raw_revision > _MAX_DATASET_REVISION
        ):
            raise sqlite3.DatabaseError("Revisione dataset feedback non valida")
        digest: str | None
        if raw_digest is None:
            digest = None
        elif (
            isinstance(raw_digest, str)
            and len(raw_digest) == 64
            and all(character in "0123456789abcdef" for character in raw_digest)
        ):
            digest = raw_digest
        else:
            raise sqlite3.DatabaseError("Digest dataset feedback non valido")
        return _DatasetState(
            dataset_id=dataset_id,
            revision=raw_revision,
            digest=digest,
        )

    @classmethod
    def _decode_dataset_rows(
        cls,
        rows: list[tuple[Any, ...]],
    ) -> tuple[list[dict[str, Any]], str]:
        digest = hashlib.sha256(_DATASET_DIGEST_DOMAIN)
        payloads: list[dict[str, Any]] = []
        for receipt_id, raw_payload, expected_hash, byte_count, created_at in rows:
            try:
                parsed_receipt_id = UUID(str(receipt_id))
            except (AttributeError, ValueError) as exc:
                raise sqlite3.DatabaseError(
                    f"Identita ricevuta feedback non valida: {receipt_id}"
                ) from exc
            if parsed_receipt_id.version != 4 or str(parsed_receipt_id) != receipt_id:
                raise sqlite3.DatabaseError(
                    f"Identita ricevuta feedback non canonica: {receipt_id}"
                )
            try:
                timestamp = float(created_at)
            except (TypeError, ValueError, OverflowError) as exc:
                raise sqlite3.DatabaseError(
                    f"Data ricevuta feedback non valida: {receipt_id}"
                ) from exc
            if not math.isfinite(timestamp):
                raise sqlite3.DatabaseError(
                    f"Data ricevuta feedback non finita: {receipt_id}"
                )
            encoded = bytes(raw_payload)
            if len(encoded) != int(byte_count):
                raise sqlite3.DatabaseError(
                    f"Dimensione ricevuta feedback incoerente: {receipt_id}"
                )
            actual_hash = hashlib.sha256(encoded).hexdigest()
            if actual_hash != expected_hash:
                raise sqlite3.DatabaseError(
                    f"Hash ricevuta feedback incoerente: {receipt_id}"
                )
            try:
                payload = json.loads(encoded, parse_constant=_invalid_json_constant)
            except (UnicodeError, ValueError, RecursionError) as exc:
                raise sqlite3.DatabaseError(
                    f"JSON ricevuta feedback illeggibile: {receipt_id}"
                ) from exc
            if not isinstance(payload, dict):
                raise sqlite3.DatabaseError(
                    f"Radice ricevuta feedback non valida: {receipt_id}"
                )
            digest.update(parsed_receipt_id.bytes)
            digest.update(struct.pack(">d", timestamp))
            digest.update(bytes.fromhex(actual_hash))
            payloads.append(payload)
        return payloads, digest.hexdigest()

    @staticmethod
    def _source_token(state: _DatasetState, dataset_digest: str) -> str:
        digest = hashlib.sha256(_SOURCE_TOKEN_DOMAIN)
        digest.update(state.dataset_id.bytes)
        digest.update(state.revision.to_bytes(8, "big"))
        digest.update(bytes.fromhex(dataset_digest))
        return digest.hexdigest()

    def _persist_dataset_digest_if_current(
        self,
        expected: _DatasetState,
        dataset_digest: str,
    ) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._dataset_state_from_connection(connection)
            if (
                current.dataset_id != expected.dataset_id
                or current.revision != expected.revision
            ):
                connection.rollback()
                return
            if current.digest is not None and current.digest != dataset_digest:
                raise sqlite3.DatabaseError("Digest concorrente del dataset incoerente")
            if current.digest is None:
                connection.execute(
                    "UPDATE dataset_state SET digest = ? WHERE singleton = 1",
                    (dataset_digest,),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
            self._secure_database_files()

    @staticmethod
    def _record_dataset_mutation(
        connection: sqlite3.Connection,
        *,
        rotate_identity: bool = False,
    ) -> None:
        if rotate_identity:
            cursor = connection.execute(
                """
                UPDATE dataset_state
                SET dataset_id = ?, revision = revision + 1, digest = NULL
                WHERE singleton = 1 AND revision < ?
                """,
                (str(uuid4()), _MAX_DATASET_REVISION),
            )
        else:
            cursor = connection.execute(
                """
                UPDATE dataset_state
                SET revision = revision + 1, digest = NULL
                WHERE singleton = 1 AND revision < ?
                """,
                (_MAX_DATASET_REVISION,),
            )
        if cursor.rowcount != 1:
            raise sqlite3.DatabaseError("Revisione dataset feedback non incrementabile")

    @classmethod
    def _synchronize_dataset_digest(
        cls,
        connection: sqlite3.Connection,
        *,
        persist_if_dirty: bool = True,
    ) -> str:
        state = cls._dataset_state_from_connection(connection)
        rows = connection.execute(
            """
            SELECT
                receipt_id,
                payload_json,
                payload_sha256,
                byte_count,
                created_at
            FROM receipts
            ORDER BY created_at, receipt_id
            """
        ).fetchall()
        _, calculated = cls._decode_dataset_rows(rows)
        if state.digest is not None and state.digest != calculated:
            raise sqlite3.DatabaseError("Digest persistente del dataset incoerente")
        if state.digest is None and persist_if_dirty:
            connection.execute(
                "UPDATE dataset_state SET digest = ? WHERE singleton = 1",
                (calculated,),
            )
        return calculated

    @staticmethod
    def _validate_payload_integrity(
        connection: sqlite3.Connection,
        *,
        table: str = "receipts",
    ) -> None:
        if table not in {"receipts", "receipts_v2"}:
            raise ValueError("Tabella integrita feedback non valida")
        rows = connection.execute(
            f"""
            SELECT receipt_id, payload_json, payload_sha256, byte_count, created_at
            FROM {table}
            """
        ).fetchall()
        for receipt_id, raw_payload, expected_hash, byte_count, created_at in rows:
            try:
                timestamp = float(created_at)
            except (TypeError, ValueError, OverflowError) as exc:
                raise sqlite3.DatabaseError(
                    f"Data ricevuta feedback non valida: {receipt_id}"
                ) from exc
            if not math.isfinite(timestamp):
                raise sqlite3.DatabaseError(
                    f"Data ricevuta feedback non finita: {receipt_id}"
                )
            encoded = bytes(raw_payload)
            if len(encoded) != int(byte_count):
                raise sqlite3.DatabaseError(
                    f"Dimensione ricevuta feedback incoerente: {receipt_id}"
                )
            if hashlib.sha256(encoded).hexdigest() != expected_hash:
                raise sqlite3.DatabaseError(
                    f"Hash ricevuta feedback incoerente: {receipt_id}"
                )
            try:
                payload = json.loads(encoded, parse_constant=_invalid_json_constant)
            except (UnicodeError, ValueError, RecursionError) as exc:
                raise sqlite3.DatabaseError(
                    f"JSON ricevuta feedback illeggibile: {receipt_id}"
                ) from exc
            if not isinstance(payload, dict):
                raise sqlite3.DatabaseError(
                    f"Radice ricevuta feedback non valida: {receipt_id}"
                )

    def _ensure_directory(self) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.directory.is_dir():
            raise OSError("Il percorso delle ricevute non e una directory")
        os.chmod(self.directory, 0o700)

    def _precreate_database(self) -> None:
        flags = os.O_CREAT | os.O_RDWR
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.database_path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise OSError("Il database feedback non e un file regolare")
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)

    def _secure_database_files(self) -> None:
        for path in (
            self.database_path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        ):
            try:
                os.chmod(path, 0o600, follow_symlinks=False)
            except FileNotFoundError:
                continue

    def _chargeable_physical_database_bytes(
        self,
        connection: sqlite3.Connection,
    ) -> int:
        """Return physical usage excluding SQLite's unavoidable empty baseline."""

        page_size = self._sqlite_page_size(connection)
        root_pages = int(
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_schema WHERE rootpage > 0"
            ).fetchone()[0]
        )
        baseline_database_bytes = (1 + root_pages) * page_size
        try:
            database_bytes = self.database_path.stat(follow_symlinks=False).st_size
        except FileNotFoundError:
            database_bytes = 0
        wal_path = Path(f"{self.database_path}-wal")
        shm_path = Path(f"{self.database_path}-shm")
        try:
            wal_bytes = wal_path.stat(follow_symlinks=False).st_size
        except FileNotFoundError:
            wal_bytes = 0
        try:
            shm_bytes = shm_path.stat(follow_symlinks=False).st_size
        except FileNotFoundError:
            shm_bytes = 0
        # The first 32 KiB SHM region is fixed SQLite coordination overhead,
        # just as the schema/root pages are unavoidable for an empty store.
        return (
            max(database_bytes - baseline_database_bytes, 0)
            + wal_bytes
            + max(shm_bytes - 32_768, 0)
        )

    @classmethod
    def _estimated_insert_physical_bytes(
        cls,
        connection: sqlite3.Connection,
        payload_bytes: int,
    ) -> int:
        """Conservatively budget database pages and their WAL frames."""

        page_size = cls._sqlite_page_size(connection)
        # Account for the receipt id, digest, timestamp and SQLite record
        # metadata, then round to complete database pages. Two extra WAL frames
        # cover the receipt and created-at index b-trees.
        record_bytes = payload_bytes + 512
        payload_pages = max(1, (record_bytes + page_size - 1) // page_size)
        modified_pages = payload_pages + 2
        database_growth = payload_pages * page_size
        wal_growth = 32 + modified_pages * (page_size + 24)
        return database_growth + wal_growth

    @staticmethod
    def _sqlite_page_size(connection: sqlite3.Connection) -> int:
        row = connection.execute("PRAGMA page_size").fetchone()
        if row is None:
            raise sqlite3.DatabaseError("Dimensione pagina SQLite non disponibile")
        page_size = int(row[0])
        if page_size < 512:
            raise sqlite3.DatabaseError("Dimensione pagina SQLite non valida")
        return page_size

    def _storage_signature(self) -> tuple[tuple[int, int], ...]:
        signature: list[tuple[int, int]] = []
        for path in (
            self.database_path,
            Path(f"{self.database_path}-wal"),
        ):
            try:
                information = path.stat(follow_symlinks=False)
                # SQLite may create and remove a zero-byte WAL merely while a
                # connection is open. Its mtime is not a dataset change and
                # must not invalidate the expensive payload-integrity cache.
                if information.st_size == 0:
                    signature.append((0, 0))
                else:
                    signature.append((information.st_mtime_ns, information.st_size))
            except FileNotFoundError:
                signature.append((0, 0))
        return tuple(signature)

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        descriptor = os.open(
            directory,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _purge_expired_locked(self, now: float) -> int:
        if not math.isfinite(now):
            raise ValueError("Data retention non valida")
        cutoff = now - (self.retention_days * 86_400)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM receipts WHERE created_at < ?",
                (cutoff,),
            )
            deleted = max(cursor.rowcount, 0)
            if deleted:
                self._record_dataset_mutation(connection)
            connection.commit()
            if deleted:
                try:
                    self._mark_compaction_required()
                except OSError as exc:
                    raise FeedbackStorageError(
                        "Indicatore di compattazione feedback non scrivibile",
                        purged_receipts=deleted,
                    ) from exc
            if deleted and self._integrity_signature is not None:
                self._integrity_signature = self._storage_signature()
            return deleted
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
            self._secure_database_files()

    @staticmethod
    def _statistics_from_connection(
        connection: sqlite3.Connection,
    ) -> FeedbackStorageStatistics:
        row = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(byte_count), 0) FROM receipts"
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("Statistiche ricevute non disponibili")
        return FeedbackStorageStatistics(receipt_count=int(row[0]), byte_count=int(row[1]))
