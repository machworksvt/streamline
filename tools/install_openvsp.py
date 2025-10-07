from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import sysconfig
import tarfile
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile

DEFAULT_CACHE_ENV = "STREAMLINE_OPENVSP_HOME"
DEFAULT_CACHE_DIRNAME = Path.home() / ".cache" / "openvsp"
INSTALL_MARKER = "install_manifest.json"
PTH_FILENAME = "openvsp-runtime.pth"


@dataclass
class PlatformSpec:
    key: str
    url: str
    archive_type: str
    archive_subdir: Optional[str]
    python_subdir: str
    library_subdirs: List[str]
    sha256: Optional[str]

    @classmethod
    def from_dict(cls, key: str, data: Dict[str, object]) -> "PlatformSpec":
        return cls(
            key=key,
            url=str(data["url"]),
            archive_type=str(data.get("archive_type", "zip")),
            archive_subdir=str(data.get("archive_subdir")) if data.get("archive_subdir") else None,
            python_subdir=str(data.get("python_subdir", "python")),
            library_subdirs=[str(item) for item in data.get("library_subdirs", [])],
            sha256=str(data["sha256"]) if data.get("sha256") else None,
        )


@dataclass
class InstallResult:
    version: str
    platform_key: str
    install_root: Path
    python_dir: Path
    path_entries: List[Path]
    library_paths: Dict[str, List[Path]]
    archive_path: Optional[Path]

    def to_json_dict(self) -> Dict[str, object]:
        return {
            "version": self.version,
            "platform": self.platform_key,
            "install_root": str(self.install_root),
            "python_dir": str(self.python_dir),
            "path_entries": [str(p) for p in self.path_entries],
            "library_paths": {key: [str(p) for p in paths] for key, paths in self.library_paths.items()},
            "archive_path": str(self.archive_path) if self.archive_path else None,
        }


