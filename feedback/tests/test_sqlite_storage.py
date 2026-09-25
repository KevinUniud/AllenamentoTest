from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from feedback_service.admin import main as admin_main
from feedback_service.config import load_settings
from feedback_service.migrate_legacy import main as migrate_main
from feedback_service.migrate_legacy import migrate_legacy_directory
from feedback_service.storage import (
    DATABASE_FILENAME,
    SCHEMA_VERSION,
    FeedbackQuotaExceededError,
    FeedbackStorageError,
    FeedbackStore,
    IdempotencyConflictError,
)


def _zero_report() -> dict[str, object]:
    return {
        "Initial Data": {
            "Tempo inizio esercitazione": "2026/08/01 12:00:00",
            "Tempo totale": "0.00s",
            "Totale domande": 0,
            "Totale domande corrette": 0,
            "Totale domande errate": 0,
            "Opzioni attive": {},
        },
        "Domande": [],
        "Feedback": {
            "Aspettative test": "3",
            "Utilità ausili": "3",
            "Utilità lezioni": "3",
            "Difficoltà test": "3",
            "Controllo": "3",
        },
    }


def test_sqlite_schema_permissions_statistics_and_deep_equal_payload() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary) / "receipts"
        store = FeedbackStore(directory, retention_days=365)
        assert store.initialize() == 0

        payload = {"accento": "università", "nested": {"b": True, "a": [1, None]}}
        receipt = store.save(payload)

        assert store.snapshot_payloads() == [payload]
        statistics = store.statistics()
        assert statistics.receipt_count == 1
        assert statistics.byte_count > 0
        assert store.stats() == statistics
        assert store.check_ready()
        assert not (directory / receipt.filename).exists()
        assert {path.name for path in directory.iterdir()} == {DATABASE_FILENAME}
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert stat.S_IMODE(store.database_path.stat().st_mode) == 0o600

        with sqlite3.connect(store.database_path) as connection:
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            indexes = {
                row[1] for row in connection.execute("PRAGMA index_list(receipts)").fetchall()
            }
        assert "receipts_created_at_idx" in indexes


def test_dirty_dataset_digest_is_recovered_and_stable_after_restart() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary) / "receipts"
        first = FeedbackStore(directory, retention_days=365)
        first.save({"payload": "immutato", "nested": [1, 2, 3]})

        with sqlite3.connect(first.database_path) as connection:
            dirty = connection.execute(
                "SELECT revision, digest FROM dataset_state WHERE singleton = 1"
            ).fetchone()
        assert dirty is not None
        assert dirty[0] == 1
        assert dirty[1] is None

        recovered = FeedbackStore(directory, retention_days=365).snapshot_dataset()
        restarted = FeedbackStore(directory, retention_days=365).snapshot_dataset()

        assert recovered.revision == 1
        assert restarted.digest == recovered.digest
        assert restarted.source_token == recovered.source_token
        with sqlite3.connect(first.database_path) as connection:
            persisted = connection.execute(
                "SELECT digest FROM dataset_state WHERE singleton = 1"
            ).fetchone()
        assert persisted == (recovered.digest,)


def test_persistent_dataset_digest_detects_same_shape_logical_tampering() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary) / "receipts"
        store = FeedbackStore(directory, retention_days=365)
        store.save({"payload": "valid"})
        snapshot = store.snapshot_dataset()

        with sqlite3.connect(store.database_path) as connection:
            connection.execute(
                "UPDATE dataset_state SET digest = ? WHERE singleton = 1",
                ("0" * 64,),
            )

        restarted = FeedbackStore(directory, retention_days=365)
        assert not restarted.check_ready()
        with pytest.raises(FeedbackStorageError):
            restarted.snapshot_dataset()
        assert snapshot.digest != "0" * 64


def test_uuid_idempotency_is_atomic_across_store_instances() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary) / "receipts"
        stores = [FeedbackStore(directory, retention_days=365) for _ in range(4)]
        for store in stores:
            store.initialize()
        key = str(uuid4())
        first_order = {"b": [1, 2], "a": "value"}
        second_order = {"a": "value", "b": [1, 2]}

        def save(index: int):  # type: ignore[no-untyped-def]
            payload = first_order if index % 2 else second_order
            return stores[index % len(stores)].save(payload, key)

        with ThreadPoolExecutor(max_workers=16) as executor:
            receipts = list(executor.map(save, range(64)))

        assert {receipt.receipt_id for receipt in receipts} == {UUID(key)}
        assert sum(receipt.created for receipt in receipts) == 1
        assert stores[0].statistics().receipt_count == 1
        numeric_key = str(uuid4())
        stores[0].save({"number": 1}, numeric_key)
        assert not stores[1].save({"number": 1.0}, numeric_key).created
        with pytest.raises(IdempotencyConflictError):
            stores[0].save({"a": "different", "b": [1, 2]}, key)


