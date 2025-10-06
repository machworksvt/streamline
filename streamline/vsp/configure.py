from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..core.schema import Configuration
from .sets import list_sets
from .util import apply_udp_overrides


@dataclass
class AppliedConfiguration:
    config_id: Optional[str]
    mode_id: Optional[str]
    use_mode_flag: Optional[bool]
    geom_set_index: Optional[int]
    geom_set_name: Optional[str]
    applied_var_presets: List[Tuple[str, str]]
    parm_overrides: Dict[str, float]


def _match_set_index(vsp, candidate: Optional[str]) -> Optional[int]:
    if not candidate:
        return None
    try:
        mapping = list_sets(vsp)
    except Exception:
        return None
    for idx, name in mapping.items():
        if name and name.lower() == candidate.lower():
            return idx
    return None


def _resolve_set_details(
    vsp,
    configuration: Configuration,
    fallback_set_index: Optional[int] = None,
    fallback_set_name: Optional[str] = None,
) -> Tuple[Optional[int], Optional[str]]:
    set_idx = configuration.geom_set_index
    set_name = configuration.geom_set_name

    if set_idx is None and set_name:
        set_idx = _match_set_index(vsp, set_name)

    if set_idx is None and fallback_set_index is not None:
        set_idx = int(fallback_set_index)

    if set_idx is None and not set_name:
        set_idx = _match_set_index(vsp, fallback_set_name)

    mapping = {}
    try:
        mapping = list_sets(vsp)
    except Exception:
        pass

    if set_idx is not None:
        try:
            set_name = mapping.get(set_idx, set_name)
        except Exception:
            pass

    if set_idx is None and set_name:
        set_idx = _match_set_index(vsp, set_name)

    return set_idx, set_name


def _find_var_preset_group_id(vsp, group_name: str) -> Optional[str]:
    try:
        group_ids = vsp.GetVarPresetGroups()
    except Exception:
        return None
    for gid in group_ids:
        try:
            if vsp.GetGroupName(gid) == group_name:
                return gid
        except Exception:
            continue
    return None


def _find_var_preset_setting_id(vsp, group_id: str, setting_name: str) -> Optional[str]:
    try:
        setting_ids = vsp.GetVarPresetSettings(group_id)
    except Exception:
        return None
    for sid in setting_ids:
        try:
            if vsp.GetSettingName(sid) == setting_name:
                return sid
        except Exception:
            continue
    return None


def apply_configuration(
    vsp,
    configuration: Configuration,
    *,
    fallback_set_index: Optional[int] = None,
    fallback_set_name: Optional[str] = None,
) -> AppliedConfiguration:
    """Apply configuration selections (mode, presets, overrides) to the active VSP model."""
    mode_id: Optional[str] = None
    use_mode_flag: Optional[bool] = None

    if configuration.mode:
        mode_id = configuration.mode.mode_id
        use_mode_flag = configuration.mode.use_mode_flag
        if mode_id:
            try:
                vsp.ApplyModeSettings(mode_id)
            except Exception as exc:
                raise ValueError(
                    f"Failed to ApplyModeSettings for mode '{mode_id}' in configuration '{configuration.config_id}'"
                ) from exc

    applied_presets: List[Tuple[str, str]] = []
    for ref in configuration.var_presets:
        gid = _find_var_preset_group_id(vsp, ref.group_name)
        if gid is None:
            raise ValueError(
                f"Variable preset group '{ref.group_name}' not found for configuration '{configuration.config_id}'"
            )
        sid = _find_var_preset_setting_id(vsp, gid, ref.setting_name)
        if sid is None:
            raise ValueError(
                f"Variable preset setting '{ref.setting_name}' not found in group '{ref.group_name}'"
            )
        try:
            vsp.ApplyVarPresetSetting(gid, sid)
        except Exception as exc:
            raise ValueError(
                f"Failed to apply variable preset setting '{ref.setting_name}' in group '{ref.group_name}'"
            ) from exc
        applied_presets.append((ref.group_name, ref.setting_name))

    geom_set_index, geom_set_name = _resolve_set_details(
        vsp,
        configuration,
        fallback_set_index=fallback_set_index,
        fallback_set_name=fallback_set_name,
    )

    parm_overrides: Dict[str, float] = {}
    if configuration.udp_overrides:
        parm_overrides.update(configuration.udp_overrides)
    if configuration.runtime_overrides:
        parm_overrides.update(configuration.runtime_overrides)

    if parm_overrides:
        apply_udp_overrides(vsp, parm_overrides)

    try:
        vsp.Update()
    except Exception:
        pass

    return AppliedConfiguration(
        config_id=configuration.config_id,
        mode_id=mode_id,
        use_mode_flag=use_mode_flag,
        geom_set_index=geom_set_index,
        geom_set_name=geom_set_name,
        applied_var_presets=applied_presets,
        parm_overrides=parm_overrides,
    )
