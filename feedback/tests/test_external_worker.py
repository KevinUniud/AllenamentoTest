from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from feedback_service.app import create_app
from feedback_service.config import FeedbackSettings
from feedback_service.coordinator import PublicationResult
from feedback_service.filelock import SingleInstanceLock
from feedback_service.worker import PeriodicFeedbackWorker
from feedback_service.worker import main as worker_main
from feedback_service.worker_status import WorkerStatus, WorkerStatusStore


def _external_settings(root: Path) -> FeedbackSettings:
    return FeedbackSettings(
        storage_dir=root / "receipts",
        charts_dir=root / "charts",
        retention_days=365,
        max_body_bytes=4_096,
        max_receipts=100,
        max_storage_bytes=1_048_576,
        minimum_aggregate_sessions=3,
        snapshots_to_keep=3,
        publish_interval_seconds=86_400,
        retention_interval_seconds=3_600,
        worker_heartbeat_seconds=1,
        worker_stale_seconds=5,
        worker_mode="external",
    )


def _worker_environment(root: Path) -> dict[str, str]:
    settings = _external_settings(root)
    return {
        "FEEDBACK_STORAGE_DIR": str(settings.storage_dir),
        "FEEDBACK_CHARTS_DIR": str(settings.charts_dir),
        "FEEDBACK_RETENTION_DAYS": str(settings.retention_days),
        "FEEDBACK_MAX_BODY_BYTES": str(settings.max_body_bytes),
        "FEEDBACK_MAX_RECEIPTS": str(settings.max_receipts),
        "FEEDBACK_MAX_STORAGE_BYTES": str(settings.max_storage_bytes),
        "FEEDBACK_MIN_AGGREGATE_SESSIONS": str(
            settings.minimum_aggregate_sessions
        ),
        "FEEDBACK_SNAPSHOTS_TO_KEEP": str(settings.snapshots_to_keep),
        "FEEDBACK_PUBLISH_INTERVAL_SECONDS": str(
            settings.publish_interval_seconds
        ),
        "FEEDBACK_RETENTION_INTERVAL_SECONDS": str(
            settings.retention_interval_seconds
        ),
        "FEEDBACK_WORKER_HEARTBEAT_SECONDS": str(
            settings.worker_heartbeat_seconds
        ),
        "FEEDBACK_WORKER_STALE_SECONDS": str(settings.worker_stale_seconds),
        "FEEDBACK_WORKER_JOB_TIMEOUT_SECONDS": str(
            settings.worker_job_timeout_seconds
        ),
        "FEEDBACK_WORKER_MODE": settings.worker_mode,
    }


def _status(*, updated_at: float) -> WorkerStatus:
    return WorkerStatus(
        schema_version=1,
        state="idle",
        updated_at=updated_at,
    )


