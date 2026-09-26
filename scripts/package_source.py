#!/usr/bin/env python3
"""Create a reproducible LiberEye source archive with integrity checks."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile


ROOT_FILES = frozenset({"README.md", "CITATION.cff", "LICENSE", "THIRD_PARTY_NOTICES.md", ".gitignore"})
SOURCE_TREES = frozenset({"docs", "scripts", "tests", ".github", "backend", "ios", "firmware"})
EXCLUDED_DIRECTORIES = frozenset({
    "build", "dist", "evaluation", "deriveddata", "node_modules",
    "__pycache__", "xcuserdata", "pods", "carthage", "private", "personal",
    "secrets", "credentials", "datasets", "runs", "output", "outputs",
    "logs", "log", "tmp", "temp", "venv",
})
EXCLUDED_SUFFIXES = frozenset({
    ".log", ".p12", ".pfx", ".pem", ".key", ".mobileprovision",
    ".bin", ".uf2", ".hex", ".elf", ".map", ".pt", ".pth", ".onnx",
    ".ckpt", ".safetensors", ".tflite", ".torchscript", ".mlmodel", ".pdf",
    ".pyc", ".pyo", ".o", ".a", ".so", ".dylib", ".dll", ".exe",
    ".class", ".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".dmg",
    ".ipa", ".apk", ".xcuserstate", ".pbxuser", ".mode1v3", ".mode2v3",
    ".perspectivev3", ".xcscmblueprint", ".framework", ".xcframework",
})
EXCLUDED_DIRECTORY_SUFFIXES = (".egg-info", ".framework", ".xcframework", ".mlmodelc")
ALLOWED_HIDDEN_FILES = frozenset({".gitignore", ".dockerignore", ".env.example"})
ARCHIVE_ROOT = "LiberEye"
MANIFEST_NAME = "SHA256SUMS"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

# Only the rule name and source path are reported when a match is found.
SECRET_PATTERNS = (
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
    ("repository token", re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|glpat-[A-Za-z0-9_-]{20,})\b")),
    ("service token", re.compile(rb"\b(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}|[sr]k_live_[A-Za-z0-9]{20,})\b")),
    ("messaging token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("cloud access key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("cloud API key", re.compile(rb"\bAIza[A-Za-z0-9_-]{35}\b")),
    ("signed access token", re.compile(rb"\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b")),
)


class SourceValidationError(ValueError):
    """The selected source files cannot be published safely."""


@dataclass(frozen=True)
class PackageResult:
    archive_path: Path
    checksum_path: Path
    source_file_count: int


def is_excluded(relative_path: PurePosixPath, *, directory: bool = False) -> bool:
    """Apply publication boundaries to a path relative to the source root."""
    parts = relative_path.parts
    if not parts:
        return True
    if parts[:3] == ("ios", "Sources", "HeyCyanSDK"):
        return True
    if parts[:2] == ("backend", "models"):
        return True
    directory_parts = parts if directory else parts[:-1]
    for index, part in enumerate(directory_parts):
        lowered = part.lower()
        if part.startswith(".") and not (index == 0 and part == ".github"):
            return True
        if lowered in EXCLUDED_DIRECTORIES or lowered.endswith(EXCLUDED_DIRECTORY_SUFFIXES):
            return True
    if directory:
        return False
    name = parts[-1]
    lowered = name.lower()
    if name.startswith(".") and name not in ALLOWED_HIDDEN_FILES:
        return True
    if ".env" in lowered and not lowered.endswith(".env.example"):
        return True
    if ".local." in lowered or lowered.endswith(".local"):
        return True
    if ".log." in lowered or lowered.endswith(".zip.sha256"):
        return True
    if Path(lowered).suffix in EXCLUDED_SUFFIXES:
        return True
    if lowered in {"credentials", "credentials.json", "secrets.json", "secrets.yaml", "secrets.yml", "service-account.json"}:
        return True
    return False


def validate_contents(relative_path: str, data: bytes) -> None:
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(data):
            raise SourceValidationError(f"Cannot package {relative_path}: detected {name}.")


def collect_sources(source_root: Path) -> dict[str, bytes]:
    """Read regular allowlisted files without traversing symbolic links."""
    source_root = source_root.resolve(strict=True)
    if not source_root.is_dir():
        raise SourceValidationError("The source root must be a directory.")
    candidates: list[Path] = []
    for name in sorted(ROOT_FILES):
        candidate = source_root / name
        if candidate.exists() and not candidate.is_symlink():
            candidates.append(candidate)
    for name in sorted(SOURCE_TREES):
        tree = source_root / name
        if tree.is_symlink() or not tree.is_dir():
            continue
        for current, directories, files in os.walk(tree, followlinks=False):
            current_path = Path(current)
            directories[:] = sorted(
                name for name in directories
                if not (current_path / name).is_symlink()
                and not is_excluded(PurePosixPath((current_path / name).relative_to(source_root).as_posix()), directory=True)
            )
            candidates.extend(current_path / name for name in sorted(files))
    sources: dict[str, bytes] = {}
    for path in sorted(candidates):
        relative = path.relative_to(source_root).as_posix()
        if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            continue
        if is_excluded(PurePosixPath(relative)):
            continue
        data = path.read_bytes()
        validate_contents(relative, data)
        sources[relative] = data
    if not sources:
        raise SourceValidationError("No publishable source files were found.")
    return sources


def _entry(name: str, *, executable: bool = False) -> zipfile.ZipInfo:
    entry = zipfile.ZipInfo(f"{ARCHIVE_ROOT}/{name}", ZIP_TIMESTAMP)
    entry.create_system = 3
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = (stat.S_IFREG | (0o755 if executable else 0o644)) << 16
    return entry


def _write_checksum(path: Path, contents: str) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(contents)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def build_archive(source_root: Path, output_path: Path) -> PackageResult:
    sources = collect_sources(source_root)
    manifest = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in sorted(sources.items())
    ).encode("utf-8")
    output_path = output_path.absolute()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    checksum_path = output_path.with_name(output_path.name + ".sha256")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=output_path.parent, suffix=".zip", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in sorted({**sources, MANIFEST_NAME: manifest}.items()):
                archive.writestr(_entry(name, executable=name.endswith(".sh")), data)
        checksum = hashlib.sha256(temporary_path.read_bytes()).hexdigest()
        os.replace(temporary_path, output_path)
        _write_checksum(checksum_path, f"{checksum}  {output_path.name}\n")
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return PackageResult(output_path, checksum_path, len(sources))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="LiberEye source root.")
    parser.add_argument("--output", type=Path, help="Archive destination; defaults to dist/libereye-source.zip.")
    parser.add_argument("--check", action="store_true", help="Validate source selection without writing an archive.")
    args = parser.parse_args()
    try:
        if args.check:
            print(f"Validated {len(collect_sources(args.root))} source files.")
            return 0
        result = build_archive(args.root, args.output or args.root / "dist" / "libereye-source.zip")
    except (OSError, SourceValidationError) as error:
        parser.exit(1, f"Packaging failed: {error}\n")
    print(f"Packaged {result.source_file_count} source files: {result.archive_path}")
    print(f"Checksum: {result.checksum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
