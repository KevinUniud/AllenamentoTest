"""Small, non-root administration CLI for the private feedback data directory."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from pathlib import Path

from feedback_service.config import FeedbackSettings, load_settings
from feedback_service.coordinator import FeedbackCoordinator
from feedback_service.snapshots import ChartSnapshotPublisher
from feedback_service.storage import FeedbackStorageError, FeedbackStore

LOGGER = logging.getLogger(__name__)


def _runtime(settings: FeedbackSettings) -> tuple[
    FeedbackStore,
    ChartSnapshotPublisher,
    FeedbackCoordinator,
]:
    store = FeedbackStore(
        settings.storage_dir,
        retention_days=settings.retention_days,
        max_receipts=settings.max_receipts,
        max_storage_bytes=settings.max_storage_bytes,
        min_free_bytes=settings.min_free_bytes,
    )
    publisher = ChartSnapshotPublisher(
        settings.charts_dir,
        minimum_aggregate_sessions=settings.minimum_aggregate_sessions,
        snapshots_to_keep=settings.snapshots_to_keep,
    )
    return store, publisher, FeedbackCoordinator(settings, store, publisher)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Amministrazione locale dei dati TestLogica Feedback (senza root)."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="mostra quote, ricevute e stato dello snapshot")
    commands.add_parser("check", help="verifica database e directory dei grafici")
    commands.add_parser("purge", help="applica subito la retention configurata")
    backup = commands.add_parser("backup", help="crea un backup SQLite consistente")
    backup.add_argument("destination", type=Path)
    restore = commands.add_parser(
        "restore",
        help="ripristina un backup solo se il database attivo non esiste",
    )
    restore.add_argument("source", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    settings = load_settings()
    store, publisher, coordinator = _runtime(settings)
    try:
        if arguments.command == "status":
            statistics = store.observe_statistics()
            manifest = publisher.load_current_manifest()
            print(
                json.dumps(
                    {
                        "max_receipts": settings.max_receipts,
                        "max_storage_bytes": settings.max_storage_bytes,
                        "receipt_count": statistics.receipt_count,
                        "snapshot_generation": (
                            None if manifest is None else str(manifest.generation_id)
                        ),
                        "storage_bytes": statistics.byte_count,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if arguments.command == "check":
            coordinator.initialize()
            integrity = publisher.current_snapshot_integrity()
            ready = store.check_ready() and publisher.check_ready() and integrity != "invalid"
            print(json.dumps({"ready": ready, "snapshot_integrity": integrity}, sort_keys=True))
            return int(not ready)
        if arguments.command == "purge":
            deleted = coordinator.initialize()
            deleted += coordinator.retention_tick()
            print(json.dumps({"purged_receipts": deleted}, sort_keys=True))
            return 0
        if arguments.command == "backup":
            coordinator.initialize()
            destination = store.backup_to(arguments.destination)
            print(json.dumps({"backup": str(destination)}, ensure_ascii=False, sort_keys=True))
            return 0
        if arguments.command == "restore":
            destination = store.restore_from(arguments.source)
            print(json.dumps({"restored": str(destination)}, ensure_ascii=False, sort_keys=True))
            return 0

        raise RuntimeError("Comando amministrativo non gestito")
    except (FeedbackStorageError, OSError, ValueError) as exc:
        LOGGER.error("Operazione amministrativa non riuscita: %s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
