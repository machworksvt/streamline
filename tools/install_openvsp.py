from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import site
import sys
import sysconfig
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_CACHE_ENV = "STREAMLINE_OPENVSP_HOME"
DEFAULT_CACHE_DIRNAME = Path.home() / ".cache" / "openvsp"
INSTALL_MARKER = "install_manifest.json"
PTH_FILENAME = "openvsp-runtime.pth"
REQUIRED_SYMBOLS = ["AddGeom", "ClearVSPModel", "SetGeomName", "SetParmVal", "GetParmVal", "Update"]
MIN_SYMBOLS = ["AddGeom"]

@dataclass
class PlatformSpec:
    key: str
    url: str
    archive_type: str
    archive_subdir: Optional[str]
    python_subdir: str
    library_subdirs: List[str]
    sha256: Optional[str]
    python_versions: Optional[List[str]]

    @classmethod
    def from_dict(cls, key: str, data: Dict[str, object]) -> "PlatformSpec":
        return cls(
            key=key,
            url=str(data["url"]),
            archive_type=str(data.get("archive_type", "zip")),
            archive_subdir=str(data.get("archive_subdir")) if data.get("archive_subdir") else None,
            python_subdir=str(data.get("python_subdir", "python")),
            library_subdirs=[str(x) for x in data.get("library_subdirs", [])],
            sha256=str(data["sha256"]) if data.get("sha256") else None,
            python_versions=[str(x) for x in data.get("python_versions", [])] or None,
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
    module_file: Optional[str]
    missing: List[str]

    def to_json_dict(self) -> Dict[str, object]:
        return {
            "version": self.version,
            "platform": self.platform_key,
            "install_root": str(self.install_root),
            "python_dir": str(self.python_dir),
            "path_entries": [str(p) for p in self.path_entries],
            "library_paths": {k: [str(p) for p in v] for k, v in self.library_paths.items()},
            "archive_path": str(self.archive_path) if self.archive_path else None,
            "module_file": self.module_file,
            "missing": self.missing,
        }

# --- helpers ---

def determine_platform_name(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit.lower()
    sysname = platform.system().lower()
    if sysname.startswith("win"):
        return "windows"
    if sysname.startswith("linux"):
        return "linux"
    if sysname.startswith("darwin") or sysname.startswith("mac"):
        return "macos"
    raise RuntimeError(f"Unsupported operating system: {platform.system()}")

def load_metadata(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))

def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

# --- download / extract ---

def download_file(url: str, destination: Path, *, archive_type: str) -> Path:
    ensure_directory(destination.parent)
    force_curl = os.getenv("STREAMLINE_OPENVSP_FORCE_CURL", "1").strip().lower() not in {"0","false","no","off"}
    tried = []

    def attempt_urllib() -> bool:
        try:
            req = Request(url, headers={"User-Agent": "streamline-openvsp-installer", "Accept": "*/*"})
            with urlopen(req) as r, destination.open("wb") as h:  # nosec
                shutil.copyfileobj(r, h)
            return True
        except Exception:
            return False

    def attempt_curl() -> bool:
        curl = shutil.which("curl")
        if not curl:
            return False
        import subprocess
        cmd = [curl, "-L", "--fail", "-A", "streamline-openvsp-installer", "-o", str(destination), url]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if p.returncode != 0:
                p = subprocess.run([curl, "-L", "-A", "streamline-openvsp-installer", "-o", str(destination), url], capture_output=True, text=True, timeout=180)
            return p.returncode == 0
        except Exception:
            return False

    if force_curl:
        if attempt_curl():
            tried.append("curl")
        elif attempt_urllib():
            tried.append("urllib")
    else:
        if attempt_urllib():
            tried.append("urllib")
        elif attempt_curl():
            tried.append("curl")

    if not destination.exists():
        raise RuntimeError("Download failed", {"url": url, "attempts": tried})

    size = destination.stat().st_size
    if size < 100_000:  # basic sanity threshold
        raise RuntimeError("Downloaded file too small; likely HTML or blocked", {"size": size, "url": url})
    return destination

def verify_checksum(path: Path, expected_sha256: Optional[str]) -> None:
    if not expected_sha256:
        return
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual.lower() != expected_sha256.lower():
        raise RuntimeError("Checksum mismatch", {"expected": expected_sha256, "actual": actual})

def extract_archive(archive: Path, destination: Path, archive_type: str) -> Path:
    ensure_directory(destination)
    if archive_type == "zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(destination)
    elif archive_type == "tar":
        with tarfile.open(archive) as t:
            t.extractall(destination)
    else:
        raise RuntimeError(f"Unsupported archive type: {archive_type}")
    return destination

def detect_runtime_root(extracted_root: Path, archive_subdir: Optional[str]) -> Path:
    if archive_subdir:
        cand = extracted_root / archive_subdir
        if cand.exists():
            return cand
    # fallback: first dir with 'python'
    for p in extracted_root.iterdir():
        if p.is_dir() and (p / "python").is_dir():
            return p
    # deeper search
    for p in extracted_root.rglob("python"):
        if p.is_dir():
            return p.parent
    raise RuntimeError("Could not locate OpenVSP runtime root", {"extracted_root": str(extracted_root)})

# --- result build ---

def build_result(version: str, platform_spec: PlatformSpec, install_root: Path, archive_path: Optional[Path], module_file: Optional[str], missing: List[str]) -> InstallResult:
    python_dir = install_root / platform_spec.python_subdir
    path_entries: List[Path] = []
    for rel in platform_spec.library_subdirs:
        # Ensure empty string means install_root (already covers dynamic libs root)
        target = install_root / rel if rel else install_root
        if target.exists():
            path_entries.append(target)
    # Always include install_root itself first
    if install_root not in path_entries:
        path_entries.insert(0, install_root)
    library_paths: Dict[str, List[Path]] = {}
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
        module_file=module_file,
        missing=missing,
    )

