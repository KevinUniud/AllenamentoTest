from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_server_backup_uses_integrated_private_service_and_never_copies_database_directly() -> None:
    script = (ROOT / "scripts" / "server-backup.sh").read_text(encoding="utf-8")

    assert "compose.server.yml" in script
    assert "compose exec -T feedback python -m feedback_service.admin backup" in script
    assert "sha256sum" in script
    assert "FEEDBACK_MIN_FREE_BYTES" in script
    assert "df -Pk" in script
    assert "cp feedback.sqlite3" not in script
    assert re.search(r"(?m)^\s*sudo\b", script) is None


def test_prepare_data_enforces_private_user_owned_runtime_tree(tmp_path: Path) -> None:
    project = tmp_path / "feedback"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "prepare-data.sh"
    shutil.copy2(ROOT / "scripts" / "prepare-data.sh", script)
    environment = {
        **os.environ,
        "FEEDBACK_UID": str(os.getuid()),
        "FEEDBACK_GID": str(os.getgid()),
    }

    prepared = subprocess.run(
        [str(script)],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert prepared.returncode == 0, prepared.stderr
    data = project / "data"
    assert data.stat().st_mode & 0o777 == 0o700
    assert (data / "receipts").stat().st_mode & 0o777 == 0o700
    assert (data / "charts").stat().st_mode & 0o777 == 0o700


def test_prepare_data_removes_group_and_other_read_permissions(tmp_path: Path) -> None:
    project = tmp_path / "feedback"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "prepare-data.sh"
    shutil.copy2(ROOT / "scripts" / "prepare-data.sh", script)
    data = project / "data"
    receipts = data / "receipts"
    charts = data / "charts"
    receipts.mkdir(parents=True)
    charts.mkdir()
    sample = receipts / "feedback.sqlite3"
    sample.write_bytes(b"test")
    data.chmod(0o755)
    receipts.chmod(0o755)
    charts.chmod(0o755)
    sample.chmod(0o644)

    prepared = subprocess.run(
        [str(script)],
        cwd=project,
        env={
            **os.environ,
            "FEEDBACK_UID": str(os.getuid()),
            "FEEDBACK_GID": str(os.getgid()),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert prepared.returncode == 0, prepared.stderr
    assert data.stat().st_mode & 0o777 == 0o700
    assert receipts.stat().st_mode & 0o777 == 0o700
    assert charts.stat().st_mode & 0o777 == 0o700
    assert sample.stat().st_mode & 0o777 == 0o600
