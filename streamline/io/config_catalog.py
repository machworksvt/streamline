from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

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


class ConfigCatalogError(RuntimeError):
    pass


def load_config_catalog(project_root: Path) -> List[ConfigSummary]:
    project = load_project_def(project_root)
    configs: List[ConfigSummary] = []
    seen_ids: Dict[str, Path] = {}
    for rel_path in project.references.get("configs", []):
        cfg_path = project_root / rel_path
        try:
            cfg = load_config(cfg_path)
        except Exception as exc:
            raise ConfigCatalogError(f"Failed to load configuration '{rel_path}': {exc}") from exc
        if cfg.config_id in seen_ids:
            other = seen_ids[cfg.config_id]
            raise ConfigCatalogError(
                f"Duplicate configuration id '{cfg.config_id}' in catalog: {rel_path} and {other}"
            )
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
    raise ConfigCatalogError(f"Configuration '{config_id}' not found in catalog")


