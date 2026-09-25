"""Environment-backed configuration for the dedicated feedback service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


def _integer(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} deve essere un numero intero") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} deve essere compreso tra {minimum} e {maximum}")
    return value


def _worker_mode() -> Literal["external", "embedded"]:
    value = os.getenv("FEEDBACK_WORKER_MODE", "external").strip().casefold()
    if value == "external":
        return "external"
    if value == "embedded":
        return "embedded"
    raise RuntimeError("FEEDBACK_WORKER_MODE deve essere external oppure embedded")


@dataclass(frozen=True, slots=True)
class FeedbackSettings:
    """All paths are explicit so chart generation never depends on the CWD."""

    storage_dir: Path
    charts_dir: Path
    retention_days: int = 365
    max_body_bytes: int = 2 * 1024 * 1024
    max_receipts: int = 100_000
    max_storage_bytes: int = 1_073_741_824
    min_free_bytes: int = 67_108_864
    minimum_aggregate_sessions: int = 10
    snapshots_to_keep: int = 3
    publish_interval_seconds: int = 86_400
    retention_interval_seconds: int = 3_600
    worker_heartbeat_seconds: int = 15
    worker_stale_seconds: int = 60
    worker_job_timeout_seconds: int = 900
    worker_mode: Literal["external", "embedded"] = "external"


def load_settings() -> FeedbackSettings:
    heartbeat = _integer(
        "FEEDBACK_WORKER_HEARTBEAT_SECONDS",
        15,
        minimum=1,
        maximum=3_600,
    )
    stale = _integer(
        "FEEDBACK_WORKER_STALE_SECONDS",
        60,
        minimum=3,
        maximum=86_400,
    )
    if stale <= heartbeat * 2:
        raise RuntimeError(
            "FEEDBACK_WORKER_STALE_SECONDS deve superare il doppio dell'heartbeat"
        )
    return FeedbackSettings(
        storage_dir=Path(os.getenv("FEEDBACK_STORAGE_DIR", "data/receipts")).resolve(),
        charts_dir=Path(os.getenv("FEEDBACK_CHARTS_DIR", "data/charts")).resolve(),
        retention_days=_integer("FEEDBACK_RETENTION_DAYS", 365, minimum=1, maximum=3_650),
        max_body_bytes=_integer(
            "FEEDBACK_MAX_BODY_BYTES",
            2 * 1024 * 1024,
            minimum=1_024,
            maximum=2 * 1024 * 1024,
        ),
        max_receipts=_integer(
            "FEEDBACK_MAX_RECEIPTS",
            100_000,
            minimum=1,
            maximum=100_000_000,
        ),
        max_storage_bytes=_integer(
            "FEEDBACK_MAX_STORAGE_BYTES",
            1_073_741_824,
            minimum=1,
            maximum=1_099_511_627_776,
        ),
        min_free_bytes=_integer(
            "FEEDBACK_MIN_FREE_BYTES",
            67_108_864,
            minimum=0,
            maximum=1_099_511_627_776,
        ),
        minimum_aggregate_sessions=_integer(
            "FEEDBACK_MIN_AGGREGATE_SESSIONS",
            10,
            minimum=2,
            maximum=10_000,
        ),
        snapshots_to_keep=_integer("FEEDBACK_SNAPSHOTS_TO_KEEP", 3, minimum=2, maximum=100),
        publish_interval_seconds=_integer(
            "FEEDBACK_PUBLISH_INTERVAL_SECONDS",
            86_400,
            minimum=1,
            maximum=31_536_000,
        ),
        retention_interval_seconds=_integer(
            "FEEDBACK_RETENTION_INTERVAL_SECONDS",
            3_600,
            minimum=1,
            maximum=86_400,
        ),
        worker_heartbeat_seconds=heartbeat,
        worker_stale_seconds=stale,
        worker_job_timeout_seconds=_integer(
            "FEEDBACK_WORKER_JOB_TIMEOUT_SECONDS",
            900,
            minimum=5,
            maximum=86_400,
        ),
        worker_mode=_worker_mode(),
    )
