"""Dedicated periodic chart and retention worker."""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from datetime import datetime
from typing import TypeVar

from feedback_service.config import FeedbackSettings, load_settings
from feedback_service.coordinator import FeedbackCoordinator, PublicationResult
from feedback_service.filelock import SingleInstanceLock
from feedback_service.snapshots import ChartSnapshotPublisher, SnapshotInvalidatedError
from feedback_service.storage import FeedbackStore
from feedback_service.worker_status import WorkerState, WorkerStatus, WorkerStatusStore

LOGGER = logging.getLogger(__name__)
_JobResult = TypeVar("_JobResult")


class PeriodicFeedbackWorker:
    def __init__(self, settings: FeedbackSettings) -> None:
        self.settings = settings
        self.store = FeedbackStore(
            settings.storage_dir,
            retention_days=settings.retention_days,
            max_receipts=settings.max_receipts,
            max_storage_bytes=settings.max_storage_bytes,
            min_free_bytes=settings.min_free_bytes,
        )
        self.publisher = ChartSnapshotPublisher(
            settings.charts_dir,
            minimum_aggregate_sessions=settings.minimum_aggregate_sessions,
            snapshots_to_keep=settings.snapshots_to_keep,
        )
        self.coordinator = FeedbackCoordinator(
            settings,
            self.store,
            self.publisher,
        )
        self.status_store = WorkerStatusStore(settings.charts_dir / "worker-status.json")
        self.instance_lock = SingleInstanceLock(settings.charts_dir / ".worker.lock")
        self._stop = threading.Event()
        self._last_publication_at: float | None = None
        self._last_publication_action: str | None = None
        self._last_retention_at: float | None = None
        self._last_error_at: float | None = None
        self._publication_error_at: float | None = None
        self._retention_error_at: float | None = None
        self._fatal_heartbeat_error: Exception | None = None
        self._status_lock = threading.RLock()
        self._state: WorkerState = "starting"

    def request_stop(self) -> None:
        self._stop.set()

    def publication_once(self) -> PublicationResult:
        with self.instance_lock:
            # A one-shot administrative process is not the daemon and must never
            # create a lease that can make the HTTP process appear ready.
            self.status_store.remove()
            try:
                self.coordinator.initialize()
                return self.coordinator.publication_tick()
            finally:
                self.status_store.remove()

    def run_forever(self) -> None:
        with self.instance_lock:
            self._set_state("starting")
            heartbeat = threading.Thread(
                target=self._heartbeat_loop,
                name="feedback-worker-heartbeat",
                daemon=True,
            )
            heartbeat.start()
            failure: BaseException | None = None
            cleanup_error: OSError | None = None
            try:
                self._run_with_watchdog(
                    self.coordinator.initialize,
                    operation_name="inizializzazione",
                )
                now = time.monotonic()
                next_publication = now + self._initial_publication_delay()
                next_retention = now + self.settings.retention_interval_seconds
                self._set_idle_preserving_errors()
                while not self._stop.is_set():
                    now = time.monotonic()
                    if now >= next_retention:
                        succeeded = self._run_with_watchdog(
                            self._run_retention,
                            operation_name="retention",
                        )
                        delay = (
                            self.settings.retention_interval_seconds
                            if succeeded
                            else self._retry_delay(self.settings.retention_interval_seconds)
                        )
                        next_retention = time.monotonic() + delay
                    if self._stop.is_set():
                        break
                    now = time.monotonic()
                    if now >= next_publication:
                        succeeded = self._run_with_watchdog(
                            self._run_publication,
                            operation_name="pubblicazione",
                        )
                        delay = (
                            self.settings.publish_interval_seconds
                            if succeeded
                            else self._retry_delay(self.settings.publish_interval_seconds)
                        )
                        next_publication = time.monotonic() + delay
                    timeout = max(
                        0.05,
                        min(next_publication, next_retention) - time.monotonic(),
                    )
                    self._stop.wait(timeout)
            except BaseException as exc:
                failure = exc
            finally:
                self._stop.set()
                heartbeat.join(timeout=self.settings.worker_heartbeat_seconds + 1)
                try:
                    self.status_store.remove()
                except OSError as exc:
                    cleanup_error = exc

            fatal_heartbeat_error = self._get_fatal_heartbeat_error()
            if fatal_heartbeat_error is not None:
                raise RuntimeError("Heartbeat del worker feedback non scrivibile") from fatal_heartbeat_error
            if failure is not None:
                raise failure
            if heartbeat.is_alive():
                raise RuntimeError("Thread heartbeat del worker feedback non arrestabile")
            if cleanup_error is not None:
                raise RuntimeError("Lease del worker feedback non rimovibile") from cleanup_error

    def _initial_publication_delay(self) -> float:
        """Do not let a restart postpone an already due publication."""

        reference: float | None = None
        manifest = self.publisher.load_current_manifest()
        if manifest is not None:
            try:
                reference = datetime.fromisoformat(
                    manifest.generated_at.replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                reference = None
        if reference is None:
            reference = self.store.oldest_created_at()
        if reference is None:
            return float(self.settings.publish_interval_seconds)
        elapsed = max(0.0, time.time() - reference)
        return max(0.0, self.settings.publish_interval_seconds - elapsed)

    def _run_retention(self) -> bool:
        self._set_state("retention")
        try:
            self.coordinator.retention_tick()
            self._last_retention_at = time.time()
            self._record_job_success("retention")
            return True
        except Exception:
            self._record_job_failure("retention")
            LOGGER.exception("Retention periodica feedback fallita")
            return False

    def _run_publication(self) -> bool:
        self._set_state("publishing")
        try:
            result = self.coordinator.publication_tick()
            self._last_publication_at = time.time()
            self._last_publication_action = result.action
            self._record_job_success("publication")
            return True
        except SnapshotInvalidatedError:
            self._set_idle_preserving_errors()
            LOGGER.info("Pubblicazione rinviata per una retention concorrente")
            return False
        except Exception:
            self._record_job_failure("publication")
            LOGGER.exception("Pubblicazione periodica dei grafici fallita")
            return False

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.settings.worker_heartbeat_seconds):
            try:
                self._write_status()
            except Exception as exc:
                with self._status_lock:
                    self._fatal_heartbeat_error = exc
                    self._last_error_at = time.time()
                    self._state = "error"
                self._stop.set()
                return

    def _run_with_watchdog(
        self,
        operation: Callable[[], _JobResult],
        *,
        operation_name: str,
    ) -> _JobResult:
        result: Future[_JobResult] = Future()

        def invoke() -> None:
            try:
                result.set_result(operation())
            except BaseException as exc:
                result.set_exception(exc)

        thread = threading.Thread(
            target=invoke,
            name=f"feedback-worker-{operation_name}",
            daemon=True,
        )
        thread.start()
        deadline = time.monotonic() + self.settings.worker_job_timeout_seconds
        while not result.done():
            fatal_heartbeat_error = self._get_fatal_heartbeat_error()
            if fatal_heartbeat_error is not None:
                raise RuntimeError(
                    "Heartbeat del worker feedback non scrivibile"
                ) from fatal_heartbeat_error
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._stop.set()
                raise RuntimeError(
                    f"Timeout del worker feedback durante {operation_name}"
                )
            thread.join(timeout=min(0.25, remaining))
        return result.result()

    def _record_job_failure(self, job: str) -> None:
        failed_at = time.time()
        with self._status_lock:
            if job == "publication":
                self._publication_error_at = failed_at
            else:
                self._retention_error_at = failed_at
            self._last_error_at = max(
                value
                for value in (
                    self._publication_error_at,
                    self._retention_error_at,
                )
                if value is not None
            )
            self._state = "error"
        self._write_status()

    def _record_job_success(self, job: str) -> None:
        with self._status_lock:
            if job == "publication":
                self._publication_error_at = None
            else:
                self._retention_error_at = None
        self._set_idle_preserving_errors()

    def _set_idle_preserving_errors(self) -> None:
        with self._status_lock:
            errors = [
                value
                for value in (
                    self._publication_error_at,
                    self._retention_error_at,
                )
                if value is not None
            ]
            self._last_error_at = max(errors) if errors else None
            self._state = "error" if errors else "idle"
        self._write_status()

    def _get_fatal_heartbeat_error(self) -> Exception | None:
        with self._status_lock:
            return self._fatal_heartbeat_error

    def _retry_delay(self, configured_interval: int) -> float:
        return min(
            float(configured_interval),
            max(5.0, float(self.settings.worker_heartbeat_seconds * 2)),
        )

    def _set_state(self, state: WorkerState) -> None:
        with self._status_lock:
            self._state = state
        self._write_status()

    def _write_status(self) -> None:
        with self._status_lock:
            self.status_store.write(
                WorkerStatus(
                    schema_version=1,
                    state=self._state,
                    updated_at=time.time(),
                    last_publication_at=self._last_publication_at,
                    last_publication_action=self._last_publication_action,
                    last_retention_at=self._last_retention_at,
                    last_error_at=self._last_error_at,
                )
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Worker periodico TestLogica Feedback")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="esegue subito un singolo tick e termina (uso amministrativo)",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="verifica che l'heartbeat del worker sia recente",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = load_settings()
    if arguments.check:
        status_store = WorkerStatusStore(settings.charts_dir / "worker-status.json")
        return int(
            not status_store.is_fresh(
                maximum_age_seconds=settings.worker_stale_seconds,
            )
        )

    worker = PeriodicFeedbackWorker(settings)
    if arguments.once:
        result = worker.publication_once()
        LOGGER.info(
            "Tick feedback concluso: action=%s receipts=%s",
            result.action,
            result.receipt_count,
        )
        return 0

    def stop_worker(_signum: int, _frame: object) -> None:
        worker.request_stop()

    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
