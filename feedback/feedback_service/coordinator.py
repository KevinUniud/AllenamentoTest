"""Synchronous retention and publication orchestration shared by API and worker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from feedback_service.config import FeedbackSettings
from feedback_service.snapshots import ChartSnapshotPublisher
from feedback_service.storage import FeedbackStore

PublicationAction = Literal["published", "unchanged", "insufficient"]


@dataclass(frozen=True, slots=True)
class PublicationResult:
    action: PublicationAction
    receipt_count: int
    purged_receipts: int
    generation_id: str | None = None


class FeedbackCoordinator:
    """Own the operations that may mutate both receipts and chart snapshots."""

    def __init__(
        self,
        settings: FeedbackSettings,
        store: FeedbackStore,
        publisher: ChartSnapshotPublisher,
    ) -> None:
        self.settings = settings
        self.store = store
        self.publisher = publisher

    def initialize(self) -> int:
        purged = self.store.initialize()
        if purged or self.store.compaction_required():
            self.store.compact()
        self.publisher.initialize()
        dataset = self.store.snapshot_dataset()
        current = self.publisher.load_current_manifest()
        integrity = self.publisher.current_snapshot_integrity()
        if (
            purged
            or current is None
            or integrity == "invalid"
            or len(dataset.payloads) < self.settings.minimum_aggregate_sessions
            or not self.publisher.current_snapshot_matches(
                dataset.source_token,
                len(dataset.payloads),
            )
        ):
            self.publisher.invalidate()
        return purged

    def retention_tick(self) -> int:
        deleted = self.store.purge_expired()
        compaction_required = bool(deleted) or self.store.compaction_required()
        if compaction_required:
            self.publisher.invalidate()
            self.store.compact()
        return deleted

    def publication_tick(self) -> PublicationResult:
        purged = self.retention_tick()
        expected_epoch = self.publisher.capture_epoch()
        dataset = self.store.snapshot_dataset()
        payloads = dataset.payloads
        current = self.publisher.load_current_manifest()
        integrity = self.publisher.current_snapshot_integrity()
        invalidated = False
        if integrity == "invalid":
            expected_epoch = self.publisher.invalidate_if_epoch(expected_epoch)
            current = None
            invalidated = True
        if len(payloads) < self.settings.minimum_aggregate_sessions:
            if not invalidated:
                self.publisher.invalidate_if_epoch(expected_epoch)
            return PublicationResult(
                action="insufficient",
                receipt_count=len(payloads),
                purged_receipts=purged,
            )
        if current is None and not invalidated:
            expected_epoch = self.publisher.invalidate_if_epoch(expected_epoch)
        if (
            current is not None
            and integrity == "valid"
            and self.publisher.current_snapshot_matches(
                dataset.source_token,
                len(payloads),
            )
        ):
            return PublicationResult(
                action="unchanged",
                receipt_count=len(payloads),
                purged_receipts=purged,
                generation_id=str(current.generation_id),
            )
        manifest = self.publisher.publish(
            payloads,
            expected_epoch,
            source_token=dataset.source_token,
        )
        if manifest is None:
            return PublicationResult(
                action="insufficient",
                receipt_count=len(payloads),
                purged_receipts=purged,
            )
        return PublicationResult(
            action="published",
            receipt_count=len(payloads),
            purged_receipts=purged,
            generation_id=str(manifest.generation_id),
        )
