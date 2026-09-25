"""Contract tests for the source bundler, using only synthetic temporary files.

Run from the project directory with:
    python3 -m unittest discover -s tools -p 'test_build_bundle.py' -v
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name("build-bundle.py")
SPEC = importlib.util.spec_from_file_location("testlogica_bundle_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
bundler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bundler
SPEC.loader.exec_module(bundler)


class BundleTests(unittest.TestCase):
    COMPONENTS = ("API_Logica", "Webpage_Logica", "feedback")
    DOCUMENTS = (
        "README.md",
        "GUIDA_PROGETTO.md",
        "fast_test.md",
        "NEXTJS_IMPLEMENTAZIONE_E_BUNDLE.md",
    )
    RELEASE = "testlogica-fixture-1"
    REVISION_KEYS = {
        "RELEASE_REVISION",
        "WEB_RELEASE_REVISION",
        "FEEDBACK_RELEASE_REVISION",
    }
    NEXT_SOURCES = {
        "package-lock.json": '{"name":"synthetic-web","lockfileVersion":3}\n',
        "next.config.mjs": "export default { output: 'export' };\n",
        "tsconfig.json": '{"compilerOptions":{"jsx":"preserve"}}\n',
        "src/app/page.tsx": "export default function Page() { return <main>Fixture</main>; }\n",
        "src/components/LegacyContent.tsx": "export function LegacyContent() { return <div />; }\n",
        "tools/prepare-public.mjs": "// Synthetic asset preparation source.\n",
    }

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="test-build-bundle-")
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)
        self.workspace = self.temporary / "workspace"
        self.workspace.mkdir()
        self.output = self.temporary / "output"
        for component in self.COMPONENTS:
            self.write(f"{component}/source.txt", f"Synthetic source: {component}\n")
        for document in self.DOCUMENTS:
            self.write(document, f"# Synthetic {document}\n")

    def write(self, relative, content="synthetic fixture\n", mode=0o644):
        path = self.workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(mode)
        return path

    def build(self, output=None, **kwargs):
        return bundler.build_bundle(
            self.workspace, self.RELEASE, output or self.output, **kwargs
        )

    def read_archive(self, result):
        with tarfile.open(result.archive, "r:gz") as archive:
            members = {member.name: member for member in archive.getmembers()}
            contents = {}
            for name, member in members.items():
                if member.isfile():
                    incoming = archive.extractfile(member)
                    assert incoming is not None
                    with incoming:
                        contents[name] = incoming.read()
            return members, contents

    def archive_name(self, relative):
        return f"{self.RELEASE}/{relative}"

    def test_bundle_contains_sources_documentation_and_useful_dotfiles(self):
        included = (
            ".gitignore",
            ".gitattributes",
            ".dockerignore",
            "tools/build-bundle.py",
            "API_Logica/.github/workflows/check.yml",
            "API_Logica/.gitignore",
            "API_Logica/.gitattributes",
            "API_Logica/.dockerignore",
            "API_Logica/.env.example",
            "API_Logica/.env.server.example",
            "Webpage_Logica/grafici/public.svg",
            "Webpage_Logica/assets/un nome con spazi è valido.txt",
            "feedback/data/.gitkeep",
        )
        for relative in included:
            self.write(relative)

        result = self.build()
        members, contents = self.read_archive(result)
        self.assertEqual(result.verification_status, "not_verified")
        self.assertIn(
            b"NON VERIFICATO", contents[self.archive_name("VERIFICHE_RELEASE.md")]
        )
        self.assertIn(
            b"verification_status=not_verified\n", contents[self.archive_name("MANIFEST.txt")]
        )
        self.assertEqual(result.archive.parent, self.output)
        self.assertEqual(result.checksum.parent, self.output)
        for relative in (*included, *self.DOCUMENTS):
            with self.subTest(path=relative):
                self.assertEqual(
                    contents[self.archive_name(relative)],
                    (self.workspace / relative).read_bytes(),
                )
        self.assertEqual(
            {Path(name).parts[0] for name in members}, {self.RELEASE}
        )
        for name in members:
            self.assertFalse(Path(name).is_absolute())
            self.assertNotIn("..", Path(name).parts)
        for relative in ("MANIFEST.txt", "REVISIONI.env", "VERIFICHE_RELEASE.md"):
            self.assertTrue(contents[self.archive_name(relative)])
        self.assertEqual(set(result.revisions), self.REVISION_KEYS)
        for revision in result.revisions.values():
            self.assertRegex(revision, r"^sha256-[a-f0-9]{64}$")
        revisions_text = contents[self.archive_name("REVISIONI.env")].decode("utf-8")
        for key, revision in result.revisions.items():
            self.assertIn(f"{key}={revision}\n", revisions_text)
        self.assertIn(f"RELEASE_TAG={self.RELEASE}\n", revisions_text)

    def test_private_files_caches_build_outputs_and_runtime_data_are_excluded(self):
        excluded = (
            "API_Logica/.git/config",
            "API_Logica/nested/.git/HEAD",
            "API_Logica/.env",
            "API_Logica/.env.server",
            "API_Logica/.env.production.local",
            "API_Logica/.venv/bin/python",
            "API_Logica/venv/pyvenv.cfg",
            "API_Logica/__pycache__/source.cpython-311.pyc",
            "API_Logica/.pytest_cache/cache/nodeids",
            "API_Logica/private.sqlite3",
            "API_Logica/private.db-wal",
            "Webpage_Logica/node_modules/dependency/index.js",
            "Webpage_Logica/.next/server/page.js",
            "Webpage_Logica/out/index.html",
            "Webpage_Logica/dist/generated.js",
            "Webpage_Logica/.cache/asset.txt",
            "feedback/data/feedback.sqlite3",
            "feedback/data/nested/private.txt",
            "feedback/report/user.txt",
            "feedback/reports/user.txt",
            "feedback/grafici/user.svg",
            "feedback/dump/user.json",
            "feedback/old_dump/user.json",
            "feedback/backups/snapshot.tar",
            "feedback/Risultati.txt",
            "feedback/radar_competenze.png",
            "feedback/report_feedback.txt",
        )
        for relative in excluded:
            self.write(relative, "synthetic private data\n")
        self.write("feedback/data/.gitkeep", "")
        members, _ = self.read_archive(self.build())
        for relative in excluded:
            with self.subTest(path=relative):
                self.assertNotIn(self.archive_name(relative), members)
        self.assertIn(self.archive_name("feedback/data/.gitkeep"), members)
        for component in self.COMPONENTS:
            self.assertIn(self.archive_name(f"{component}/source.txt"), members)

    def test_root_github_configuration_is_included_with_checksums_and_private_files_excluded(self):
        included = {
            ".github/workflows/ci.yml": "name: Synthetic CI fixture\non: [push]\n",
            ".github/dependabot.yml": "version: 2\nupdates: []\n",
        }
        excluded = (
            ".github/.git/config",
            ".github/.env",
            ".github/.env.server",
            ".github/.npmrc",
            ".github/workflows/.npmrc",
            ".github/secrets/token.txt",
        )
        for relative, content in included.items():
            self.write(relative, content)
        for relative in excluded:
            self.write(relative, "synthetic private fixture\n")

        members, contents = self.read_archive(self.build())
        checksum_lines = contents[self.archive_name("SHA256SUMS")].decode("utf-8").splitlines()
        for relative, content in included.items():
            with self.subTest(included=relative):
                expected = content.encode("utf-8")
                self.assertEqual(contents[self.archive_name(relative)], expected)
                self.assertIn(
                    f"{hashlib.sha256(expected).hexdigest()}  ./{relative}", checksum_lines
                )
        for relative in excluded:
            with self.subTest(excluded=relative):
                self.assertNotIn(self.archive_name(relative), members)
        for relative in (".github/.git", ".github/secrets"):
            self.assertNotIn(self.archive_name(relative), members)

    def test_root_github_symlink_is_rejected_before_output_creation(self):
        (self.workspace / ".github").symlink_to(
            self.workspace / "API_Logica", target_is_directory=True
        )
        with self.assertRaises(bundler.BundleError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_github_workflow_symlink_is_rejected_before_output_creation(self):
        workflows = self.workspace / ".github/workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").symlink_to(self.workspace / "API_Logica/source.txt")
        with self.assertRaises(bundler.BundleError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_output_inside_absent_github_is_rejected_without_creating_it(self):
        github = self.workspace / ".github"
        self.assertFalse(github.exists())
        for output in (github, github / "bundles"):
            with self.subTest(output=output.relative_to(self.workspace)):
                with self.assertRaises(bundler.BundleError):
                    self.build(output)
                self.assertFalse(github.exists())

    def test_next_sources_lockfile_and_asset_preparation_tool_are_included(self):
        for relative, content in self.NEXT_SOURCES.items():
            self.write(f"Webpage_Logica/{relative}", content)
        _, contents = self.read_archive(self.build())
        for relative, content in self.NEXT_SOURCES.items():
            with self.subTest(path=relative):
                self.assertEqual(
                    contents[self.archive_name(f"Webpage_Logica/{relative}")],
                    content.encode("utf-8"),
                )

    def test_generated_public_is_excluded_only_at_web_component_root(self):
        generated = "Webpage_Logica/public/assets/generated.svg"
        included = (
            "API_Logica/public/endpoint.txt",
            "Webpage_Logica/src/public/source.svg",
            "feedback/public/source.txt",
        )
        for relative in (generated, *included):
            self.write(relative)
        members, contents = self.read_archive(self.build())
        generated_root = self.archive_name("Webpage_Logica/public")
        self.assertFalse(
            any(name == generated_root or name.startswith(generated_root + "/") for name in members)
        )
        for relative in included:
            with self.subTest(path=relative):
                self.assertEqual(
                    contents[self.archive_name(relative)],
                    (self.workspace / relative).read_bytes(),
                )

    def test_build_browser_outputs_and_auth_configs_are_excluded_at_any_depth(self):
        output_directories = (".build", "test-results", "playwright-report")
        auth_files = (".npmrc", ".pypirc", ".netrc")
        retained = []
        for component in self.COMPONENTS:
            for nested in ("", "src/nested/"):
                prefix = f"{component}/{nested}"
                retained.append(prefix + "retained.txt")
                self.write(retained[-1])
                for directory in output_directories:
                    self.write(prefix + directory + "/generated.txt")
                for filename in auth_files:
                    self.write(prefix + filename, "synthetic authentication fixture\n")
        members, _ = self.read_archive(self.build())
        for name in members:
            with self.subTest(archived_path=name):
                self.assertTrue(set(Path(name).parts).isdisjoint((*output_directories, *auth_files)))
        for relative in retained:
            self.assertIn(self.archive_name(relative), members)

    def test_next_revisions_ignore_generated_artifacts_but_track_source_inputs(self):
        for relative, content in self.NEXT_SOURCES.items():
            self.write(f"Webpage_Logica/{relative}", content)
        for component in self.COMPONENTS:
            self.write(f"{component}/nested/retained.txt")
        first = self.build(self.temporary / "before-generated")
        generated = ["Webpage_Logica/public/assets/generated.svg"]
        for component in self.COMPONENTS:
            generated.extend((
                f"{component}/.build/generated.txt",
                f"{component}/nested/test-results/result.txt",
                f"{component}/nested/playwright-report/index.html",
                f"{component}/nested/.npmrc",
                f"{component}/nested/.pypirc",
                f"{component}/nested/.netrc",
            ))
        for phase in ("created", "modified"):
            for relative in generated:
                self.write(relative, f"Synthetic generated fixture: {phase}\n")
            result = self.build(self.temporary / phase)
            with self.subTest(artifacts=phase):
                self.assertEqual(first.revisions, result.revisions)

        previous = result
        for index, relative in enumerate((
            "package-lock.json", "src/app/page.tsx", "tools/prepare-public.mjs",
        )):
            self.write(f"Webpage_Logica/{relative}", self.NEXT_SOURCES[relative] + "changed fixture\n")
            result = self.build(self.temporary / f"source-change-{index}")
            with self.subTest(changed_source=relative):
                self.assertNotEqual(
                    previous.revisions["WEB_RELEASE_REVISION"],
                    result.revisions["WEB_RELEASE_REVISION"],
                )
                for key in ("RELEASE_REVISION", "FEEDBACK_RELEASE_REVISION"):
                    self.assertEqual(previous.revisions[key], result.revisions[key])
            previous = result

    def test_permissions_are_normalized_without_changing_sources(self):
        script = self.write("API_Logica/scripts/run.sh", "#!/bin/sh\nexit 0\n", 0o751)
        ordinary = self.write("Webpage_Logica/source.txt", mode=0o664)
        directory = script.parent
        directory.chmod(0o775)
        members, _ = self.read_archive(self.build())
        self.assertEqual(members[self.archive_name("API_Logica/scripts/run.sh")].mode, 0o755)
        self.assertEqual(members[self.archive_name("Webpage_Logica/source.txt")].mode, 0o644)
        for member in members.values():
            if member.isdir():
                self.assertEqual(member.mode, 0o755, member.name)
        self.assertEqual(script.stat().st_mode & 0o777, 0o751)
        self.assertEqual(ordinary.stat().st_mode & 0o777, 0o664)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o775)

    def test_revisions_ignore_mtimes_private_files_and_irrelevant_permissions(self):
        script = self.write("API_Logica/scripts/run.sh", "#!/bin/sh\nexit 0\n", 0o751)
        self.write("API_Logica/.env", "private fixture before\n")
        self.write("feedback/data/.gitkeep", "")
        first = self.build(self.temporary / "first")
        for source in self.workspace.rglob("*"):
            os.utime(source, (946684800, 946684800))
        script.chmod(0o711)
        script.parent.chmod(0o700)
        (self.workspace / "API_Logica/source.txt").chmod(0o600)
        self.write("API_Logica/.env", "private fixture after\n")
        self.write("feedback/data/new-runtime-file.txt", "new private data\n")
        self.write("Webpage_Logica/node_modules/new-package/index.js")
        second = self.build(self.temporary / "second")
        self.assertEqual(first.revisions, second.revisions)

    def test_changing_content_changes_only_its_component_revision(self):
        first = self.build(self.temporary / "first")
        self.write("API_Logica/source.txt", "changed source\n")
        second = self.build(self.temporary / "second")
        self.assertNotEqual(first.revisions["RELEASE_REVISION"], second.revisions["RELEASE_REVISION"])
        for key in ("WEB_RELEASE_REVISION", "FEEDBACK_RELEASE_REVISION"):
            self.assertEqual(first.revisions[key], second.revisions[key])

    def test_changing_executable_bit_changes_revision(self):
        first = self.build(self.temporary / "first")
        (self.workspace / "API_Logica/source.txt").chmod(0o755)
        second = self.build(self.temporary / "second")
        self.assertNotEqual(first.revisions["RELEASE_REVISION"], second.revisions["RELEASE_REVISION"])

    def test_included_file_symlink_is_rejected_before_output_creation(self):
        (self.workspace / "API_Logica/linked.txt").symlink_to("source.txt")
        with self.assertRaises(bundler.BundleError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_included_directory_symlink_is_rejected_before_output_creation(self):
        (self.workspace / "API_Logica/linked").symlink_to(
            self.workspace / "Webpage_Logica", target_is_directory=True
        )
        with self.assertRaises(bundler.BundleError):
            self.build()
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO fixtures require POSIX")
    def test_fifo_is_rejected_before_output_creation(self):
        os.mkfifo(self.workspace / "API_Logica/channel")
        with self.assertRaises(bundler.BundleError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_existing_archive_is_not_overwritten(self):
        self.output.mkdir()
        existing = self.output / f"{self.RELEASE}.tar.gz"
        existing.write_bytes(b"previous archive fixture")
        with self.assertRaises(bundler.BundleError):
            self.build()
        self.assertEqual(existing.read_bytes(), b"previous archive fixture")
        self.assertEqual(list(self.output.iterdir()), [existing])

    def test_existing_external_checksum_is_not_overwritten(self):
        self.output.mkdir()
        existing = self.output / f"{self.RELEASE}.tar.gz.sha256"
        existing.write_bytes(b"previous checksum fixture")
        with self.assertRaises(bundler.BundleError):
            self.build()
        self.assertEqual(existing.read_bytes(), b"previous checksum fixture")
        self.assertEqual(list(self.output.iterdir()), [existing])

    def test_release_ready_requires_a_nonempty_verification_report(self):
        empty = self.write("empty-report.md", " \n\t")
        for report in (None, empty):
            with self.subTest(report=report):
                with self.assertRaises(bundler.BundleError):
                    self.build(verification_report=report, release_ready=True)
                self.assertFalse(self.output.exists())

    def test_supplied_verification_report_is_included_verbatim(self):
        report = self.write(
            "synthetic-checks.md",
            "# Synthetic release check fixture\nAll synthetic checks passed.\n",
        )
        result = self.build(verification_report=report, release_ready=True)
        _, contents = self.read_archive(result)
        self.assertEqual(result.verification_status, "report_supplied")
        self.assertIn(
            b"verification_status=report_supplied\n", contents[self.archive_name("MANIFEST.txt")]
        )
        self.assertIn(
            b"application_tests_run_by_packager=no\n", contents[self.archive_name("MANIFEST.txt")]
        )
        self.assertEqual(
            contents[self.archive_name("VERIFICHE_RELEASE.md")], report.read_bytes()
        )

    def test_missing_required_document_is_rejected(self):
        (self.workspace / "GUIDA_PROGETTO.md").unlink()
        with self.assertRaises(bundler.BundleError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_missing_component_is_rejected(self):
        (self.workspace / "feedback/source.txt").unlink()
        (self.workspace / "feedback").rmdir()
        with self.assertRaises(bundler.BundleError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_release_identifier_cannot_escape_output_directory(self):
        for release in ("", ".", "..", "../escape", "/absolute", "bad/name", "bad\nname"):
            with self.subTest(release=release):
                with self.assertRaises(bundler.BundleError):
                    bundler.build_bundle(self.workspace, release, self.output)
                self.assertFalse(self.output.exists())

    def test_internal_and_external_checksums_match_actual_archive_contents(self):
        self.write("Webpage_Logica/assets/with spaces è.txt", "UTF-8 fixture: è\n")
        result = self.build()
        _, contents = self.read_archive(result)
        checksums_name = self.archive_name("SHA256SUMS")
        checked_names = set()
        for line in contents[checksums_name].decode("utf-8").splitlines():
            digest, relative = line.split("  ", 1)
            if relative.startswith("./"):
                relative = relative[2:]
            name = self.archive_name(relative)
            self.assertNotIn(name, checked_names)
            self.assertEqual(hashlib.sha256(contents[name]).hexdigest(), digest, name)
            checked_names.add(name)
        self.assertEqual(checked_names, set(contents) - {checksums_name})
        external_lines = result.checksum.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(external_lines), 1)
        digest, archive_name = external_lines[0].split("  ", 1)
        self.assertEqual(archive_name.removeprefix("./"), result.archive.name)
        self.assertEqual(hashlib.sha256(result.archive.read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
