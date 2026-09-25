"""Readiness checks for external SWI-Prolog dependencies."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..config import PROLOG_DIR, SWI_PROLOG_PATH


def readiness(executable: str = SWI_PROLOG_PATH, source_dir: Path = PROLOG_DIR) -> tuple[bool, str]:
    if shutil.which(executable) is None and not Path(executable).is_file():
        return False, "SWI-Prolog executable not found"
    required = ("rpc_server.pl", "logic.pl", "equivalence.pl", "rewrite.pl", "templates.pl", "distractions.pl")
    missing = [name for name in required if not (source_dir / name).is_file()]
    if missing:
        return False, "Missing Prolog sources: " + ", ".join(missing)
    return True, "ready"
