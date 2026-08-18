"""One JSON writer for every hashed artifact, on both sides of the contract.

Sorted keys, compact separators, shortest round-trip floats, one trailing newline, no NaN/Inf. Two
processes that hold the same numbers write the same bytes, which is what lets `MANIFEST.json`
carry a sha256 that means something and lets a determinism double-run be a byte diff
(Master Plan §10.3).

numpy scalars and arrays are converted here, on purpose, so callers never hand `json` a
`np.float32` (not a float subclass; would raise) or an `np.float64` (a float subclass — fine — but
`repr` of a numpy 2 scalar is `np.float64(0.1)`, and json's float encoder happens to use
`float.__repr__`; relying on that quietly is exactly the kind of thing that changes between
versions). Everything numeric becomes a Python `int` or `float` first.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


def to_jsonable(obj: Any) -> Any:
    """Recursively convert numpy containers/scalars to plain Python; leave everything else."""
    if isinstance(obj, np.ndarray):
        return [to_jsonable(x) for x in obj.tolist()] if obj.ndim else to_jsonable(obj.item())
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


def dumps(obj: Any) -> str:
    """The canonical text. Raises ValueError on NaN/Inf — a hole in a table is a lint failure, not
    a token in a file."""
    return json.dumps(to_jsonable(obj), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_of(obj: Any) -> str:
    return sha256_text(dumps(obj))


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path: Path | str, obj: Any) -> str:
    """Write canonically; return the sha256 of the bytes written."""
    text = dumps(obj)
    Path(path).write_text(text, encoding="utf-8", newline="\n")
    return sha256_text(text)


def read(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))