def determine_platform_name(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit.lower()

    system = platform.system().lower()
    if system.startswith("win"):
        return "windows"
    if system.startswith("linux"):
        return "linux"
    if system.startswith("darwin") or system.startswith("mac"):
        return "macos"
    raise RuntimeError(f"Unsupported operating system: {platform.system()}")


def load_metadata(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def download_file(url: str, destination: Path) -> Path:
    req = Request(url, headers={"User-Agent": "streamline-openvsp-installer"})
    with urlopen(req) as response:
        ensure_directory(destination.parent)
        with destination.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    return destination


def verify_checksum(path: Path, expected_sha256: Optional[str]) -> None:
    if not expected_sha256:
        return

    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual.lower() != expected_sha256.lower():
        raise RuntimeError(
            "Checksum verification failed",
            {"expected": expected_sha256, "actual": actual, "path": str(path)},
        )


def extract_archive(archive: Path, destination: Path, archive_type: str) -> Path:
    ensure_directory(destination)
    if archive_type == "zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(destination)
    elif archive_type == "tar":
        with tarfile.open(archive) as tf:
            tf.extractall(destination)
    else:
        raise RuntimeError(f"Unsupported archive type: {archive_type}")
    return destination


def detect_runtime_root(extracted_root: Path, archive_subdir: Optional[str]) -> Path:
    if archive_subdir:
        candidate = extracted_root / archive_subdir
        if candidate.exists():
            return candidate

    python_dirs = list(extracted_root.rglob("python"))
    for candidate in python_dirs:
        if candidate.is_dir():
            return candidate.parent

    raise RuntimeError(
        "Could not locate OpenVSP runtime in extracted archive",
        {"extracted_root": str(extracted_root)},
    )


def install_runtime(
    metadata: Dict[str, object],
    platform_key: str,
    *,
    cache_root: Path,
    force: bool,
    create_pth: bool,
    site_packages_dir: Optional[Path] = None,
) -> InstallResult:
    version = str(metadata.get("version", "unknown"))
    platforms = metadata.get("platforms", {})
    if platform_key not in platforms:
        raise RuntimeError(f"Platform '{platform_key}' is not defined in metadata")

    platform_spec = PlatformSpec.from_dict(platform_key, platforms[platform_key])

    install_root = cache_root / version / platform_key
    marker_path = install_root / INSTALL_MARKER

    if install_root.exists() and not force:
        if marker_path.exists():
            with marker_path.open("r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            if manifest.get("version") == version and manifest.get("platform") == platform_key:
                python_dir = install_root / manifest.get("python_subdir", platform_spec.python_subdir)
                if python_dir.exists():
                    return build_result(
                        version=version,
                        platform_spec=platform_spec,
                        install_root=install_root,
                        python_dir=python_dir,
                        archive_path=None,
                    )
        if force:
            shutil.rmtree(install_root)
        else:
            raise RuntimeError(
                "Existing OpenVSP installation is incompatible. Use --force to reinstall.",
                {"install_root": str(install_root)},
            )

    downloads_dir = cache_root / "downloads"
    archive_path = downloads_dir / f"{platform_key}-{version}.{platform_spec.archive_type}"

    try:
        archive_path = download_file(platform_spec.url, archive_path)
    except (HTTPError, URLError) as exc:
        raise RuntimeError(
            "Failed to download OpenVSP archive",
            {"url": platform_spec.url, "error": str(exc)},
        ) from exc

    verify_checksum(archive_path, platform_spec.sha256)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        extract_root = extract_archive(archive_path, tmp_path, platform_spec.archive_type)
        runtime_root = detect_runtime_root(extract_root, platform_spec.archive_subdir)
        if install_root.exists():
            shutil.rmtree(install_root)
        ensure_directory(install_root.parent)
        shutil.move(str(runtime_root), str(install_root))

    marker_payload = {
        "version": version,
        "platform": platform_key,
        "python_subdir": platform_spec.python_subdir,
        "url": platform_spec.url,
    }
    ensure_directory(install_root)
    with marker_path.open("w", encoding="utf-8") as handle:
        json.dump(marker_payload, handle, indent=2)

    python_dir = install_root / platform_spec.python_subdir
    if create_pth:
        site_dir = site_packages_dir or Path(sysconfig.get_paths()["purelib"])
        ensure_directory(site_dir)
        pth_path = site_dir / PTH_FILENAME
        with pth_path.open("w", encoding="utf-8") as handle:
            handle.write(str(python_dir.resolve()) + os.linesep)

    return build_result(
        version=version,
        platform_spec=platform_spec,
        install_root=install_root,
        python_dir=python_dir,
        archive_path=archive_path,
    )


def build_result(
    *,
    version: str,
    platform_spec: PlatformSpec,
    install_root: Path,
    python_dir: Path,
    archive_path: Optional[Path],
) -> InstallResult:
    path_entries: List[Path] = []
    library_paths: Dict[str, List[Path]] = {}

    for relative in platform_spec.library_subdirs:
        target = install_root / relative if relative else install_root
        if target.exists():
            path_entries.append(target)

    # Configure dynamic library hints for POSIX systems.
    if platform_spec.key == "linux":
        library_paths["LD_LIBRARY_PATH"] = path_entries
    elif platform_spec.key == "macos":
        library_paths["DYLD_LIBRARY_PATH"] = path_entries

    return InstallResult(
        version=version,
        platform_key=platform_spec.key,
        install_root=install_root,
        python_dir=python_dir,
        path_entries=path_entries,
        library_paths=library_paths,
        archive_path=archive_path,
    )


def parse_arguments(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install the OpenVSP runtime used by Streamline.")
    parser.add_argument("--platform", choices=["windows", "linux", "macos"], help="Target platform override.")
    parser.add_argument("--metadata", type=Path, default=Path(__file__).with_name("openvsp.json"), help="Path to the metadata file.")
    parser.add_argument("--cache-root", type=Path, help=f"Installation cache root (default: ${DEFAULT_CACHE_ENV} or {DEFAULT_CACHE_DIRNAME}).")
    parser.add_argument("--force", action="store_true", help="Reinstall even if the runtime is already present.")
    parser.add_argument("--no-pth", action="store_true", help="Skip writing a .pth file into the current environment.")
    parser.add_argument("--site-packages", type=Path, help="Explicit site-packages directory for the .pth file.")
    parser.add_argument("--export", type=Path, help="Write installation metadata as JSON to the given path.")
    parser.add_argument("--print-json", action="store_true", help="Print installation metadata as JSON to stdout.")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_arguments(argv)

    cache_root = args.cache_root
    if cache_root is None:
        cache_root = Path(os.environ.get(DEFAULT_CACHE_ENV, DEFAULT_CACHE_DIRNAME))
    ensure_directory(cache_root)

    metadata = load_metadata(args.metadata)
    platform_key = determine_platform_name(args.platform)

    try:
        result = install_runtime(
            metadata,
            platform_key,
            cache_root=cache_root,
            force=args.force,
            create_pth=not args.no_pth,
            site_packages_dir=args.site_packages,
        )
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"OpenVSP installation failed: {exc}") from exc

    if args.export:
        ensure_directory(args.export.parent)
        with args.export.open("w", encoding="utf-8") as handle:
            json.dump(result.to_json_dict(), handle, indent=2)

    if args.print_json:
        json.dump(result.to_json_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"Installed OpenVSP {result.version} for {result.platform_key} at {result.install_root}")
        print(f"Python bindings exposed via {result.python_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
