from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from ..core.errors import ConfigCatalogError
from ..core.logging import get_logger
from ..core.schema import Configuration, ProjectDefinition
from .fs import load_config, load_project_def


@dataclass
class ConfigSummary:
    config_id: str
    path: Path
    mode_id: Optional[str]
    set_name: Optional[str]
    set_index: Optional[int]
    has_presets: bool
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
        configs.append(
            ConfigSummary(
                config_id=cfg.config_id,
                path=cfg_path,
                mode_id=cfg.mode.mode_id if cfg.mode else None,
                set_name=cfg.geom_set_name,
                set_index=cfg.geom_set_index,
                has_presets=bool(cfg.var_presets),
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


