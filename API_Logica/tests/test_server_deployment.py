from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_base_image_is_pinned_by_digest() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.startswith("FROM python:3.11-slim-bookworm@sha256:")
    assert "swi-prolog-nox" in dockerfile
    assert "swi-prolog" not in dockerfile.replace("swi-prolog-nox", "")


def test_server_compose_keeps_api_private_and_bounds_concurrency() -> None:
    compose = (ROOT / "compose.server.yml").read_text(encoding="utf-8")

    assert "external: true" in compose
    assert "api-logica" in compose
    assert "ports:" not in compose
    assert "--workers" in compose
    assert "${API_WORKERS:-2}" in compose
    assert "--limit-concurrency" in compose
    assert "${API_CONCURRENCY_LIMIT:-16}" in compose
    assert "--backlog" in compose
    assert "${API_BACKLOG:-64}" in compose


def test_server_loopback_override_never_defaults_to_all_interfaces() -> None:
    override = (ROOT / "compose.server.loopback.yml").read_text(encoding="utf-8")

    assert "${API_LOOPBACK_ADDRESS:-127.0.0.1}" in override
    assert "0.0.0.0" not in override


def test_failed_deploy_is_stopped_when_rollback_is_unavailable() -> None:
    deploy_script = (ROOT / "scripts" / "deploy-server.sh").read_text(encoding="utf-8")

    assert "recover_after_failure" in deploy_script
    assert 'run_compose_for_release "$RELEASE_TAG" down --remove-orphans' in deploy_script