def test_retention_runs_before_atomic_receipt_quota_check() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary) / "receipts"
        initial = FeedbackStore(directory, retention_days=3_650)
        initial.save({"expired": True}, created_at=time.time() - (2 * 86_400))
        initial.save({"live": True})

        restricted = FeedbackStore(directory, retention_days=1, max_receipts=1)
        with pytest.raises(FeedbackQuotaExceededError) as captured:
            restricted.save({"third": True})
        assert captured.value.quota == "receipts"
        assert captured.value.purged_receipts == 1
        assert restricted.statistics().receipt_count == 1
        assert restricted.snapshot_payloads() == [{"live": True}]


def test_logical_byte_quota_rejects_without_partial_insert() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        store = FeedbackStore(
            Path(temporary) / "receipts",
            retention_days=365,
            max_storage_bytes=1,
        )
        with pytest.raises(FeedbackQuotaExceededError) as captured:
            store.save({"larger": "than one byte"})
        assert captured.value.quota == "bytes"
        assert captured.value.limit == 1
        assert captured.value.current == 0
        assert captured.value.attempted > 1
        assert store.statistics().receipt_count == 0
        assert store.statistics().byte_count == 0


def test_quota_environment_defaults_and_overrides() -> None:
    with patch.dict(
        os.environ,
        {
            "FEEDBACK_MAX_RECEIPTS": "17",
            "FEEDBACK_MAX_STORAGE_BYTES": "4096",
        },
    ):
        settings = load_settings()
    assert settings.max_receipts == 17
    assert settings.max_storage_bytes == 4096

    with patch.dict(os.environ, {"FEEDBACK_MAX_RECEIPTS": "0"}):
        with pytest.raises(RuntimeError):
            load_settings()


