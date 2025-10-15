from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.errors import ConfigCatalogError
from ..core.logging import get_logger
from ..core.schema import Configuration, ProjectDefinition
from .fs import load_config, load_project_def


@dataclass
class ConfigSummary:
    config_id: str
    path: Path
    mode_id: Optional[str]
    mode_use_flag: Optional[bool]
    set_name: Optional[str]
    set_index: Optional[int]
    has_presets: bool
    preset_pairs: List[Tuple[str, str]]
    signature: str
    checksum: Optional[str]
    captured_at: Optional[str]
    metadata_path: Optional[Path]
    notes: str


def load_config_catalog(project_root: Path) -> List[ConfigSummary]:
    logger = get_logger(__name__, project=str(project_root))
    project = load_project_def(project_root)
    configs: List[ConfigSummary] = []
    seen_ids: Dict[str, Path] = {}
    for rel_path in project.references.get("configs", []):
        cfg_path = project_root / rel_path
        try:
            cfg = load_config(cfg_path)
        except Exception as exc:
            err = ConfigCatalogError(
                f"Failed to load configuration '{rel_path}': {exc}",
                context={"config_path": str(cfg_path)},
            )
            logger.error(err.message, context=err.context, code=err.code)
            raise err from exc
        if cfg.config_id in seen_ids:
            other = seen_ids[cfg.config_id]
            err = ConfigCatalogError(
                f"Duplicate configuration id '{cfg.config_id}' in catalog",
                context={
                    "config_id": cfg.config_id,
                    "path": str(cfg_path),
                    "other_path": str(other),
                },
            )
            logger.error(err.message, context=err.context, code=err.code)
            raise err
        seen_ids[cfg.config_id] = cfg_path
        metadata_path = cfg_path.with_suffix(cfg_path.suffix + ".meta")
        metadata: Dict[str, Any] = {}
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception as meta_exc:
                logger.warning(
                    "Failed to load configuration metadata",
                    context={"config_id": cfg.config_id, "metadata_path": str(metadata_path)},
                    hint=str(meta_exc),
                )
        try:
            stat = cfg_path.stat()
            signature = f"{int(stat.st_mtime_ns)}:{stat.st_size}"
        except FileNotFoundError:
            signature = "missing"
        preset_pairs_meta = metadata.get("preset_pairs") or []
        if preset_pairs_meta:
            preset_pairs = [tuple(pair) for pair in preset_pairs_meta if isinstance(pair, (list, tuple)) and len(pair) == 2]  # type: ignore[list-item]
        else:
            preset_pairs = [(ref.group_name, ref.setting_name) for ref in cfg.var_presets]
        mode_id = metadata.get("mode_id", cfg.mode.mode_id if cfg.mode else None)
        mode_use_flag = metadata.get(
            "mode_use_flag", cfg.mode.use_mode_flag if cfg.mode else None
        )
        set_index = metadata.get("geom_set_index", cfg.geom_set_index)
        set_name = metadata.get("geom_set_name", cfg.geom_set_name)
        checksum = metadata.get("checksum_sha256")
        captured_at = metadata.get("captured_at")
        configs.append(
            ConfigSummary(
                config_id=cfg.config_id,
                path=cfg_path,
                mode_id=mode_id,
                mode_use_flag=mode_use_flag,
                set_name=set_name,
                set_index=set_index,
                has_presets=bool(cfg.var_presets),
                preset_pairs=preset_pairs,
                signature=signature,
                checksum=checksum,
                captured_at=captured_at,
                metadata_path=metadata_path if metadata_path.exists() else None,
                notes=cfg.notes,
            )
        )
    return configs


def get_configuration(project_root: Path, config_id: str) -> Configuration:
    for summary in load_config_catalog(project_root):
        if summary.config_id == config_id:
            return load_config(summary.path)
    err = ConfigCatalogError(
        f"Configuration '{config_id}' not found in catalog",
        context={"config_id": config_id, "project": str(project_root)},
        hint="Verify that the configuration exists in the project references.",
    )
    get_logger(__name__).error(err.message, context=err.context, code=err.code, hint=err.hint)
    raise err


