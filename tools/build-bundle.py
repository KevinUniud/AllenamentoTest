#!/usr/bin/env python3
"""Package TestLogica sources without Git, dependencies, or runtime data.

Example, from the integration workspace:
    python3 tools/build-bundle.py --release testlogica-20260922 --output dist/bundles

The utility validates and hashes the archive; it does not run application tests.
Use --verification-report to include actual release checks. --release-ready
requires that report but does not independently validate its statements.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tarfile
import tempfile
from typing import BinaryIO


COMPONENTS = {
    "API_Logica": "RELEASE_REVISION",
    "Webpage_Logica": "WEB_RELEASE_REVISION",
    "feedback": "FEEDBACK_RELEASE_REVISION",
}
DOCUMENTS = (
    "README.md",
    "GUIDA_PROGETTO.md",
    "fast_test.md",
    "NEXTJS_IMPLEMENTAZIONE_E_BUNDLE.md",
)
EXCLUDED_NAMES = {
    ".git", ".agents", ".codex", ".claude", ".venv", "venv", "env", "ENV",
    "__pycache__", ".Python", "node_modules", ".next", "out", "build", ".build", "dist",
    ".cache", ".turbo", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".hypothesis", ".tox", ".nox", ".eggs", "pip-wheel-metadata", "coverage",
    "htmlcov", ".nyc_output", ".deploy", ".idea", ".vscode", ".DS_Store",
    "Thumbs.db", ".ssh", "secrets", "logs", "backup", "backups", "reports",
    "test-results", "playwright-report", ".npmrc", ".pypirc", ".netrc",
}
EXCLUDED_PATTERNS = (
    "*.pyc", "*.pyo", "*.pyd", "*.egg-info", "*.qlf", "*.tsbuildinfo",
    ".coverage*", "coverage.xml", "*.log", "*.pid", "*.swp", "*.swo", "*~",
    "*.db", "*.db-*", "*.sqlite", "*.sqlite-*", "*.sqlite3", "*.sqlite3-*",
    "*.key", "*.pem", "*.p12", "*.pfx", "*.jks", "*.keystore", "id_rsa*",
    "id_ed25519*", "*credentials*", "*.bak", "*.backup",
)
FEEDBACK_PRIVATE = {
    "dump", "old_dump", "report", "grafici", "Risultati.txt",
    "radar_competenze.png", "report_feedback.txt",
}
ENV_EXAMPLES = {".env.example", ".env.server.example"}
CHUNK_SIZE = 1024 * 1024


class BundleError(Exception):
    """An invalid or unsafe input prevented packaging."""


@dataclass(frozen=True)
class BundleResult:
    archive: Path
    checksum: Path
    revisions: dict[str, str]
    verification_status: str


@dataclass(frozen=True)
class SourceEntry:
    source: Path
    relative: Path
    info: os.stat_result


def excluded(component: str, relative: Path) -> bool:
    name = relative.name
    if name in EXCLUDED_NAMES:
        return True
    if name not in ENV_EXAMPLES and (name == ".env" or name.startswith(".env.")):
        return True
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in EXCLUDED_PATTERNS):
        return True
    # This frontend regenerates its root public/ from source assets using
    # tools/prepare-public.mjs. Other components' public directories are sources.
    if component == "Webpage_Logica" and relative.parts[0] == "public":
        return True
    if component == "feedback":
        if relative.parts[0] in FEEDBACK_PRIVATE:
            return True
        if relative.parts[0] == "data" and relative.as_posix() not in {
            "data", "data/.gitkeep",
        }:
            return True
    return False


def inspect_path(source: Path, relative: Path) -> SourceEntry:
    info = source.lstat()
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise BundleError(f"Link o file speciale non distribuibile: {source}")
    # These names are legal on Linux but cannot be represented unambiguously
    # by the deliberately simple, portable SHA256SUMS file used in the bundle.
    if any(character in relative.as_posix() for character in ("\n", "\r", "\\")):
        raise BundleError(f"Nome non supportato per i checksum: {source}")
    return SourceEntry(source, relative, info)


def scan_tree(source_root: Path, component: str) -> list[SourceEntry]:
    root = inspect_path(source_root, Path(component))
    if not stat.S_ISDIR(root.info.st_mode):
        raise BundleError(f"Il componente deve essere una directory: {source_root}")
    entries = [root]

    def visit(directory: Path, relative_dir: Path) -> None:
        for source in sorted(directory.iterdir(), key=lambda item: item.name):
            relative = relative_dir / source.name
            if excluded(component, relative):
                continue
            entry = inspect_path(source, Path(component) / relative)
            entries.append(entry)
            if stat.S_ISDIR(entry.info.st_mode):
                visit(source, relative)

    visit(source_root, Path())
    return entries


def fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns)


def open_source(source: Path) -> BinaryIO:
    """Open an absolute source through directory descriptors without symlinks."""
    absolute = source.absolute()
    directory_fd = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:-1]:
            child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                               dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        file_fd = os.open(absolute.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                          dir_fd=directory_fd)
        return os.fdopen(file_fd, "rb")
    finally:
        os.close(directory_fd)


def copy_file(entry: SourceEntry, target: Path) -> tuple[int, str]:
    with open_source(entry.source) as incoming:
        before = os.fstat(incoming.fileno())
        if not stat.S_ISREG(before.st_mode) or fingerprint(before) != fingerprint(entry.info):
            raise BundleError(f"Sorgente cambiato durante il confezionamento: {entry.source}")
        mode = 0o755 if before.st_mode & 0o111 else 0o644
        digest = hashlib.sha256()
        with target.open("xb") as outgoing:
            while chunk := incoming.read(CHUNK_SIZE):
                outgoing.write(chunk)
                digest.update(chunk)
        if fingerprint(os.fstat(incoming.fileno())) != fingerprint(before):
            raise BundleError(f"Sorgente cambiato durante la lettura: {entry.source}")
    target.chmod(mode)
    return mode, digest.hexdigest()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    path.chmod(0o644)


def build_bundle(
    workspace: Path,
    release: str,
    output: Path,
    verification_report: Path | None = None,
    release_ready: bool = False,
) -> BundleResult:
    """Build an archive after preflight; raise BundleError on rejected inputs.

    Source files must remain unchanged until packaging completes. Exclusions
    are explicit, not interpreted from Git settings, and cannot detect secrets
    stored under unexpected names. Review distributable sources before release.
    """
    try:
        return _build_bundle(workspace, release, output, verification_report, release_ready)
    except OSError as error:
        raise BundleError(str(error)) from error


def _build_bundle(
    workspace: Path,
    release: str,
    output: Path,
    verification_report: Path | None,
    release_ready: bool,
) -> BundleResult:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", release):
        raise BundleError("Release non valida: usare 1-128 caratteri A-Za-z0-9_.-, "
                          "iniziando con una lettera o cifra")
    workspace, output = Path(workspace).absolute(), Path(output).absolute()
    archive = output / f"{release}.tar.gz"
    checksum = output / f"{release}.tar.gz.sha256"
    if os.path.lexists(archive) or os.path.lexists(checksum):
        raise BundleError(f"Release già presente; nessuna sovrascrittura: {release}")
    for component in COMPONENTS:
        if output.resolve().is_relative_to((workspace / component).resolve()):
            raise BundleError("La directory di output deve essere esterna ai componenti")

    # Enumerate every included source before creating any output directory.
    entries: list[SourceEntry] = []
    for component in COMPONENTS:
        entries.extend(scan_tree(workspace / component, component))
    for name in DOCUMENTS:
        entry = inspect_path(workspace / name, Path(name))
        if not stat.S_ISREG(entry.info.st_mode):
            raise BundleError(f"La guida deve essere un file regolare: {entry.source}")
        entries.append(entry)
    for name in (".gitignore", ".gitattributes", ".dockerignore"):
        if os.path.lexists(workspace / name):
            entry = inspect_path(workspace / name, Path(name))
            if not stat.S_ISREG(entry.info.st_mode):
                raise BundleError(f"Configurazione non regolare: {entry.source}")
            entries.append(entry)
    if os.path.lexists(workspace / "tools"):
        entries.extend(scan_tree(workspace / "tools", "tools"))
        if output.resolve().is_relative_to((workspace / "tools").resolve()):
            raise BundleError("La directory di output deve essere esterna a tools")

    report_entry = None
    if verification_report is not None:
        report_entry = inspect_path(Path(verification_report).absolute(), Path("VERIFICHE_RELEASE.md"))
        if not stat.S_ISREG(report_entry.info.st_mode):
            raise BundleError("Il rapporto delle verifiche deve essere un file regolare")
        with open_source(report_entry.source) as stream:
            if not stream.read().strip():
                raise BundleError("Il rapporto delle verifiche è vuoto")
        entries.append(report_entry)
    elif release_ready:
        raise BundleError("--release-ready richiede --verification-report con gli esiti reali")
    verification_status = "report_supplied" if report_entry else "not_verified"

    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{release}-", dir=output) as scratch:
        stage = Path(scratch)
        root = stage / release
        root.mkdir(mode=0o755)
        root.chmod(0o755)
        records: dict[str, list[list[str]]] = {name: [] for name in COMPONENTS}
        for entry in entries:
            target = root / entry.relative
            component = entry.relative.parts[0]
            relative = Path(*entry.relative.parts[1:]).as_posix()
            if stat.S_ISDIR(entry.info.st_mode):
                target.mkdir(mode=0o755)
                target.chmod(0o755)
                if component in records and len(entry.relative.parts) > 1:
                    records[component].append([relative, "directory", "0755"])
            else:
                mode, digest = copy_file(entry, target)
                if component in records:
                    records[component].append([relative, "file", f"{mode:04o}", digest])
        revisions = {}
        for component, key in COMPONENTS.items():
            ordered = sorted(records[component], key=lambda item: item[0])
            encoded = json.dumps(ordered, ensure_ascii=True, separators=(",", ":")).encode("ascii")
            revisions[key] = "sha256-" + hashlib.sha256(encoded).hexdigest()
        write_text(root / "REVISIONI.env", f"RELEASE_TAG={release}\n" + "".join(
            f"{key}={value}\n" for key, value in revisions.items()))
        if report_entry is None:
            write_text(root / "VERIFICHE_RELEASE.md", "# Verifiche della release\n\n"
                       f"Release: `{release}`.\n\n"
                       "**NON VERIFICATO**: nessun rapporto di collaudo fornito.\n"
                       "Il confezionamento non esegue test applicativi, build Docker "
                       "o controlli del browser. I checksum attestano i file inclusi; "
                       "non attestano il funzionamento dell'applicazione.\n")
        manifest = {
            "format": "testlogica-source-bundle-v2",
            "release": release,
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "components": ",".join(COMPONENTS),
            "kind": "sources",
            "dependency_downloads_required": "yes",
            "runtime_data_included": "no",
            "revisions": "REVISIONI.env",
            "revision_scheme": "sha256-canonical-tree-v1",
            "revision_fields": "path,type,normalized-mode,file-sha256",
            "symlinks_and_special_files": "refused",
            "checksums": "SHA256SUMS",
            "verification_report": "VERIFICHE_RELEASE.md",
            "verification_status": verification_status,
            "release_ready_requested": "yes" if release_ready else "no",
            "application_tests_run_by_packager": "no",
            "packager_python_version": sys.version.split()[0],
        }
        write_text(root / "MANIFEST.txt", "".join(f"{key}={value}\n" for key, value in manifest.items()))
        files = sorted((path for path in root.rglob("*") if path.is_file()),
                       key=lambda path: path.relative_to(root).as_posix())
        sums = {path.relative_to(root).as_posix(): hash_file(path) for path in files}
        write_text(root / "SHA256SUMS", "".join(f"{digest}  ./{name}\n" for name, digest in sums.items()))
        sums["SHA256SUMS"] = hash_file(root / "SHA256SUMS")

        staged_archive = stage / archive.name
        with tarfile.open(staged_archive, "w:gz", format=tarfile.PAX_FORMAT) as bundle:
            for path in [root, *sorted(root.rglob("*"))]:
                info = bundle.gettarinfo(str(path), arcname=str(path.relative_to(stage)))
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                if info.isfile():
                    with path.open("rb") as stream:
                        bundle.addfile(info, stream)
                elif info.isdir():
                    bundle.addfile(info)
                else:
                    raise BundleError(f"Tipo di file imprevisto nello staging: {path}")
        # Check the bytes actually archived, not only the temporary sources.
        archived_files = set()
        with tarfile.open(staged_archive, "r:gz") as bundle:
            for member in bundle:
                if not member.isfile():
                    continue
                name = Path(member.name).relative_to(release).as_posix()
                stream = bundle.extractfile(member)
                assert stream is not None
                digest = hashlib.sha256()
                with stream:
                    while chunk := stream.read(CHUNK_SIZE):
                        digest.update(chunk)
                if name not in sums or digest.hexdigest() != sums[name]:
                    raise BundleError(f"Checksum dell'archivio non valido: {name}")
                archived_files.add(name)
        if archived_files != set(sums):
            raise BundleError("L'archivio non contiene tutti i file previsti")
        staged_checksum = stage / checksum.name
        write_text(staged_checksum, f"{hash_file(staged_archive)}  {archive.name}\n")
        staged_archive.chmod(0o644)
        # Hard links publish complete files atomically and refuse overwrites,
        # including collisions created after the initial preflight.
        os.link(staged_archive, archive)
        try:
            os.link(staged_checksum, checksum)
        except OSError:
            archive.unlink()
            raise
    return BundleResult(archive, checksum, revisions, verification_status)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", required=True, help="Identificativo univoco della release")
    parser.add_argument("--output", required=True, type=Path, help="Directory per tar.gz e checksum")
    parser.add_argument("--verification-report", type=Path, help="Rapporto reale dei controlli da includere")
    parser.add_argument("--release-ready", action="store_true", help="Richiede un rapporto; non esegue né certifica test")
    args = parser.parse_args()
    try:
        result = build_bundle(Path(__file__).resolve().parent.parent, args.release,
                              args.output, args.verification_report, args.release_ready)
    except BundleError as error:
        print(f"Errore: {error}", file=sys.stderr)
        return 1
    print(f"Bundle: {result.archive}\nChecksum: {result.checksum}")
    for key, revision in result.revisions.items():
        print(f"{key}={revision}")
    if result.verification_status == "not_verified":
        print("Stato: NON VERIFICATO; nessun rapporto di collaudo fornito.", file=sys.stderr)
    else:
        print("Stato: rapporto fornito; contenuti del rapporto non certificati dalla utility.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
