from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import zipfile


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "package_source.py"
SPEC = importlib.util.spec_from_file_location("package_source", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
package_source = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = package_source
SPEC.loader.exec_module(package_source)


def write_file(root: Path, name: str, data: bytes = b"source\n") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


SECRETS = [
    b"-----BEGIN " + b"PRIVATE KEY-----\nprivate material",
    b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----\nprivate material",
    b"ghp_" + b"a" * 36,
    b"github_pat_" + b"a" * 60,
    b"glpat-" + b"a" * 24,
    b"sk-proj-" + b"a" * 48,
    b"sk_live_" + b"a" * 24,
    b"xoxb-" + b"1" * 12 + b"-" + b"a" * 24,
    b"AKIA" + b"A" * 16,
    b"AIza" + b"a" * 35,
    b"eyJ" + b"a" * 20 + b"." + b"b" * 20 + b"." + b"c" * 20,
]


class PackageSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_archive_selects_sources_and_preserves_assets(self):
        tmp_path = self.root
        root = tmp_path / "source"
        included = {
            "README.md", "CITATION.cff", "THIRD_PARTY_NOTICES.md", ".gitignore",
            "backend/.env.example", "backend/.dockerignore", "backend/libereye/models.py",
            "ios/Configuration/HeyCyanLicense.env.example",
            "ios/Sources/Assets.xcassets/AppIcon.appiconset/icon.png",
            "ios/LiberEye.xcodeproj/project.pbxproj", "firmware/libereye_wrist/libereye_wrist.ino",
            "docs/development.md", "scripts/check.sh", "tests/test_api.py", ".github/workflows/ci.yml",
        }
        excluded = {
            "notes.txt", "other/source.py", ".env", ".local/keys.json", ".git/config",
            ".tools/compiler/bin/tool", "backend/.env", "backend/.env.local",
            "backend/config.local.json", "backend/.private/data.txt", "backend/node_modules/pkg/index.js",
            "backend/libereye.egg-info/PKG-INFO", "backend/__pycache__/models.pyc",
            "backend/build/lib.py", "backend/dist/pkg.zip", "backend/models/model.pt",
            "backend/evaluation/scores.csv", "backend/datasets/data.json", "backend/runs/result.csv",
            "backend/private/user.json", "backend/service-account.json", "backend/server.log",
            "backend/server.log.1", "backend/model.onnx", "backend/model.safetensors",
            "ios/DerivedData/source.swift", "ios/.private/data.txt", "ios/xcuserdata/state.xml",
            "ios/Sources/HeyCyanSDK/Public.h", "ios/Sources/HeyCyanSDK/README.md",
            "ios/Sources/Library.framework/Headers/public.h", "ios/Sources/Library.xcframework/Info.plist",
            "ios/Configuration/HeyCyanLicense.env", "ios/certificate.p12", "ios/certificate.pem",
            "ios/private.key", "ios/profile.mobileprovision", "docs/paper.pdf",
            "firmware/wrist.bin", "firmware/wrist.uf2", "firmware/wrist.hex",
            "firmware/wrist.elf", "firmware/wrist.map", "backend/.DS_Store",
            ".github/.private/token.txt", "dist/old.zip",
        }
        for name in included | excluded:
            write_file(root, name)
        output = tmp_path / "release" / "libereye-source.zip"
        result = package_source.build_archive(root, output)
        self.assertEqual(result.source_file_count, len(included))
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(set(archive.namelist()), {f"LiberEye/{name}" for name in included | {"SHA256SUMS"}})
            self.assertEqual(archive.read("LiberEye/ios/Sources/Assets.xcassets/AppIcon.appiconset/icon.png"), b"source\n")
            manifest = archive.read("LiberEye/SHA256SUMS").decode()
            entries = dict(line.split("  ", 1)[::-1] for line in manifest.splitlines())
            self.assertEqual(set(entries), included)
            for name, digest in entries.items():
                self.assertEqual(digest, hashlib.sha256(archive.read(f"LiberEye/{name}")).hexdigest())
            for entry in archive.infolist():
                self.assertEqual(entry.date_time, package_source.ZIP_TIMESTAMP)
                mode = entry.external_attr >> 16
                self.assertTrue(stat.S_ISREG(mode))
                self.assertEqual(stat.S_IMODE(mode), 0o755 if entry.filename.endswith(".sh") else 0o644)
        digest, filename = result.checksum_path.read_text().strip().split("  ", 1)
        self.assertEqual(digest, hashlib.sha256(output.read_bytes()).hexdigest())
        self.assertEqual(filename, output.name)
        self.assertFalse((root / "LICENSE").exists())

    def test_archive_is_reproducible_and_license_is_optional(self):
        tmp_path = self.root
        root = tmp_path / "source"
        paths = [write_file(root, name) for name in ["README.md", "LICENSE", "backend/app.py", "scripts/run.sh"]]
        first = tmp_path / "first.zip"
        second = tmp_path / "second.zip"
        package_source.build_archive(root, first)
        for index, path in enumerate(paths):
            os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
            path.chmod(0o777)
        package_source.build_archive(root, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as archive:
            self.assertIn("LiberEye/LICENSE", archive.namelist())

    def test_symbolic_links_are_not_followed(self):
        tmp_path = self.root
        root = tmp_path / "source"
        write_file(root, "README.md")
        actual = write_file(root, "backend/actual.py")
        external = write_file(tmp_path, "external/value.txt", b"private")
        (root / "backend/link.py").symlink_to(external)
        (root / "backend/internal.py").symlink_to(actual)
        (root / "backend/linked-directory").symlink_to(external.parent, target_is_directory=True)
        (root / "docs").symlink_to(external.parent, target_is_directory=True)
        (root / "LICENSE").symlink_to(external)
        (root / "backend/broken.py").symlink_to(tmp_path / "missing")
        self.assertEqual(set(package_source.collect_sources(root)), {"README.md", "backend/actual.py"})

    def test_secret_scan_aborts_without_exposing_values_or_replacing_archive(self):
        for index, secret in enumerate(SECRETS):
            with self.subTest(case=index):
                self.check_secret(secret)

    def check_secret(self, secret):
        tmp_path = self.root
        root = tmp_path / "source"
        write_file(root, "README.md")
        write_file(root, "backend/settings.py", b"value = '" + secret + b"'\n")
        output = write_file(tmp_path, "libereye-source.zip", b"existing archive")
        with self.assertRaises(package_source.SourceValidationError) as error:
            package_source.build_archive(root, output)
        self.assertIn("backend/settings.py", str(error.exception))
        self.assertNotIn(secret.decode(), str(error.exception))
        self.assertEqual(output.read_bytes(), b"existing archive")
        self.assertFalse(output.with_name(output.name + ".sha256").exists())

    def test_private_configuration_is_excluded_before_scanning(self):
        tmp_path = self.root
        root = tmp_path / "source"
        write_file(root, "README.md")
        write_file(root, "backend/.env.example", b"LIBEREYE_API_TOKEN=\n")
        write_file(root, "backend/.env", b"LIBEREYE_API_TOKEN=" + b"ghp_" + b"a" * 36)
        self.assertEqual(set(package_source.collect_sources(root)), {"README.md", "backend/.env.example"})

    def test_checksum_write_does_not_follow_an_existing_link(self):
        root = self.root / "source"
        write_file(root, "README.md")
        external = write_file(self.root, "private.txt", b"private")
        output = self.root / "libereye-source.zip"
        checksum = output.with_name(output.name + ".sha256")
        checksum.symlink_to(external)
        package_source.build_archive(root, output)
        self.assertEqual(external.read_bytes(), b"private")
        self.assertFalse(checksum.is_symlink())

    def test_source_models_directories_are_distinct_from_backend_weights(self):
        root = self.root / "source"
        included = {
            "ios/Sources/Models/AppModels.swift",
            "ios/Sources/Models/CloudBaseModels.swift",
            "ios/Sources/Models/LiberEyeCloudPlan.swift",
            "ios/Sources/Models/WristProtocol.swift",
            "backend/libereye/models/scene.py",
        }
        excluded = {
            "backend/models/model.pt",
            "backend/models/config.json",
            "backend/models/nested/metadata.txt",
            "backend/libereye/models/checkpoint.onnx",
        }
        for name in included | excluded:
            write_file(root, name)
        self.assertEqual(set(package_source.collect_sources(root)), included)

    def test_empty_source_selection_fails(self):
        tmp_path = self.root
        with self.assertRaisesRegex(package_source.SourceValidationError, "No publishable"):
            package_source.collect_sources(tmp_path)


if __name__ == "__main__":
    unittest.main()