# --- dev requirements (mandatory per project requirement) ---

def install_dev_requirements(python_dir: Path) -> None:
    req = python_dir / "requirements-dev.txt"
    if not req.exists():
        raise RuntimeError("requirements-dev.txt not found in OpenVSP python directory", {"path": str(req)})
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req)], cwd=str(python_dir))

# --- core install ---

def install_runtime(metadata: Dict[str, object], platform_key: str, *, cache_root: Path, force: bool, create_pth: bool, site_packages_dir: Optional[Path]) -> InstallResult:
    version = str(metadata.get("version", "unknown"))
    platforms = metadata.get("platforms", {})
    if platform_key not in platforms:
        raise RuntimeError(f"Platform '{platform_key}' not defined in metadata")
    platform_spec = PlatformSpec.from_dict(platform_key, platforms[platform_key])

    interpreter_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if platform_spec.python_versions and interpreter_version not in platform_spec.python_versions:
        raise RuntimeError(
            "Interpreter version incompatible",
            {"interpreter": interpreter_version, "supported": platform_spec.python_versions},
        )

    # Detect if cache_root already ends with version/platform (nested path provided via env)
    parts_lower = [p.lower() for p in cache_root.parts]
    nested_style = len(parts_lower) >= 2 and parts_lower[-2] == version.lower() and parts_lower[-1] == platform_key.lower()
    if nested_style:
        install_root = cache_root
        # Base cache root is two levels up for downloads directory
        base_cache_root = cache_root.parent.parent if len(cache_root.parents) >= 2 else cache_root.parent
    else:
        install_root = cache_root / version / platform_key
        base_cache_root = cache_root

    marker_path = install_root / INSTALL_MARKER

    if install_root.exists() and not force:
        if marker_path.exists():
            try:
                manifest = json.loads(marker_path.read_text(encoding="utf-8"))
                py_dir = install_root / manifest.get("python_subdir", platform_spec.python_subdir)
                if py_dir.exists():
                    module_file, missing = attempt_import(py_dir, platform_spec)
                    return build_result(version, platform_spec, install_root, None, module_file, missing)
            except Exception:
                pass
        raise RuntimeError("Existing OpenVSP installation present (use --force to reinstall)")

    if install_root.exists() and force:
        shutil.rmtree(install_root)

    downloads_dir = base_cache_root / "downloads"
    archive_path = downloads_dir / f"{platform_key}-{version}.{platform_spec.archive_type}"
    archive_path = download_file(platform_spec.url, archive_path, archive_type=platform_spec.archive_type)
    verify_checksum(archive_path, platform_spec.sha256)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        extract_archive(archive_path, tmp, platform_spec.archive_type)
        runtime_root = detect_runtime_root(tmp, platform_spec.archive_subdir)
        ensure_directory(install_root.parent)
        if nested_style and install_root.exists():
            # After force removal we already cleared; else ensure it's empty
            pass
        shutil.move(str(runtime_root), str(install_root))

    python_dir = install_root / platform_spec.python_subdir
    if not python_dir.is_dir():
        raise RuntimeError("Python bindings directory missing", {"expected": str(python_dir)})

    install_dev_requirements(python_dir)
    module_file, missing = attempt_import(python_dir, platform_spec)
    patched = False
    if missing and 'AddGeom' in missing:
        # Try to patch wrapper by grafting compiled layer
        module_file, missing, patched = _attempt_wrapper_patch(python_dir)

    # Extra diagnostics if symbols missing
    if missing:
        pkg_root = python_dir / "openvsp"
        listing = []
        if pkg_root.is_dir():
            try:
                for p in sorted(pkg_root.iterdir()):
                    listing.append(p.name)
            except Exception:
                pass
        compiled = [p.name for p in pkg_root.rglob('_vsp*.pyd')] if pkg_root.is_dir() else []
        if module_file is None:
            module_file = "<import failed>"
        if not compiled and "_NO_COMPILED_LAYER_" not in missing:
            missing.append("_NO_COMPILED_LAYER_")
        try:
            (install_root / "python" / "openvsp_install_diagnostics.json").write_text(
                json.dumps({
                    "module_file": module_file,
                    "missing": missing,
                    "openvsp_dir_listing": listing[:200],
                    "compiled_candidates": compiled,
                    "patched": patched,
                }, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    marker_payload = {
        "version": version,
        "platform": platform_spec.key,
        "python_subdir": platform_spec.python_subdir,
        "url": platform_spec.url,
        "module_file": module_file,
        "missing": missing,
        "nested_style": nested_style,
        "patched": patched,
    }
    ensure_directory(install_root)
    marker_path.write_text(json.dumps(marker_payload, indent=2), encoding="utf-8")

    if create_pth:
        write_pth(python_dir, site_packages_dir)

    return build_result(version, platform_spec, install_root, archive_path, module_file, missing)

# --- pth ---

def write_pth(python_dir: Path, site_packages_dir: Optional[Path]) -> None:
    targets: List[Path] = []
    if site_packages_dir:
        targets.append(site_packages_dir)
    else:
        try:
            targets.append(Path(sysconfig.get_paths()["purelib"]))  # type: ignore[index]
        except Exception:
            pass
        try:
            user_site = Path(site.getusersitepackages())
            targets.append(user_site)
        except Exception:
            pass
    for t in targets:
        try:
            ensure_directory(t)
            (t / PTH_FILENAME).write_text(str(python_dir.resolve()) + os.linesep, encoding="utf-8")
            return
        except PermissionError:
            continue

# --- import attempt ---

def attempt_import(python_dir: Path, platform_spec: PlatformSpec) -> tuple[Optional[str], List[str]]:
    if str(python_dir) not in sys.path:
        sys.path.insert(0, str(python_dir))
    # Make sure dynamic lib dirs are on PATH (Windows)
    for rel in platform_spec.library_subdirs:
        target = (platform_spec.key == "windows") and (python_dir.parent / rel if rel else python_dir.parent) or None
        if target and target.exists():
            os.environ["PATH"] = str(target) + os.pathsep + os.environ.get("PATH", "")
    try:
        import importlib
        mod = importlib.import_module("openvsp")
        missing = [s for s in REQUIRED_SYMBOLS if not hasattr(mod, s)]
        # lenient: record but do not raise
        return getattr(mod, "__file__", None), missing
    except Exception:
        return None, REQUIRED_SYMBOLS[:]  # everything missing if import failed

def _attempt_wrapper_patch(python_dir: Path) -> tuple[Optional[str], List[str], bool]:
    """If the editable wrapper lacks symbols but compiled layer exists, graft them.

    Returns (module_file, missing, patched_flag).
    """
    try:
        if str(python_dir) not in sys.path:
            sys.path.insert(0, str(python_dir))
        import importlib, importlib.util
        mod = importlib.import_module('openvsp')
        if hasattr(mod, 'AddGeom'):
            missing = [s for s in REQUIRED_SYMBOLS if not hasattr(mod, s)]
            return getattr(mod, '__file__', None), missing, False
        spec = importlib.util.find_spec('openvsp._vsp')
        if not spec:
            return getattr(mod, '__file__', None), REQUIRED_SYMBOLS[:], False
        core = importlib.import_module('openvsp._vsp')
        if hasattr(core, 'AddGeom'):
            for name in dir(core):
                if not name.startswith('_') and not hasattr(mod, name):
                    try:
                        setattr(mod, name, getattr(core, name))
                    except Exception:
                        pass
            if hasattr(core, 'VSPVersion') and not hasattr(mod, 'GetVSPVersion'):
                try:
                    mod.GetVSPVersion = core.VSPVersion  # type: ignore[attr-defined]
                except Exception:
                    pass
        missing = [s for s in REQUIRED_SYMBOLS if not hasattr(mod, s)]
        return getattr(mod, '__file__', None), missing, True
    except Exception:
        return None, REQUIRED_SYMBOLS[:], False

# --- cli ---

def parse_arguments(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Install the OpenVSP runtime (stable interface).")
    p.add_argument("--platform", choices=["windows", "linux", "macos"], help="Platform override")
    p.add_argument("--metadata", type=Path, default=Path(__file__).with_name("openvsp.json"), help="Metadata JSON path")
    p.add_argument("--cache-root", type=Path, help="Cache root (default env or ~/.cache/openvsp)")
    p.add_argument("--force", action="store_true", help="Force reinstall")
    p.add_argument("--no-pth", action="store_true", help="Skip .pth creation")
    p.add_argument("--site-packages", type=Path, help="Explicit site-packages for .pth")
    p.add_argument("--export", type=Path, help="Write manifest JSON to path")
    p.add_argument("--print-json", action="store_true", help="Print manifest JSON to stdout")
    p.add_argument("--env-file", type=Path, help="Write a shell-friendly env file with OPENVSP vars")
    return p.parse_args(argv)

# --- cache root sanitization to avoid recursive nesting of version/platform ---

def _sanitize_cache_root(raw: Path, version: str, platform_key: str) -> Path:
    segs = list(raw.parts)
    # Collect indices where version/platform pair begins
    idxs = [i for i in range(len(segs) - 1) if segs[i].lower() == version.lower() and segs[i+1].lower() == platform_key.lower()]
    if not idxs:
        return raw
    # If multiple occurrences, truncate at first occurrence parent (base cache root)
    if len(idxs) > 1:
        base_parts = segs[:idxs[0]]
        if not base_parts:  # fallback to default ~/.cache/openvsp
            return DEFAULT_CACHE_DIRNAME
        return Path(*base_parts)
    # Single occurrence but path ends WITH version/platform (normal) -> ok
    i0 = idxs[0]
    if i0 == len(segs) - 2:
        return raw  # expected pattern <cache_root>/<version>/<platform>
    # Occurs but additional trailing duplicate segments follow -> truncate
    base_parts = segs[:i0]
    if not base_parts:
        return DEFAULT_CACHE_DIRNAME
    return Path(*base_parts)

def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_arguments(argv)
    metadata = load_metadata(args.metadata)
    # Determine platform early for sanitization
    tmp_platform_key = determine_platform_name(args.platform)
    version = str(metadata.get("version", "unknown"))
    raw_env = os.environ.get(DEFAULT_CACHE_ENV)
    if args.cache_root:
        cache_root = args.cache_root
    else:
        if raw_env:
            env_path = Path(raw_env)
            sanitized = _sanitize_cache_root(env_path, version, tmp_platform_key)
            if sanitized != env_path:
                print(f"[install_openvsp] Normalized cache root '{env_path}' -> '{sanitized}'", file=sys.stderr)
            # If env path already inside version/platform, prefer sanitized parent
            cache_root = sanitized
        else:
            cache_root = DEFAULT_CACHE_DIRNAME
    ensure_directory(cache_root)
    platform_key = tmp_platform_key
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

    data = result.to_json_dict()
    if args.export:
        ensure_directory(args.export.parent)
        args.export.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if args.env_file:
        lines = [
            f"OPENVSP_HOME={data['install_root']}",
            f"STREAMLINE_OPENVSP_HOME={data['install_root']}",
            f"OPENVSP_PYTHON_DIR={data['python_dir']}",
            f"STREAMLINE_OPENVSP_PYTHON_DIR={data['python_dir']}",
            f"# Add to PATH (example):", "# set PATH=%OPENVSP_HOME%;%OPENVSP_HOME%\\bin;%OPENVSP_HOME%\\vspaero_ex;%PATH%", "",
        ]
        ensure_directory(args.env_file.parent)
        args.env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.print_json:
        json.dump(data, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"Installed OpenVSP {data['version']} for {data['platform']} at {data['install_root']}")
        if data.get("missing"):
            print(f"Missing symbols: {', '.join(data['missing'])}")
        if args.env_file:
            print(f"Wrote env file: {args.env_file}")
    return 0

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
