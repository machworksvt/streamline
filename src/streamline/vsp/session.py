"""The OpenVSP session: import, version pin, and the rule that canonical runs refuse an unpinned solver.

This is the only module that imports `openvsp`. Everything else takes a `Session` and calls
`session.api`, which keeps two facts in one place: which build of OpenVSP is running, and whether it
is the one the flake pins (Master Plan §8.9 #4 — "streamline refuses canonical runs on an unpinned
OpenVSP; upgrades are a deliberate event").

Two things about the `openvsp` package that shape this file:

* `openvsp_config` is read ONCE, at `import openvsp`, to choose between the headless `_vsp` module
  and the graphics `_vsp_g` module. So the graphics flag has to be set before the first import and
  cannot change afterwards in the same process. `require_openvsp(graphics=True)` after a headless
  import is refused rather than silently ignored.
* Results accumulate across `ExecAnalysis` calls in one process (index 0 is the FIRST result ever
  produced, not the latest). `Session.fresh_results()` exists so no wrapper has to remember that.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

#: The one OpenVSP this repository's artifacts are produced with. Bumping it is a reviewed event:
#: change nix/openvsp.nix, re-run the golden reference project, review the diff (plan D2/D3).
PINNED_OPENVSP = "3.51.2"


class OpenVSPMissing(RuntimeError):
    """The `openvsp` bindings are not importable — you are not in the flake's dev shell."""


class UnpinnedOpenVSP(RuntimeError):
    """The running OpenVSP is not the pinned version and the caller did not opt in."""


class GraphicsModeFixed(RuntimeError):
    """`openvsp` was already imported with the other graphics setting in this process."""


@dataclass(frozen=True)
class Session:
    api: object
    version: str
    graphics: bool

    @property
    def pinned(self) -> bool:
        return self.version == PINNED_OPENVSP

    def fresh_results(self) -> None:
        """Forget every result held by the API. Call before an `ExecAnalysis` whose output you will
        read back with `FindLatestResultsID` — otherwise a stale result from an earlier run in the
        same process is one off-by-one away."""
        self.api.DeleteAllResults()

    def latest(self, name: str) -> str:
        """The results id of the most recent result set called `name`, or raise — a missing result
        set means the solve did not happen, and reading index 0 would hand back an older one."""
        rid = self.api.FindLatestResultsID(name)
        if not rid:
            raise LookupError(f"no '{name}' result set — did the analysis run?")
        return rid

    @contextlib.contextmanager
    def workdir(self, path: Path | None = None) -> Iterator[Path]:
        """chdir into a scratch directory for the duration of a solve. VSPAERO writes its case,
        history and stability files next to the model in the CURRENT directory; a run that leaves
        them beside a committed .vsp3 is a run that just dirtied the repo."""
        cwd = Path.cwd()
        made = path is None
        d = Path(tempfile.mkdtemp(prefix="streamline_")) if made else Path(path)
        d.mkdir(parents=True, exist_ok=True)
        os.chdir(d)
        try:
            yield d
        finally:
            os.chdir(cwd)


_SESSION: Session | None = None


def _parse_version(s: str) -> str:
    m = re.search(r"(\d+\.\d+\.\d+)", s)
    if not m:
        raise OpenVSPMissing(f"could not parse an OpenVSP version out of {s!r}")
    return m.group(1)


def require_openvsp(*, graphics: bool = False, allow_unpinned: bool = False) -> Session:
    """Import the bindings once, check the pin, and hand back the session.

    `graphics=True` loads the GUI-capable module (for `streamline gui`); it is a process-wide,
    one-shot choice. `allow_unpinned=True` is for exploration on a machine that is not the flake;
    every artifact produced under it records `unpinned: true` and the release lint refuses it.
    """
    global _SESSION
    if _SESSION is not None:
        if _SESSION.graphics != graphics:
            raise GraphicsModeFixed(
                f"openvsp is already loaded with graphics={_SESSION.graphics}; start a new process")
        if not (_SESSION.pinned or allow_unpinned):
            raise UnpinnedOpenVSP(_unpinned_msg(_SESSION.version))
        return _SESSION

    try:
        cfg = importlib.import_module("openvsp_config")
    except ModuleNotFoundError as e:
        raise OpenVSPMissing(
            "openvsp_config is not importable — run inside `nix develop` (flake.nix pins OpenVSP "
            f"{PINNED_OPENVSP}); a conda or system Python will not have it") from e
    cfg.LOAD_GRAPHICS = bool(graphics)
    cfg.LOAD_FACADE = False
    cfg.LOAD_MULTI_FACADE = False

    if "openvsp" in sys.modules:
        raise GraphicsModeFixed("openvsp was imported outside require_openvsp(); refusing to guess")
    try:
        api = importlib.import_module("openvsp")
    except ImportError as e:
        raise OpenVSPMissing(f"openvsp bindings failed to import: {e}") from e

    version = _parse_version(api.GetVSPVersion())
    session = Session(api=api, version=version, graphics=graphics)
    if not (session.pinned or allow_unpinned):
        raise UnpinnedOpenVSP(_unpinned_msg(version))
    _SESSION = session
    return session


def _unpinned_msg(version: str) -> str:
    return (f"OpenVSP {version} is running but {PINNED_OPENVSP} is pinned. Canonical runs refuse "
            "an unpinned solver (Master Plan §8.9 #4). Enter the flake's dev shell, or pass "
            "allow_unpinned=True for exploration — the artifact will say so and cannot be released.")
