from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from feedback_service.admin import main as admin_main
from feedback_service.coordinator import FeedbackCoordinator
from feedback_service.storage import (
    FeedbackQuotaExceededError,
    FeedbackStorageError,
    FeedbackStore,
)


def test_repeated_readiness_reuses_payload_integrity_scan() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        store = FeedbackStore(Path(temporary) / "receipts", retention_days=365)
        store.save({"valid": True})
        original = store._validate_payload_integrity
        original_dataset = store._synchronize_dataset_digest

        with (
            patch.object(store, "_validate_payload_integrity", wraps=original) as validator,
            patch.object(
                store,
                "_synchronize_dataset_digest",
                wraps=original_dataset,
            ) as dataset_validator,
        ):
            assert store.check_ready()
            assert store.check_ready()
            assert store.check_ready()

        assert validator.call_count == 1
        assert dataset_validator.call_count == 1


def test_physical_quota_excludes_empty_baseline_and_budgets_sqlite_pages() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary) / "receipts"
        probe = FeedbackStore(directory, retention_days=365)
        probe.initialize()
        encoded = probe._encode_payload({"small": True}, purged_receipts=0)
        connection = probe._connect()
        try:
            attempted = probe._estimated_insert_physical_bytes(connection, len(encoded))
            assert probe._chargeable_physical_database_bytes(connection) == 0
        finally:
            connection.close()

        assert attempted > len(encoded)
        restricted = FeedbackStore(
            directory,
            retention_days=365,
            max_storage_bytes=attempted - 1,
            min_free_bytes=0,
        )
        with pytest.raises(FeedbackQuotaExceededError) as captured:
            restricted.save({"small": True})

        assert captured.value.quota == "disk"
        assert captured.value.current == 0
        assert captured.value.attempted == attempted


def test_minimum_free_space_uses_physical_write_budget() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        store = FeedbackStore(
            Path(temporary) / "receipts",
            retention_days=365,
            max_storage_bytes=1_000_000,
            min_free_bytes=100,
        )
        # shutil.disk_usage only consumes the named ``free`` field. A Mock
        # keeps the test independent from the host filesystem capacity.
        with (
            patch.object(store, "_estimated_insert_physical_bytes", return_value=16_384),
            patch("feedback_service.storage.shutil.disk_usage") as usage,
        ):
            usage.return_value.free = 16_483
            with pytest.raises(FeedbackQuotaExceededError) as captured:
                store.save({"small": True})

        assert captured.value.quota == "free"
        assert captured.value.attempted == 16_384


def test_post_purge_marker_survives_failed_compaction_and_next_tick_consumes_it() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary) / "receipts"
        seed = FeedbackStore(directory, retention_days=3_650)
        seed.save({"expired": True}, created_at=time.time() - (2 * 86_400))
        seed.save({"live": True})

        api_store = FeedbackStore(directory, retention_days=1)
        receipt = api_store.save({"new": True})
        assert receipt.purged_receipts == 1
        assert api_store.compaction_required()
        assert stat.S_IMODE(api_store.compaction_marker_path.stat().st_mode) == 0o600
        assert api_store.compaction_marker_path.stat().st_uid == os.getuid()

        worker_store = FeedbackStore(directory, retention_days=1)
        coordinator = FeedbackCoordinator(Mock(), worker_store, Mock())
        with patch.object(
            worker_store,
            "compact",
            side_effect=FeedbackStorageError("boom", purged_receipts=0),
        ):
            with pytest.raises(FeedbackStorageError):
                coordinator.retention_tick()
        assert worker_store.compaction_required()

        assert coordinator.retention_tick() == 0
        assert not worker_store.compaction_required()


def test_admin_purge_reports_initialize_and_tick_deletions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage = tmp_path / "receipts"
    seed = FeedbackStore(storage, retention_days=3_650)
    seed.save({"expired": True}, created_at=time.time() - (2 * 86_400))
    monkeypatch.setenv("FEEDBACK_STORAGE_DIR", str(storage))
    monkeypatch.setenv("FEEDBACK_CHARTS_DIR", str(tmp_path / "charts"))
    monkeypatch.setenv("FEEDBACK_RETENTION_DAYS", "1")

    assert admin_main(["purge"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"purged_receipts": 1}