def test_explicit_legacy_migration_has_non_writing_dry_run() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "legacy"
        destination = root / "receipts"
        source.mkdir()
        payload = _zero_report()
        (source / "1.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        (source / "invalid.json").write_text("{}", encoding="utf-8")
        store = FeedbackStore(destination, retention_days=365)

        preview = migrate_legacy_directory(source, store, dry_run=True)
        assert preview.scanned_files == 2
        assert preview.valid_files == 1
        assert preview.invalid_files == 1
        assert preview.imported_receipts == 0
        assert not destination.exists()

        migrated = migrate_legacy_directory(source, store)
        assert migrated.imported_receipts == 1
        assert migrated.invalid_files == 1
        assert store.snapshot_payloads() == [payload]
        assert not list(destination.glob("*.json"))

        repeated = migrate_legacy_directory(source, store)
        assert repeated.imported_receipts == 0
        assert repeated.duplicate_receipts == 1
        assert store.statistics().receipt_count == 1


def test_consistent_backup_is_private_complete_and_never_overwritten() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = FeedbackStore(root / "receipts", retention_days=365)
        payloads = [{"index": index, "text": "università"} for index in range(3)]
        for payload in payloads:
            store.save(payload)

        destination = root / "backups" / "feedback.sqlite3"
        result = store.backup_to(destination)

        assert result == destination
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
        with sqlite3.connect(destination) as connection:
            assert connection.execute("PRAGMA quick_check(1)").fetchone()[0] == "ok"
            rows = connection.execute(
                "SELECT payload_json FROM receipts ORDER BY created_at, receipt_id"
            ).fetchall()
        assert [json.loads(bytes(row[0])) for row in rows] == payloads
        with pytest.raises(FileExistsError):
            store.backup_to(destination)


def test_backup_excludes_expired_rows_without_mutating_the_live_store() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        long_retention = FeedbackStore(root / "receipts", retention_days=365)
        long_retention.save(
            {"expired": True},
            created_at=time.time() - (2 * 86_400),
        )
        short_retention = FeedbackStore(root / "receipts", retention_days=1)
        destination = short_retention.backup_to(root / "backup.sqlite3")

        assert long_retention.statistics().receipt_count == 1
        with sqlite3.connect(destination) as connection:
            assert connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0


def test_verified_restore_round_trip_refuses_active_or_corrupt_destinations() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        original = FeedbackStore(root / "original", retention_days=365)
        payload = {"payload": "con accento è", "nested": [1, 2, 3]}
        original.save(payload)
        backup = original.backup_to(root / "backup.sqlite3")

        restored = FeedbackStore(root / "restored", retention_days=365)
        assert restored.restore_from(backup) == restored.database_path
        assert restored.snapshot_payloads() == [payload]
        restored_snapshot = restored.snapshot_dataset()
        second_restored = FeedbackStore(root / "second-restored", retention_days=365)
        second_restored.restore_from(backup)
        second_snapshot = second_restored.snapshot_dataset()
        assert second_snapshot.revision == restored_snapshot.revision
        assert second_snapshot.digest == restored_snapshot.digest
        assert second_snapshot.source_token != restored_snapshot.source_token
        assert stat.S_IMODE(restored.database_path.stat().st_mode) == 0o600
        with pytest.raises(FileExistsError):
            restored.restore_from(backup)

        corrupt = root / "corrupt.sqlite3"
        corrupt.write_bytes(backup.read_bytes())
        with sqlite3.connect(corrupt) as connection:
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute("UPDATE receipts SET payload_sha256 = ?", ("0" * 64,))
        rejected = FeedbackStore(root / "rejected", retention_days=365)
        with pytest.raises(FeedbackStorageError):
            rejected.restore_from(corrupt)
        assert not rejected.database_path.exists()


def test_restore_rejects_two_live_receipts_when_quota_is_one_atomically() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = FeedbackStore(root / "source", retention_days=365)
        source.save({"index": 1})
        source.save({"index": 2})
        backup = source.backup_to(root / "backup.sqlite3")

        restored = FeedbackStore(
            root / "restored",
            retention_days=365,
            max_receipts=1,
            min_free_bytes=0,
        )
        with pytest.raises(FeedbackQuotaExceededError) as captured:
            restored.restore_from(backup)

        assert captured.value.quota == "receipts"
        assert captured.value.current == 2
        assert captured.value.limit == 1
        assert not restored.database_path.exists()
        assert not list(restored.directory.glob(".feedback-restore-*"))


def test_restore_applies_retention_before_receipt_quota() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = FeedbackStore(root / "source", retention_days=365)
        source.save({"expired": True}, created_at=time.time() - (2 * 86_400))
        source.save({"live": True})
        backup = source.backup_to(root / "backup.sqlite3")

        restored = FeedbackStore(
            root / "restored",
            retention_days=1,
            max_receipts=1,
            min_free_bytes=0,
        )
        restored.restore_from(backup)

        assert restored.snapshot_payloads() == [{"live": True}]


def test_backup_and_restore_reject_non_finite_created_at_without_output() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        active = FeedbackStore(root / "active", retention_days=365)
        active.save({"valid": True})
        with sqlite3.connect(active.database_path) as connection:
            connection.execute("UPDATE receipts SET created_at = ?", (float("inf"),))

        invalid_backup = root / "invalid-backup.sqlite3"
        with pytest.raises(FeedbackStorageError):
            active.backup_to(invalid_backup)
        assert not invalid_backup.exists()

        valid = FeedbackStore(root / "valid", retention_days=365)
        valid.save({"valid": True})
        corrupt_source = valid.backup_to(root / "corrupt-source.sqlite3")
        with sqlite3.connect(corrupt_source) as connection:
            connection.execute("UPDATE receipts SET created_at = ?", (float("inf"),))

        restored = FeedbackStore(root / "restored", retention_days=365)
        with pytest.raises(FeedbackStorageError):
            restored.restore_from(corrupt_source)
        assert not restored.database_path.exists()
        assert not list(restored.directory.glob(".feedback-restore-*"))


def test_restore_enforces_logical_physical_and_free_space_quotas() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = FeedbackStore(root / "source", retention_days=365)
        source.save({"payload": "a sufficiently long value"})
        backup = source.backup_to(root / "backup.sqlite3")
        logical_bytes = source.statistics().byte_count

        logical = FeedbackStore(
            root / "logical",
            retention_days=365,
            max_storage_bytes=logical_bytes - 1,
            min_free_bytes=0,
        )
        with pytest.raises(FeedbackQuotaExceededError) as logical_error:
            logical.restore_from(backup)
        assert logical_error.value.quota == "bytes"
        assert not logical.database_path.exists()

        physical = FeedbackStore(
            root / "physical",
            retention_days=365,
            max_storage_bytes=backup.stat().st_size - 1,
            min_free_bytes=0,
        )
        with pytest.raises(FeedbackQuotaExceededError) as physical_error:
            physical.restore_from(backup)
        assert physical_error.value.quota == "disk"
        assert not physical.database_path.exists()

        no_space = FeedbackStore(
            root / "no-space",
            retention_days=365,
            min_free_bytes=1,
        )
        with patch(
            "feedback_service.storage.shutil.disk_usage",
            return_value=SimpleNamespace(free=backup.stat().st_size),
        ):
            with pytest.raises(FeedbackQuotaExceededError) as free_error:
                no_space.restore_from(backup)
        assert free_error.value.quota == "free"
        assert not no_space.database_path.exists()


def test_restore_of_invalid_sqlite_never_overwrites_an_active_database() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        corrupt = root / "corrupt.sqlite3"
        corrupt.write_bytes(b"not a SQLite database")
        destination = root / "destination"
        destination.mkdir()
        active_database = destination / DATABASE_FILENAME
        sentinel = b"active database sentinel"
        active_database.write_bytes(sentinel)

        store = FeedbackStore(destination, retention_days=365)
        with pytest.raises(FileExistsError):
            store.restore_from(corrupt)

        assert active_database.read_bytes() == sentinel


def test_schema_v3_migrates_valid_v1_and_rejects_logical_corruption() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary) / "receipts"
        directory.mkdir()
        database = directory / DATABASE_FILENAME
        payload = b'{"valid":true}'
        receipt_id = str(uuid4())
        with sqlite3.connect(database) as connection:
            connection.executescript(
                """
                CREATE TABLE schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                ) WITHOUT ROWID;
                CREATE TABLE receipts (
                    receipt_id TEXT PRIMARY KEY,
                    payload_json BLOB NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
                    created_at REAL NOT NULL
                ) WITHOUT ROWID;
                CREATE INDEX receipts_created_at_idx ON receipts(created_at);
                INSERT INTO schema_metadata VALUES ('schema_version', '1');
                PRAGMA user_version=1;
                """
            )
            connection.execute(
                "INSERT INTO receipts VALUES (?, ?, ?, ?, ?)",
                (receipt_id, payload, hashlib.sha256(payload).hexdigest(), len(payload), time.time()),
            )

        store = FeedbackStore(directory, retention_days=365)
        store.initialize()
        migrated_snapshot = store.snapshot_dataset()
        assert migrated_snapshot.payloads == [{"valid": True}]
        assert FeedbackStore(directory, retention_days=365).snapshot_dataset().source_token == (
            migrated_snapshot.source_token
        )
        with sqlite3.connect(database) as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            state = connection.execute(
                "SELECT revision, digest FROM dataset_state WHERE singleton = 1"
            ).fetchone()
            assert state == (0, migrated_snapshot.digest)
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute(
                "UPDATE receipts SET payload_json = ? WHERE receipt_id = ?",
                (b'{"valid":fals}', receipt_id),
            )
        assert not store.check_ready()
        with pytest.raises(FeedbackStorageError):
            store.snapshot_payloads()


