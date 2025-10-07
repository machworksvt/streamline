import os
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any


@contextmanager
def vsp_working_dir(path: Path):
    """Context manager to run VSPAERO analyses inside ``path``."""
    path.mkdir(parents=True, exist_ok=True)
    old_cwd = os.getcwd()
    try:
        os.chdir(str(path))
        yield
    finally:
        os.chdir(old_cwd)


def prepare_results_dir(results_root: Path, analysis_key: str, ticket_sha: str, started: Optional[datetime] = None) -> Path:
    """Create ``results_root/analysis_key/<timestamp>_<hash>`` and return it."""
    stamp = (started or datetime.utcnow()).strftime("%Y%m%dT%H%M%SZ")
    subdir = f"{stamp}_{ticket_sha[:12]}"
    run_dir = results_root / analysis_key / subdir
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def dump_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write ``payload`` to ``path`` as formatted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def relativize(path: Path, root: Path) -> str:
    """Return a path relative to ``root`` when possible."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
