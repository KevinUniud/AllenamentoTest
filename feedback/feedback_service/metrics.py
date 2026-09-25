"""PII-free in-process counters rendered in Prometheus text format."""

from __future__ import annotations

import threading
from collections import Counter


class ServiceMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._submissions: Counter[str] = Counter()
        self._payload_bytes = 0

    def submission(self, outcome: str, *, payload_bytes: int = 0) -> None:
        with self._lock:
            self._submissions[outcome] += 1
            if outcome in {"accepted", "idempotent"}:
                self._payload_bytes += max(0, payload_bytes)

    def snapshot(self) -> tuple[dict[str, int], int]:
        with self._lock:
            return dict(self._submissions), self._payload_bytes

    def render(
        self,
        *,
        receipt_count: int,
        storage_bytes: int,
        max_receipts: int,
        max_storage_bytes: int,
        snapshot_available: bool,
        worker_fresh: bool,
    ) -> str:
        submissions, payload_bytes = self.snapshot()
        lines = [
            "# HELP testlogica_feedback_submissions_total Submission outcomes.",
            "# TYPE testlogica_feedback_submissions_total counter",
        ]
        for outcome in sorted(submissions):
            safe = outcome.replace('"', "")
            lines.append(
                f'testlogica_feedback_submissions_total{{outcome="{safe}"}} '
                f"{submissions[outcome]}"
            )
        lines.extend(
            [
                "# TYPE testlogica_feedback_payload_bytes_total counter",
                f"testlogica_feedback_payload_bytes_total {payload_bytes}",
                "# TYPE testlogica_feedback_receipts gauge",
                f"testlogica_feedback_receipts {receipt_count}",
                "# TYPE testlogica_feedback_storage_bytes gauge",
                f"testlogica_feedback_storage_bytes {storage_bytes}",
                "# TYPE testlogica_feedback_receipts_limit gauge",
                f"testlogica_feedback_receipts_limit {max_receipts}",
                "# TYPE testlogica_feedback_storage_bytes_limit gauge",
                f"testlogica_feedback_storage_bytes_limit {max_storage_bytes}",
                "# TYPE testlogica_feedback_snapshot_available gauge",
                f"testlogica_feedback_snapshot_available {int(snapshot_available)}",
                "# TYPE testlogica_feedback_worker_fresh gauge",
                f"testlogica_feedback_worker_fresh {int(worker_fresh)}",
            ]
        )
        return "\n".join(lines) + "\n"
