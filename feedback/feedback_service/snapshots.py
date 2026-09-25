"""Versioned, atomic publication of chart snapshots and their manifest."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from feedback_service.chart_generator import CHART_SPECS, ChartArtifact, ChartGenerator
from feedback_service.data_processor import DataProcessor
from feedback_service.filelock import exclusive_file_lock
from feedback_service.schemas import ChartManifest, ChartManifestEntry

LOGGER = logging.getLogger(__name__)
_SAFE_SEGMENT = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SAFE_PNG = re.compile(r"^[a-z][a-z0-9_-]{0,127}\.png$")
_SOURCE_TOKEN = re.compile(r"^[0-9a-f]{64}$")
_STAGING_DIRECTORY = re.compile(
    r"^\.staging-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-.+$"
)
SnapshotIntegrity = Literal["absent", "valid", "invalid"]


class SnapshotInvalidatedError(RuntimeError):
    """Raised when an in-flight render became stale before publication."""


@dataclass(frozen=True, slots=True)
class _SnapshotSourceState:
    generation_id: UUID
    session_count: int
    source_token: str


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ChartSnapshotPublisher:
    """Generate privately, then expose only an immutable allow-listed snapshot."""

    def __init__(
        self,
        charts_dir: Path,
        *,
        minimum_aggregate_sessions: int,
        snapshots_to_keep: int = 3,
    ) -> None:
        if minimum_aggregate_sessions < 2:
            raise ValueError("minimum_aggregate_sessions deve essere almeno 2")
        self.charts_dir = charts_dir.resolve()
        self.snapshots_dir = self.charts_dir / "snapshots"
        self.current_manifest_path = self.charts_dir / "manifest.json"
        # Deliberately private: the source token is never part of the public
        # chart manifest or of an HTTP response.
        self._source_state_path = self.charts_dir / ".snapshot-source.json"
        self._epoch_path = self.charts_dir / ".snapshot-epoch"
        self._state_lock_path = self.charts_dir / ".snapshot-state.lock"
        self._publish_lock_path = self.charts_dir / ".snapshot-publish.lock"
        self.minimum_aggregate_sessions = minimum_aggregate_sessions
        if snapshots_to_keep < 1:
            raise ValueError("snapshots_to_keep deve essere almeno 1")
        self.snapshots_to_keep = snapshots_to_keep
        self._lock = threading.RLock()
        self._publish_lock = threading.Lock()

    def initialize(self) -> None:
        with self._lock:
            self.charts_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.snapshots_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            with exclusive_file_lock(self._state_lock_path):
                if not self._epoch_path.exists():
                    self._write_epoch_locked(0)
                else:
                    self._read_epoch_locked()

    def check_ready(self) -> bool:
        with self._lock:
            probe: Path | None = None
            try:
                self.initialize()
                descriptor, name = tempfile.mkstemp(prefix=".ready-", dir=self.charts_dir)
                os.close(descriptor)
                probe = Path(name)
                probe.unlink()
                return True
            except OSError:
                if probe is not None:
                    probe.unlink(missing_ok=True)
                return False

    def capture_epoch(self) -> int:
        """Return a token invalidated whenever the source dataset shrinks."""
        self.initialize()
        with self._lock, exclusive_file_lock(self._state_lock_path):
            return self._read_epoch_locked()

    def publish(
        self,
        payloads: list[dict[str, Any]],
        expected_epoch: int | None = None,
        *,
        source_token: str | None = None,
    ) -> ChartManifest | None:
        """Create all charts in private staging and atomically publish safe assets."""
        effective_source_token = (
            self._source_token_for_payloads(payloads)
            if source_token is None
            else self._validate_source_token(source_token)
        )
        self.initialize()
        with self._publish_lock, exclusive_file_lock(self._publish_lock_path):
            self._remove_orphaned_staging_locked()
            return self._publish_serialized(
                payloads,
                expected_epoch=expected_epoch,
                source_token=effective_source_token,
            )

    def _remove_orphaned_staging_locked(self) -> None:
        """Remove private render trees left by a killed previous publisher.

        The caller owns the cross-process publish lock, so a matching directory
        cannot belong to another live rendering process.
        """

        for path in self.charts_dir.iterdir():
            if _STAGING_DIRECTORY.fullmatch(path.name) is None:
                continue
            if path.is_symlink() or not path.is_dir():
                LOGGER.warning("Staging feedback non valido ignorato: %s", path.name)
                continue
            shutil.rmtree(path)

    def _publish_serialized(
        self,
        payloads: list[dict[str, Any]],
        *,
        expected_epoch: int | None,
        source_token: str,
    ) -> ChartManifest | None:
        with self._lock, exclusive_file_lock(self._state_lock_path):
            current_epoch = self._read_epoch_locked()
            if expected_epoch is not None and expected_epoch != current_epoch:
                raise SnapshotInvalidatedError(
                    "Dataset feedback invalidato prima della generazione"
                )
            if len(payloads) < self.minimum_aggregate_sessions:
                self._invalidate_locked()
                return None
            current = self.load_current_manifest()
            if current is not None and len(payloads) < current.session_count:
                self._invalidate_locked()
                current = None
            if current is not None:
                if self._current_snapshot_integrity_locked() != "valid":
                    self._invalidate_locked()
                    current = None
                elif self._current_source_matches_locked(
                    current,
                    source_token=source_token,
                    session_count=len(payloads),
                ):
                    return current
            publish_epoch = self._read_epoch_locked()
        generation_id = uuid4()
        work = Path(tempfile.mkdtemp(prefix=f".staging-{generation_id}-", dir=self.charts_dir))
        generated_dir = work / "generated"
        public_dir = work / "public"
        try:
            processor = DataProcessor(payloads)
            processor.extract_metrics()
            artifacts = ChartGenerator(
                processor,
                generated_dir,
                minimum_aggregate_sessions=self.minimum_aggregate_sessions,
            ).generate_all_charts()
            public_dir.mkdir(mode=0o700)
            entries = self._copy_public_assets(artifacts, public_dir, generation_id)
            manifest = ChartManifest(
                generation_id=generation_id,
                generated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                session_count=len(payloads),
                charts=entries,
            )
            manifest_data = manifest.model_dump(mode="json")
            self._write_json(public_dir / "manifest.json", manifest_data)

            with self._lock, exclusive_file_lock(self._state_lock_path):
                if publish_epoch != self._read_epoch_locked():
                    raise SnapshotInvalidatedError("Snapshot invalidato durante la generazione")
                final_dir = self.snapshots_dir / str(generation_id)
                os.replace(public_dir, final_dir)
                self._sync_directory(self.snapshots_dir)
                self._atomic_current_manifest(manifest_data)
                self._atomic_source_state(
                    _SnapshotSourceState(
                        generation_id=generation_id,
                        session_count=len(payloads),
                        source_token=source_token,
                    )
                )
                self._prune_snapshots(current=generation_id)
            return manifest
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def invalidate(self) -> None:
        """Immediately make every previously generated snapshot unreachable."""
        self.initialize()
        with self._lock, exclusive_file_lock(self._state_lock_path):
            self._invalidate_locked()

    def invalidate_if_epoch(self, expected_epoch: int) -> int:
        """Invalidate only if no concurrent retention changed the dataset."""
        self.initialize()
        with self._lock, exclusive_file_lock(self._state_lock_path):
            if expected_epoch != self._read_epoch_locked():
                raise SnapshotInvalidatedError(
                    "Dataset feedback invalidato durante la raccolta"
                )
            self._invalidate_locked()
            return self._read_epoch_locked()

    def _invalidate_locked(self) -> None:
        self._write_epoch_locked(self._read_epoch_locked() + 1)
        self.current_manifest_path.unlink(missing_ok=True)
        self._source_state_path.unlink(missing_ok=True)
        if self.snapshots_dir.exists():
            for path in self.snapshots_dir.iterdir():
                if path.is_dir() and self._canonical_generation_id(path.name) is not None:
                    shutil.rmtree(path)
        if self.charts_dir.exists():
            self._sync_directory(self.charts_dir)
        if self.snapshots_dir.exists():
            self._sync_directory(self.snapshots_dir)

    def _copy_public_assets(
        self,
        artifacts: list[ChartArtifact],
        public_dir: Path,
        generation_id: UUID,
    ) -> list[ChartManifestEntry]:
        entries: list[ChartManifestEntry] = []
        for artifact in artifacts:
            destination_dir = public_dir / artifact.spec.category
            destination_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination = destination_dir / artifact.spec.filename
            shutil.copyfile(artifact.path, destination)
            destination.chmod(0o600)
            digest = file_sha256(destination)
            entries.append(
                ChartManifestEntry(
                    id=artifact.spec.chart_id,
                    category=artifact.spec.category,
                    filename=artifact.spec.filename,
                    url=(
                        f"/api/feedback/charts/{generation_id}/"
                        f"{artifact.spec.category}/{artifact.spec.filename}"
                    ),
                    sha256=digest,
                    status=artifact.status,
                )
            )
        return entries

    def load_current_manifest(self) -> ChartManifest | None:
        with self._lock:
            if (
                not self.current_manifest_path.is_file()
                or self.current_manifest_path.is_symlink()
            ):
                return None
            try:
                return self._read_manifest(self.current_manifest_path)
            except (OSError, json.JSONDecodeError, ValueError):
                LOGGER.warning("Manifest corrente illeggibile ignorato")
                return None

    def load_generation_manifest(self, generation_id: str) -> ChartManifest | None:
        canonical = self._canonical_generation_id(generation_id)
        if canonical is None:
            return None
        snapshot_root = self.snapshots_dir / canonical
        if not snapshot_root.is_dir() or snapshot_root.is_symlink():
            return None
        snapshot = snapshot_root.resolve()
        if snapshot.parent != self.snapshots_dir:
            return None
        path = snapshot / "manifest.json"
        if not path.is_file() or path.is_symlink():
            return None
        try:
            manifest = self._read_manifest(path)
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        return manifest if str(manifest.generation_id) == canonical else None

    def current_snapshot_integrity(self) -> SnapshotIntegrity:
        """Validate the complete current allow-list and every published hash."""
        self.initialize()
        with self._lock, exclusive_file_lock(self._state_lock_path):
            return self._current_snapshot_integrity_locked()

    def current_snapshot_matches(self, source_token: str, session_count: int) -> bool:
        """Return whether the private source identity matches the current charts."""

        validated_token = self._validate_source_token(source_token)
        if session_count < 0:
            raise ValueError("Conteggio dataset snapshot non valido")
        self.initialize()
        with self._lock, exclusive_file_lock(self._state_lock_path):
            current = self.load_current_manifest()
            if current is None or self._current_snapshot_integrity_locked() != "valid":
                return False
            return self._current_source_matches_locked(
                current,
                source_token=validated_token,
                session_count=session_count,
            )

    def _current_snapshot_integrity_locked(self) -> SnapshotIntegrity:
        if not self.current_manifest_path.exists():
            return "absent"
        if (
            not self.current_manifest_path.is_file()
            or self.current_manifest_path.is_symlink()
        ):
            return "invalid"
        try:
            current = self._read_manifest(self.current_manifest_path)
        except (OSError, json.JSONDecodeError, ValueError):
            return "invalid"

        generation_id = str(current.generation_id)
        snapshot_root = self.snapshots_dir / generation_id
        manifest_path = snapshot_root / "manifest.json"
        if (
            not snapshot_root.is_dir()
            or snapshot_root.is_symlink()
            or not manifest_path.is_file()
            or manifest_path.is_symlink()
        ):
            return "invalid"
        snapshot = snapshot_root.resolve()
        if snapshot.parent != self.snapshots_dir:
            return "invalid"
        try:
            stored = self._read_manifest(manifest_path)
        except (OSError, json.JSONDecodeError, ValueError):
            return "invalid"
        if stored != current:
            return "invalid"
        source_state = self._read_source_state_locked()
        if (
            source_state is None
            or source_state.generation_id != current.generation_id
            or source_state.session_count != current.session_count
        ):
            return "invalid"

        expected_specs = {spec.chart_id: spec for spec in CHART_SPECS}
        if (
            len(current.charts) != len(expected_specs)
            or {entry.id for entry in current.charts} != set(expected_specs)
        ):
            return "invalid"
        for entry in current.charts:
            spec = expected_specs[entry.id]
            expected_url = (
                f"/api/feedback/charts/{generation_id}/"
                f"{spec.category}/{spec.filename}"
            )
            if (
                entry.category != spec.category
                or entry.filename != spec.filename
                or entry.url != expected_url
            ):
                return "invalid"
            raw_path = snapshot / entry.category / entry.filename
            if raw_path.is_symlink():
                return "invalid"
            path = raw_path.resolve()
            if path.parent != snapshot / entry.category or not path.is_file():
                return "invalid"
            try:
                if file_sha256(path) != entry.sha256:
                    return "invalid"
            except OSError:
                return "invalid"
        return "valid"

    def resolve_asset(self, generation_id: str, category: str, filename: str) -> Path | None:
        """Resolve only assets explicitly listed in that immutable manifest."""
        canonical = self._canonical_generation_id(generation_id)
        if canonical is None or _SAFE_SEGMENT.fullmatch(category) is None or _SAFE_PNG.fullmatch(filename) is None:
            return None
        manifest = self.load_generation_manifest(canonical)
        if manifest is None:
            return None
        expected = next(
            (
                entry
                for entry in manifest.charts
                if entry.category == category and entry.filename == filename
            ),
            None,
        )
        if expected is None:
            return None
        snapshot = (self.snapshots_dir / canonical).resolve()
        raw_path = snapshot / category / filename
        if raw_path.is_symlink():
            return None
        path = raw_path.resolve()
        if path.parent != snapshot / category or not path.is_file():
            return None
        try:
            if file_sha256(path) != expected.sha256:
                LOGGER.error(
                    "Hash non valido per asset grafico (%s/%s/%s)",
                    canonical,
                    category,
                    filename,
                )
                return None
        except OSError:
            return None
        return path

    def read_asset(self, generation_id: str, category: str, filename: str) -> bytes | None:
        """Read and verify an asset while prune/invalidate cannot remove it."""
        with self._lock:
            path = self.resolve_asset(generation_id, category, filename)
            if path is None:
                return None
            try:
                content = path.read_bytes()
            except OSError:
                return None
            manifest = self.load_generation_manifest(generation_id)
            if manifest is None:
                return None
            expected = next(
                (
                    entry.sha256
                    for entry in manifest.charts
                    if entry.category == category and entry.filename == filename
                ),
                None,
            )
            if expected is None or hashlib.sha256(content).hexdigest() != expected:
                return None
            return content

    @staticmethod
    def _canonical_generation_id(value: str) -> str | None:
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError):
            return None
        canonical = str(parsed)
        return canonical if parsed.version == 4 and value == canonical else None

    @staticmethod
    def _read_manifest(path: Path) -> ChartManifest:
        # JSON mode intentionally accepts the RFC-formatted UUID string while
        # preserving strict Python-mode validation everywhere else.
        return ChartManifest.model_validate_json(path.read_bytes())

    def _atomic_current_manifest(self, data: dict[str, Any]) -> None:
        descriptor, name = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=self.charts_dir)
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.current_manifest_path)
            self._sync_directory(self.charts_dir)
        finally:
            temporary.unlink(missing_ok=True)

    def _atomic_source_state(self, state: _SnapshotSourceState) -> None:
        data = {
            "schema_version": 1,
            "generation_id": str(state.generation_id),
            "session_count": state.session_count,
            "source_token": state.source_token,
        }
        descriptor, name = tempfile.mkstemp(
            prefix=".snapshot-source-",
            suffix=".tmp",
            dir=self.charts_dir,
        )
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._source_state_path)
            self._sync_directory(self.charts_dir)
        finally:
            temporary.unlink(missing_ok=True)

    def _read_source_state_locked(self) -> _SnapshotSourceState | None:
        if not self._source_state_path.is_file() or self._source_state_path.is_symlink():
            return None
        try:
            raw = json.loads(self._source_state_path.read_bytes())
            if not isinstance(raw, dict) or set(raw) != {
                "schema_version",
                "generation_id",
                "session_count",
                "source_token",
            }:
                return None
            if raw["schema_version"] != 1:
                return None
            generation_id = UUID(raw["generation_id"])
            if generation_id.version != 4 or str(generation_id) != raw["generation_id"]:
                return None
            session_count = raw["session_count"]
            if (
                isinstance(session_count, bool)
                or not isinstance(session_count, int)
                or session_count < self.minimum_aggregate_sessions
            ):
                return None
            source_token = self._validate_source_token(raw["source_token"])
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return None
        return _SnapshotSourceState(
            generation_id=generation_id,
            session_count=session_count,
            source_token=source_token,
        )

    def _current_source_matches_locked(
        self,
        current: ChartManifest,
        *,
        source_token: str,
        session_count: int,
    ) -> bool:
        source_state = self._read_source_state_locked()
        return (
            source_state is not None
            and source_state.generation_id == current.generation_id
            and source_state.session_count == session_count == current.session_count
            and source_state.source_token == source_token
        )

    @staticmethod
    def _validate_source_token(value: str) -> str:
        if not isinstance(value, str) or _SOURCE_TOKEN.fullmatch(value) is None:
            raise ValueError("Token sorgente snapshot non valido")
        return value

    @staticmethod
    def _source_token_for_payloads(payloads: list[dict[str, Any]]) -> str:
        """Compatibility token for callers without a persistent store identity."""

        digest = hashlib.sha256(b"testlogica-feedback-direct-snapshot-v1\0")
        for payload in payloads:
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return digest.hexdigest()

    def _read_epoch_locked(self) -> int:
        try:
            value = int(self._epoch_path.read_text(encoding="ascii").strip())
        except (OSError, UnicodeError, ValueError) as exc:
            raise OSError("Epoch degli snapshot non valida") from exc
        if value < 0:
            raise OSError("Epoch degli snapshot non valida")
        return value

    def _write_epoch_locked(self, value: int) -> None:
        descriptor, name = tempfile.mkstemp(
            prefix=".snapshot-epoch-",
            suffix=".tmp",
            dir=self.charts_dir,
        )
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                stream.write(f"{value}\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._epoch_path)
            self._sync_directory(self.charts_dir)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8") as stream:
            path.chmod(0o600)
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _prune_snapshots(self, *, current: UUID) -> None:
        candidates: list[Path] = []
        for path in self.snapshots_dir.iterdir():
            if not path.is_dir() or self._canonical_generation_id(path.name) is None:
                continue
            candidates.append(path)
        keep = {str(current)}
        previous = [path for path in candidates if path.name != str(current)]
        try:
            previous.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        except FileNotFoundError:
            previous = [path for path in previous if path.exists()]
        keep.update(
            path.name
            for path in previous[: max(0, self.snapshots_to_keep - 1)]
        )
        for path in candidates:
            if path.name not in keep:
                shutil.rmtree(path)
        self._sync_directory(self.snapshots_dir)

    @staticmethod
    def _sync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
