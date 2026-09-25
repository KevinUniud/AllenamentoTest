from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare-data.sh"
DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o700)


@pytest.mark.parametrize("selinuxenabled_exit", [0, 1])
def test_selinux_preflight_checks_then_relabels_without_sudo(
    tmp_path: Path,
    selinuxenabled_exit: int,
) -> None:
    project = tmp_path / "feedback"
    scripts = project / "scripts"
    data = project / "data"
    fake_bin = tmp_path / "bin"
    scripts.mkdir(parents=True)
    (data / "receipts").mkdir(parents=True)
    (data / "charts").mkdir()
    data.chmod(0o700)
    (data / "receipts").chmod(0o700)
    (data / "charts").chmod(0o700)
    fake_bin.mkdir()
    script = scripts / "prepare-data.sh"
    shutil.copy2(SOURCE_SCRIPT, script)

    relabelled = tmp_path / "relabelled"
    chcon_arguments = tmp_path / "chcon-arguments"
    _write_executable(
        fake_bin / "selinuxenabled",
        f"#!/bin/sh\nexit {selinuxenabled_exit}\n",
    )
    _write_executable(fake_bin / "getenforce", "#!/bin/sh\nprintf 'Disabled\\n'\n")
    _write_executable(
        fake_bin / "stat",
        "#!/bin/sh\n"
        f"if [ -f {shlex.quote(str(relabelled))} ]; then\n"
        "  printf '%s\\n' 'system_u:object_r:container_file_t:s0'\n"
        "else\n"
        "  printf '%s\\n' 'unconfined_u:object_r:user_tmp_t:s0'\n"
        "fi\n",
    )
    _write_executable(
        fake_bin / "chcon",
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" > {shlex.quote(str(chcon_arguments))}\n"
        f": > {shlex.quote(str(relabelled))}\n",
    )
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FEEDBACK_UID": str(os.getuid()),
        "FEEDBACK_GID": str(os.getgid()),
    }

    check_before = subprocess.run(
        [str(script), "--check"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert check_before.returncode == 1
    assert "container_file_t" in check_before.stderr
    assert not relabelled.exists()

    prepared = subprocess.run(
        [str(script)],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert prepared.returncode == 0, prepared.stderr
    assert "Contesto SELinux pronto" in prepared.stdout
    arguments = chcon_arguments.read_text(encoding="utf-8")
    assert arguments == f"-R -t container_file_t {data}\n"

    check_after = subprocess.run(
        [str(script), "--check"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert check_after.returncode == 0, check_after.stderr


def test_data_directory_override_from_env_file_is_relative_to_repository(
    tmp_path: Path,
) -> None:
    project = tmp_path / "feedback"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "prepare-data.sh"
    shutil.copy2(SOURCE_SCRIPT, script)
    (project / ".env").write_text("FEEDBACK_DATA_DIR=../private-feedback\n", encoding="utf-8")
    environment = {
        **os.environ,
        "FEEDBACK_UID": str(os.getuid()),
        "FEEDBACK_GID": str(os.getgid()),
    }

    prepared = subprocess.run(
        [str(script)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    expected = tmp_path / "private-feedback"
    assert prepared.returncode == 0, prepared.stderr
    assert (expected / "receipts").is_dir()
    assert (expected / "charts").is_dir()
    assert (expected / ".testlogica-feedback-data").is_dir()
    assert f"Directory dati pronta: {expected}" in prepared.stdout


def test_data_directory_override_rejects_a_symlink_component(tmp_path: Path) -> None:
    project = tmp_path / "feedback"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "prepare-data.sh"
    shutil.copy2(SOURCE_SCRIPT, script)
    real_data = tmp_path / "real-data"
    real_data.mkdir()
    (project / "linked-data").symlink_to(real_data, target_is_directory=True)
    environment = {
        **os.environ,
        "FEEDBACK_DATA_DIR": "linked-data",
        "FEEDBACK_UID": str(os.getuid()),
        "FEEDBACK_GID": str(os.getgid()),
    }

    rejected = subprocess.run(
        [str(script)],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert rejected.returncode == 1
    assert "collegamenti simbolici" in rejected.stderr
    assert not (real_data / "receipts").exists()


def test_data_directory_override_rejects_a_broad_non_feedback_directory(
    tmp_path: Path,
) -> None:
    project = tmp_path / "feedback"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "prepare-data.sh"
    shutil.copy2(SOURCE_SCRIPT, script)
    unrelated = tmp_path / "personal-document.txt"
    unrelated.write_text("non modificare", encoding="utf-8")
    environment = {
        **os.environ,
        "FEEDBACK_DATA_DIR": "..",
        "FEEDBACK_UID": str(os.getuid()),
        "FEEDBACK_GID": str(os.getgid()),
    }

    rejected = subprocess.run(
        [str(script)],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert rejected.returncode == 1
    assert "elementi estranei" in rejected.stderr
    assert unrelated.read_text(encoding="utf-8") == "non modificare"
    assert not (tmp_path / "receipts").exists()


def test_write_env_persists_the_custom_data_directory(tmp_path: Path) -> None:
    project = tmp_path / "feedback"
    scripts = project / "scripts"
    fake_bin = tmp_path / "bin"
    scripts.mkdir(parents=True)
    fake_bin.mkdir()
    script = scripts / "prepare-data.sh"
    shutil.copy2(SOURCE_SCRIPT, script)
    _write_executable(fake_bin / "selinuxenabled", "#!/bin/sh\nexit 1\n")
    _write_executable(fake_bin / "getenforce", "#!/bin/sh\nprintf 'Disabled\\n'\n")
    _write_executable(fake_bin / "stat", "#!/bin/sh\nprintf '?\\n'\n")
    custom_data = tmp_path / "custom-data"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FEEDBACK_DATA_DIR": str(custom_data),
        "FEEDBACK_UID": str(os.getuid()),
        "FEEDBACK_GID": str(os.getgid()),
    }

    written = subprocess.run(
        [str(script), "--write-env"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert written.returncode == 0, written.stderr
    env_file = (project / ".env").read_text(encoding="utf-8")
    assert f"FEEDBACK_DATA_DIR={custom_data}\n" in env_file

    without_override = {
        key: value
        for key, value in environment.items()
        if key not in {"FEEDBACK_DATA_DIR", "FEEDBACK_UID", "FEEDBACK_GID"}
    }
    checked = subprocess.run(
        [str(script), "--check"],
        cwd=project,
        env=without_override,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr
    assert f"Directory dati pronta: {custom_data}" in checked.stdout


def test_docker_test_stage_runs_the_suite_as_a_non_root_user() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    test_stage = dockerfile.split("FROM builder AS test", maxsplit=1)[1].split(
        "FROM python:",
        maxsplit=1,
    )[0]

    user_position = test_stage.index("USER 1000:1000")
    pytest_position = test_stage.index("python -m pytest")
    assert user_position < pytest_position
    assert "COPY scripts ./scripts" in test_stage
