from __future__ import annotations

import json
import pathlib
from typing import Any, Dict

import pandas as pd

from ..core.schema import (
    Configuration,
    MissionDefinition,
    OperatingPoint,
    PowerplantDefinition,
    ProjectDefinition,
)

PathLike = str | pathlib.Path


def _p(p: PathLike) -> pathlib.Path:
    return pathlib.Path(p).resolve()


# ---------- project root ----------

def project_root(path: PathLike) -> pathlib.Path:
    root = _p(path)
    if not root.exists():
        raise FileNotFoundError(root)
    return root


# ---------- json helpers ----------

def read_json(path: PathLike) -> Dict[str, Any]:
    return json.loads(_p(path).read_text(encoding="utf-8"))


def write_json(data: Dict[str, Any], path: PathLike) -> None:
    target = _p(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------- project definition ----------

def load_project_def(proj_dir: PathLike) -> ProjectDefinition:
    root = project_root(proj_dir)
    raw = read_json(root / f"{root.name}.json")
    return ProjectDefinition.model_validate(raw)


def save_project_def(model: ProjectDefinition, proj_dir: PathLike) -> None:
    root = project_root(proj_dir)
    write_json(json.loads(model.model_dump_json()), root / f"{root.name}.json")


# ---------- sub-entities ----------

def load_mission(path: PathLike) -> MissionDefinition:
    return MissionDefinition.model_validate(read_json(path))


def load_powerplant(path: PathLike) -> PowerplantDefinition:
    return PowerplantDefinition.model_validate(read_json(path))


def load_op(path: PathLike) -> OperatingPoint:
    return OperatingPoint.model_validate(read_json(path))


def load_config(path: PathLike) -> Configuration:
    return Configuration.model_validate(read_json(path))


# ---------- dataframe csv ----------

def write_df_csv(df: pd.DataFrame, path: PathLike) -> None:
    target = _p(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(target)


def read_df_csv(path: PathLike, **kwargs) -> pd.DataFrame:
    return pd.read_csv(_p(path), **kwargs)


# ---------- receipts index ----------

def load_receipts_index(path: PathLike) -> Dict[str, Any]:
    return read_json(path)


def save_receipts_index(data: Dict[str, Any], path: PathLike) -> None:
    write_json(data, path)