def test_admin_status_is_observational_when_storage_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage = tmp_path / "missing-receipts"
    charts = tmp_path / "missing-charts"
    monkeypatch.setenv("FEEDBACK_STORAGE_DIR", str(storage))
    monkeypatch.setenv("FEEDBACK_CHARTS_DIR", str(charts))

    assert admin_main(["status"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["receipt_count"] == 0
    assert output["snapshot_generation"] is None
    assert not storage.exists()
    assert not charts.exists()


def test_migration_preview_reports_expired_and_future_reports_without_writes() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "legacy"
        source.mkdir()
        expired = _zero_report()
        future = _zero_report()
        expired["Initial Data"]["Tempo inizio esercitazione"] = "2020/01/01 00:00:00"  # type: ignore[index]
        future["Initial Data"]["Tempo inizio esercitazione"] = "2099/01/01 00:00:00"  # type: ignore[index]
        (source / "expired.json").write_text(json.dumps(expired), encoding="utf-8")
        (source / "future.json").write_text(json.dumps(future), encoding="utf-8")
        destination = root / "receipts"
        store = FeedbackStore(destination, retention_days=365)

        preview = migrate_legacy_directory(source, store, dry_run=True)

        assert preview.scanned_files == 2
        assert preview.valid_files == 1
        assert preview.expired_files == 1
        assert preview.future_dated_files == 1
        assert preview.invalid_files == 1
        assert not destination.exists()

        assert (
            migrate_main(
                [
                    str(source),
                    "--storage-dir",
                    str(destination),
                    "--retention-days",
                    "0",
                ]
            )
            == 2
        )
        assert not destination.exists()
