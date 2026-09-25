from __future__ import annotations

from uuid import uuid4

from feedback_service.snapshots import ChartSnapshotPublisher


def test_publish_removes_only_orphaned_private_staging(tmp_path) -> None:
    charts = tmp_path / "charts"
    publisher = ChartSnapshotPublisher(
        charts,
        minimum_aggregate_sessions=2,
        snapshots_to_keep=2,
    )
    publisher.initialize()
    orphan = charts / f".staging-{uuid4()}-orphan"
    orphan.mkdir()
    (orphan / "partial.png").write_bytes(b"partial")
    unrelated = charts / ".staging-not-a-generation"
    unrelated.mkdir()

    assert publisher.publish([]) is None

    assert not orphan.exists()
    assert unrelated.is_dir()