class ExternalWorkerCommandTests(unittest.TestCase):
    def test_check_reports_missing_fresh_and_stale_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            status_store = WorkerStatusStore(root / "charts" / "worker-status.json")
            environment = _worker_environment(root)

            with patch.dict(os.environ, environment, clear=True):
                self.assertEqual(worker_main(["--check"]), 1)

                status_store.write(_status(updated_at=time.time()))
                self.assertEqual(worker_main(["--check"]), 0)

                status_store.write(_status(updated_at=time.time() - 6))
                self.assertEqual(worker_main(["--check"]), 1)

    def test_once_is_single_instance_and_releases_its_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = _worker_environment(root)
            status_store = WorkerStatusStore(root / "charts" / "worker-status.json")
            instance_lock = SingleInstanceLock(root / "charts" / ".worker.lock")

            with patch.dict(os.environ, environment, clear=True):
                self.assertEqual(worker_main(["--once"]), 0)
                # A process that has already exited must not leave a fresh
                # lease that would make the separate HTTP process appear ready.
                self.assertIsNone(status_store.read())

                with instance_lock:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "Un altro worker feedback",
                    ):
                        worker_main(["--once"])

                self.assertEqual(worker_main(["--once"]), 0)

    def test_failed_once_never_leaves_a_daemon_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worker = PeriodicFeedbackWorker(_external_settings(Path(temporary)))
            worker.coordinator.publication_tick = Mock(  # type: ignore[method-assign]
                side_effect=RuntimeError("render fallito")
            )

            with self.assertRaisesRegex(RuntimeError, "render fallito"):
                worker.publication_once()

            self.assertIsNone(worker.status_store.read())

    def test_heartbeat_remains_fresh_during_a_long_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active_settings = _external_settings(root)
            active_settings = FeedbackSettings(
                storage_dir=active_settings.storage_dir,
                charts_dir=active_settings.charts_dir,
                retention_days=active_settings.retention_days,
                max_body_bytes=active_settings.max_body_bytes,
                max_receipts=active_settings.max_receipts,
                max_storage_bytes=active_settings.max_storage_bytes,
                minimum_aggregate_sessions=active_settings.minimum_aggregate_sessions,
                snapshots_to_keep=active_settings.snapshots_to_keep,
                publish_interval_seconds=1,
                retention_interval_seconds=60,
                worker_heartbeat_seconds=1,
                worker_stale_seconds=2,
                worker_mode="external",
            )
            worker = PeriodicFeedbackWorker(active_settings)
            publication_started = threading.Event()
            release_publication = threading.Event()

            def blocked_publication() -> PublicationResult:
                publication_started.set()
                release_publication.wait(timeout=10)
                return PublicationResult(
                    action="unchanged",
                    receipt_count=0,
                    purged_receipts=0,
                )

            worker.coordinator.publication_tick = blocked_publication  # type: ignore[method-assign]
            thread = threading.Thread(target=worker.run_forever)
            thread.start()
            try:
                self.assertTrue(publication_started.wait(timeout=4))
                time.sleep(2.2)
                self.assertTrue(
                    worker.status_store.is_fresh(maximum_age_seconds=2)
                )
                status = worker.status_store.read()
                assert status is not None
                self.assertEqual(status.state, "publishing")
            finally:
                worker.request_stop()
                release_publication.set()
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertIsNone(worker.status_store.read())

    def test_heartbeat_write_failure_stops_the_main_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            active_settings = replace(
                _external_settings(Path(temporary)),
                publish_interval_seconds=60,
                retention_interval_seconds=60,
                worker_heartbeat_seconds=1,
                worker_stale_seconds=3,
                worker_job_timeout_seconds=10,
            )
            worker = PeriodicFeedbackWorker(active_settings)
            original_write = worker.status_store.write
            failures: list[BaseException] = []

            def fail_only_in_heartbeat(status: WorkerStatus) -> None:
                if threading.current_thread().name == "feedback-worker-heartbeat":
                    raise OSError("fsync heartbeat fallito")
                original_write(status)

            def run_worker() -> None:
                try:
                    worker.run_forever()
                except BaseException as exc:
                    failures.append(exc)

            with patch.object(
                worker.status_store,
                "write",
                side_effect=fail_only_in_heartbeat,
            ):
                thread = threading.Thread(target=run_worker)
                thread.start()
                thread.join(timeout=5)

            self.assertFalse(thread.is_alive())
            self.assertEqual(len(failures), 1)
            self.assertIsInstance(failures[0], RuntimeError)
            self.assertIn("Heartbeat", str(failures[0]))
            self.assertIsNone(worker.status_store.read())

    def test_watchdog_terminates_a_worker_with_a_deadlocked_tick(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            active_settings = replace(
                _external_settings(Path(temporary)),
                publish_interval_seconds=1,
                retention_interval_seconds=60,
                worker_heartbeat_seconds=1,
                worker_stale_seconds=3,
                worker_job_timeout_seconds=1,
            )
            worker = PeriodicFeedbackWorker(active_settings)
            publication_started = threading.Event()
            release_publication = threading.Event()
            worker_job_finished = threading.Event()
            failures: list[BaseException] = []

            def blocked_publication() -> PublicationResult:
                publication_started.set()
                release_publication.wait(timeout=10)
                return PublicationResult(
                    action="unchanged",
                    receipt_count=0,
                    purged_receipts=0,
                )

            def run_worker() -> None:
                try:
                    worker.run_forever()
                except BaseException as exc:
                    failures.append(exc)

            original_run_publication = worker._run_publication

            def tracked_publication() -> bool:
                try:
                    return original_run_publication()
                finally:
                    worker_job_finished.set()

            worker.coordinator.publication_tick = blocked_publication  # type: ignore[method-assign]
            worker._run_publication = tracked_publication  # type: ignore[method-assign]
            thread = threading.Thread(target=run_worker)
            thread.start()
            try:
                self.assertTrue(publication_started.wait(timeout=4))
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(failures), 1)
                self.assertIn("Timeout", str(failures[0]))
            finally:
                release_publication.set()
                worker_job_finished.wait(timeout=2)
                worker.status_store.remove()

    def test_publication_error_survives_a_successful_retention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worker = PeriodicFeedbackWorker(_external_settings(Path(temporary)))
            worker.coordinator.publication_tick = Mock(  # type: ignore[method-assign]
                side_effect=RuntimeError("renderer non disponibile")
            )
            worker.coordinator.retention_tick = Mock(return_value=0)  # type: ignore[method-assign]

            self.assertFalse(worker._run_publication())
            failed = worker.status_store.read()
            assert failed is not None
            self.assertEqual(failed.state, "error")
            self.assertIsNotNone(failed.last_error_at)

            self.assertTrue(worker._run_retention())
            retained_error = worker.status_store.read()
            assert retained_error is not None
            self.assertEqual(retained_error.state, "error")
            self.assertEqual(retained_error.last_error_at, failed.last_error_at)
            self.assertFalse(
                worker.status_store.is_fresh(maximum_age_seconds=60)
            )

            worker.coordinator.publication_tick = Mock(  # type: ignore[method-assign]
                return_value=PublicationResult(
                    action="unchanged",
                    receipt_count=0,
                    purged_receipts=0,
                )
            )
            self.assertTrue(worker._run_publication())
            recovered = worker.status_store.read()
            assert recovered is not None
            self.assertEqual(recovered.state, "idle")
            self.assertIsNone(recovered.last_error_at)

    def test_stop_between_due_jobs_skips_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            active_settings = replace(
                _external_settings(Path(temporary)),
                publish_interval_seconds=1,
                retention_interval_seconds=1,
                worker_job_timeout_seconds=10,
            )
            worker = PeriodicFeedbackWorker(active_settings)
            retention_started = threading.Event()
            release_retention = threading.Event()
            publication_calls = 0

            def blocked_retention() -> int:
                retention_started.set()
                release_retention.wait(timeout=5)
                return 0

            def publication() -> PublicationResult:
                nonlocal publication_calls
                publication_calls += 1
                return PublicationResult(
                    action="unchanged",
                    receipt_count=0,
                    purged_receipts=0,
                )

            worker.coordinator.retention_tick = blocked_retention  # type: ignore[method-assign]
            worker.coordinator.publication_tick = publication  # type: ignore[method-assign]
            thread = threading.Thread(target=worker.run_forever)
            thread.start()
            try:
                self.assertTrue(retention_started.wait(timeout=4))
                worker.request_stop()
            finally:
                release_retention.set()
                thread.join(timeout=5)

            self.assertFalse(thread.is_alive())
            self.assertEqual(publication_calls, 0)


class ExternalWorkerReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_readiness_requires_a_fresh_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            active_settings = _external_settings(Path(temporary))
            app = create_app(active_settings)
            status_store: WorkerStatusStore = app.state.worker_status

            async with app.router.lifespan_context(app):
                self.assertIsNone(app.state.publication_task)
                self.assertIsNone(app.state.retention_task)
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://feedback",
                ) as client:
                    missing = await client.get("/ready")
                    self.assertEqual(missing.status_code, 503)

                    status_store.write(_status(updated_at=time.time()))
                    fresh = await client.get("/ready")
                    self.assertEqual(fresh.status_code, 200)
                    self.assertEqual(fresh.json()["worker"], "external")

                    status_store.write(_status(updated_at=time.time() - 6))
                    stale = await client.get("/ready")
                    self.assertEqual(stale.status_code, 503)

                    status_store.write(
                        WorkerStatus(
                            schema_version=1,
                            state="error",
                            updated_at=time.time(),
                        )
                    )
                    errored = await client.get("/ready")
                    self.assertEqual(errored.status_code, 503)

                    for active_state in ("publishing", "retention"):
                        status_store.write(
                            WorkerStatus(
                                schema_version=1,
                                state=active_state,  # type: ignore[arg-type]
                                updated_at=time.time(),
                                last_error_at=time.time(),
                            )
                        )
                        pending_error = await client.get("/ready")
                        self.assertEqual(pending_error.status_code, 503)

                    status_store.write(
                        WorkerStatus(
                            schema_version=1,
                            state="starting",
                            updated_at=time.time(),
                        )
                    )
                    starting = await client.get("/ready")
                    self.assertEqual(starting.status_code, 503)


if __name__ == "__main__":
    unittest.main()
