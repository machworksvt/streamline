from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple, Any, Sequence
from pathlib import Path
from contextlib import contextmanager

from ..core.schema import Configuration, VarPresetRef, ModeRef
from .sets import list_sets
from .util import apply_udp_overrides
from ..io import fs as _fs
from . import session as _session  # new import for proper VSP session access
from ..tui.events import (
    CatalogChangedEvent,
    ConfigurationCreatedEvent,
    ConfigurationStaleEvent,
)

try:  # Replace direct import with session-based resolution first
    def _get_vsp_module():
        """Obtain the active openvsp module from session; fall back to prior import if needed."""
        # Preferred: dedicated accessor
        get_vsp = getattr(_session, "get_vsp", None)
        if callable(get_vsp):
            mod = get_vsp()
            if mod is not None:
                return mod
        # Fallback attributes
        for attr in ("vsp", "_vsp", "module"):
            mod = getattr(_session, attr, None)
            if mod is not None:
                return mod
        # Ultimate fallback: previously imported global (may be None)
        return globals().get("vsp")

    vsp = _get_vsp_module()  # rebind global reference dynamically
except Exception:  # pragma: no cover
    pass


@dataclass
class AppliedConfiguration:
    config_id: Optional[str]
    mode_id: Optional[str]
    use_mode_flag: Optional[bool]
    geom_set_index: Optional[int]
    geom_set_name: Optional[str]
    applied_var_presets: List[Tuple[str, str]]
    parm_overrides: Dict[str, float]


@dataclass
class ModeGroupSetting:
    group_id: str
    group_name: str
    setting_id: str
    setting_name: str


@dataclass
class ModeDetails:
    mode_id: str
    mode_name: Optional[str]
    use_mode_flag: Optional[bool]
    normal_set: Optional[int]
    degen_set: Optional[int]
    group_settings: List[ModeGroupSetting]


def _safe(callable_name: str, *args, default=None):
    """Call a vsp function if available; return default on failure."""
    if vsp is None:
        return default
    fn = getattr(vsp, callable_name, None)
    if not fn:
        return default
    try:
        return fn(*args)
    except Exception:  # pragma: no cover
        return default


def _resolve_group_name(group_id: Optional[str]) -> Optional[str]:
    if not group_id:
        return None
    return _safe("GetGroupName", group_id, default=group_id) or group_id


def _resolve_setting_name(setting_id: Optional[str]) -> Optional[str]:
    if not setting_id:
        return None
    return _safe("GetSettingName", setting_id, default=setting_id) or setting_id


def _clone_model(value):
    if value is None:
        return None
    model_copy = getattr(value, "model_copy", None)
    if callable(model_copy):
        return model_copy(deep=True)
    copy_fn = getattr(value, "copy", None)
    if callable(copy_fn):
        return copy_fn()
    return value


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


def list_vsp_sets() -> List[str]:
    """Return list of set names currently defined in the loaded VSP model."""
    names: List[str] = []
    n = _safe("GetNumSets", default=0) or 0
    for i in range(n):
        nm = _safe("GetSetName", i, default=None)
        if nm:
            names.append(nm)
    return names


def list_var_preset_groups() -> List[str]:
    """Return variable preset group names if supported by this OpenVSP version."""
    groups = _safe("GetVarPresetGroupNames", default=[]) or []
    return list(groups)


def list_var_presets(group: str) -> List[str]:
    presets = _safe("GetVarPresetNames", group, default=[]) or []
    return list(presets)


def snapshot_var_preset_structure() -> Dict[str, List[str]]:
    return {g: list_var_presets(g) for g in list_var_preset_groups()}


def build_ephemeral_configuration_dict(preferred_set: Optional[str] = None) -> Dict[str, Any]:
    """Build a dictionary shaped like core.schema.Configuration (subset) from current VSP state.
    This does NOT persist anything; higher layers can wrap into a Pydantic model.
    """
    sets = list_vsp_sets()
    set_name = preferred_set if preferred_set in sets else (sets[0] if sets else None)
    return {
        "geom_set_name": set_name,
        "var_presets": [],  # population left to UI; mapping groups->selected preset not yet formalized
        "udp_overrides": {},
        "runtime_overrides": {},
        "hinges": [],
        "control_surface_groups": [],
        "payloads_toggle": [],
        "notes": "Ephemeral capture from current OpenVSP model.",
    }


# --- Extended configuration GUI-bridge helpers (new) ---


class ConfigurationIntrospectionError(RuntimeError):
    pass


def list_modes() -> List[Dict[str, Any]]:
    """Best-effort enumeration of Modes (id + name). Returns empty list if unsupported."""
    modes: List[Dict[str, Any]] = []
    count = _safe("GetNumModes", default=0) or 0
    for i in range(count):
        mid = _safe("GetModeID", i, default=None)
        name = _safe("GetModeName", i, default=None)
        if mid:
            modes.append({"mode_id": mid, "name": name or f"mode_{i}"})
    return modes


def _mode_group_pairs(mode_id: str) -> List[Tuple[Optional[str], Optional[str]]]:
    groups = list(_safe("ModeGetAllGroups", mode_id, default=[]) or [])
    settings = list(_safe("ModeGetAllSettings", mode_id, default=[]) or [])
    pairs: List[Tuple[Optional[str], Optional[str]]] = []
    if groups and settings and len(groups) == len(settings):
        pairs = list(zip(groups, settings))
    else:
        count = max(len(groups), len(settings))
        if count == 0:
            count = int(_safe("ModeGetNumGroupSettings", mode_id, default=0) or 0)
        idx = 0
        while idx < count or count == 0:
            gid = groups[idx] if idx < len(groups) else _safe("ModeGetGroup", mode_id, idx, default=None)
            sid = settings[idx] if idx < len(settings) else _safe("ModeGetSetting", mode_id, idx, default=None)
            if gid is None and sid is None:
                if count == 0:
                    break
                idx += 1
                continue
            pairs.append((gid, sid))
            idx += 1
        if not pairs:
            # Attempt until failure, but cap iterations to prevent infinite loops
            for idx in range(0, 32):
                gid = _safe("ModeGetGroup", mode_id, idx, default=None)
                sid = _safe("ModeGetSetting", mode_id, idx, default=None)
                if gid is None and sid is None:
                    break
                pairs.append((gid, sid))
    return [(g, s) for g, s in pairs if g or s]


def get_mode_group_settings(mode_id: str, *, resolve_names: bool = True) -> List[ModeGroupSetting]:
    entries: List[ModeGroupSetting] = []
    for gid, sid in _mode_group_pairs(mode_id):
        group_name = _resolve_group_name(gid) if resolve_names else gid
        setting_name = _resolve_setting_name(sid) if resolve_names else sid
        entries.append(
            ModeGroupSetting(
                group_id=gid or "",
                group_name=group_name or (gid or ""),
                setting_id=sid or "",
                setting_name=setting_name or (sid or ""),
            )
        )
    return entries


def get_mode_details(mode_id: str, *, resolve_names: bool = True) -> Optional[ModeDetails]:
    if not mode_id:
        return None
    mode_entry = next((m for m in list_modes() if m.get("mode_id") == mode_id), None)
    mode_name = mode_entry.get("name") if mode_entry else None
    use_flag = _safe("GetModeUseFlag", mode_id, default=None)
    if use_flag is None:
        use_flag = _safe("GetUseModeFlag", default=None)
    normal_set = _safe("ModeGetSet", mode_id, default=None)
    if normal_set is None:
        normal_set = _safe("GetModeSet", mode_id, default=None)
    degen_set = _safe("ModeGetSubSurfaceSet", mode_id, default=None)
    if degen_set is None:
        degen_set = _safe("GetModeDegenSet", mode_id, default=None)
    group_settings = get_mode_group_settings(mode_id, resolve_names=resolve_names)
    return ModeDetails(
        mode_id=mode_id,
        mode_name=mode_name,
        use_mode_flag=bool(use_flag) if use_flag is not None else None,
        normal_set=normal_set,
        degen_set=degen_set,
        group_settings=group_settings,
    )


def list_mode_details(*, resolve_names: bool = True) -> List[ModeDetails]:
    details: List[ModeDetails] = []
    for entry in list_modes():
        mid = entry.get("mode_id")
        if not mid:
            continue
        detail = get_mode_details(mid, resolve_names=resolve_names)
        if detail:
            details.append(detail)
    return details


def get_active_mode_id() -> Optional[str]:
    return _safe("GetActiveModeID", default=None)


def capture_active_mode_ref() -> Optional[ModeRef]:
    mid = get_active_mode_id()
    if not mid:
        return None
    # Some OpenVSP versions expose a use flag; fall back to True if absent
    use_flag = _safe("GetUseModeFlag", default=True)
    name = None
    for m in list_modes():
        if m["mode_id"] == mid:
            name = m.get("name")
            break
    return ModeRef(mode_id=mid, mode_name=name, use_mode_flag=bool(use_flag))


def capture_active_var_presets() -> List[VarPresetRef]:
    """Attempt to detect which preset is active in each group.
    If API lacks an active query, returns empty (caller may prompt user).
    """
    active: List[VarPresetRef] = []
    groups = list_var_preset_groups()
    for g in groups:
        presets = list_var_presets(g)
        chosen = None
        for p in presets:
            is_active = _safe("IsVarPresetSettingActive", g, p, default=False)
            if is_active:
                chosen = p
                break
        if chosen:
            active.append(VarPresetRef(group_name=g, setting_name=chosen))
    return active


def snapshot_current_configuration(preferred_set: Optional[str] = None, *, include_mode: bool = True, include_presets: bool = True) -> Dict[str, Any]:
    base = build_ephemeral_configuration_dict(preferred_set=preferred_set)
    if include_mode:
        mode_ref = capture_active_mode_ref()
        if mode_ref:
            base["mode"] = mode_ref.model_dump()
    if include_presets and not base.get("var_presets"):
        # Only populate if caller did not already inject presets
        active_presets = capture_active_var_presets()
        if active_presets:
            base["var_presets"] = [vp.model_dump() for vp in active_presets]
    return base


def build_configuration_model(config_id: str, snapshot: Dict[str, Any]) -> Configuration:
    data = dict(snapshot)
    data["config_id"] = config_id
    # Normalize lists
    data.setdefault("var_presets", [])
    data.setdefault("control_surface_groups", [])
    data.setdefault("hinges", [])
    data.setdefault("payloads_toggle", [])
    data.setdefault("udp_overrides", {})
    data.setdefault("runtime_overrides", {})
    return Configuration(**data)


def compute_configuration_diff(existing: Configuration, snapshot: Dict[str, Any]) -> Dict[str, Tuple[Any, Any]]:
    """Return dict of changed fields -> (old, new). Only shallow comparison for now."""
    diffs: Dict[str, Tuple[Any, Any]] = {}
    fields = [
        "geom_set_name",
        "geom_set_index",
        "mode",
        "var_presets",
        "udp_overrides",
        "runtime_overrides",
        "hinges",
        "control_surface_groups",
        "payloads_toggle",
    ]
    for f in fields:
        old = getattr(existing, f)
        new = snapshot.get(f, None)
        if f == "mode" and isinstance(new, dict):
            # Coerce dict to comparable subset
            new = (new.get("mode_id"), new.get("use_mode_flag"))
            old = (old.mode_id, old.use_mode_flag) if old else None
        if f == "var_presets" and isinstance(new, list) and new and isinstance(new[0], dict):
            new = [(i.get("group_name"), i.get("setting_name")) for i in new]
            old = [(i.group_name, i.setting_name) for i in old] if old else []
        if old != new:
            diffs[f] = (old, new)
    return diffs


def save_configuration_json(project_root: Path, configuration: Configuration) -> Path:
    cfg_dir = project_root / "configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / f"{configuration.config_id}.json"
    payload = configuration.model_dump(mode="json", exclude_none=True)
    _fs.write_json(payload, path)
    checksum = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    _save_configuration_metadata(path, configuration, checksum=checksum)
    return path


def _config_metadata_path(config_path: Path) -> Path:
    return config_path.with_suffix(config_path.suffix + ".meta")


def _save_configuration_metadata(
    config_path: Path,
    configuration: Configuration,
    *,
    checksum: str,
    captured_at: Optional[datetime] = None,
) -> Path:
    meta_path = _config_metadata_path(config_path)
    meta_payload: Dict[str, Any] = {
        "metadata_version": 1,
        "config_id": configuration.config_id,
        "captured_at": (captured_at or datetime.now(timezone.utc)).isoformat(),
        "checksum_sha256": checksum,
        "mode_id": configuration.mode.mode_id if configuration.mode else None,
        "mode_use_flag": configuration.mode.use_mode_flag if configuration.mode else None,
        "preset_pairs": [
            [ref.group_name, ref.setting_name] for ref in configuration.var_presets
        ],
        "geom_set_index": configuration.geom_set_index,
        "geom_set_name": configuration.geom_set_name,
    }
    _fs.write_json(meta_payload, meta_path)
    return meta_path


def load_configuration_metadata(config_path: Path) -> Dict[str, Any]:
    meta_path = _config_metadata_path(config_path)
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def register_current_configuration(project_root: Path, config_id: str, preferred_set: Optional[str] = None) -> Configuration:
    if vsp is None:
        raise ConfigurationIntrospectionError("OpenVSP bindings not available; cannot register configuration.")
    snapshot = snapshot_current_configuration(preferred_set=preferred_set)
    model = build_configuration_model(config_id, snapshot)
    save_configuration_json(project_root, model)
    return model


def configuration_from_mode(
    config_id: str,
    mode_id: str,
    *,
    geom_set_name: Optional[str] = None,
    geom_set_index: Optional[int] = None,
    include_presets: bool = True,
    udp_overrides: Optional[Dict[str, float]] = None,
    runtime_overrides: Optional[Dict[str, float]] = None,
    notes: Optional[str] = None,
    use_mode_flag: Optional[bool] = None,
) -> Configuration:
    if vsp is None:
        raise ConfigurationIntrospectionError("OpenVSP bindings not available; cannot build configuration from mode.")
    details = get_mode_details(mode_id)
    if details is None:
        raise ConfigurationIntrospectionError(f"Mode '{mode_id}' not available in current OpenVSP session.")
    available_sets = list_vsp_sets()
    if geom_set_name is None and geom_set_index is None:
        if details.normal_set is not None:
            geom_set_index = details.normal_set
            if 0 <= geom_set_index < len(available_sets):
                geom_set_name = available_sets[geom_set_index]
        elif available_sets:
            geom_set_name = available_sets[0]
            geom_set_index = 0
    if geom_set_name is not None and geom_set_index is None:
        if available_sets and geom_set_name in available_sets:
            geom_set_index = available_sets.index(geom_set_name)
    if geom_set_index is not None and geom_set_name is None and available_sets:
        if 0 <= geom_set_index < len(available_sets):
            geom_set_name = available_sets[geom_set_index]

    presets: List[VarPresetRef] = []
    if include_presets:
        for item in details.group_settings:
            if item.group_name and item.setting_name:
                presets.append(
                    VarPresetRef(
                        group_name=item.group_name,
                        setting_name=item.setting_name,
                    )
                )
    mode_ref = ModeRef(
        mode_id=details.mode_id,
        mode_name=details.mode_name,
        use_mode_flag=use_mode_flag if use_mode_flag is not None else (details.use_mode_flag if details.use_mode_flag is not None else True),
    )
    return Configuration(
        config_id=config_id,
        mode=mode_ref,
        geom_set_index=geom_set_index,
        geom_set_name=geom_set_name,
        var_presets=presets,
        udp_overrides=dict(udp_overrides or {}),
        runtime_overrides=dict(runtime_overrides or {}),
        notes=notes or f"Generated from OpenVSP mode '{details.mode_name or details.mode_id}'",
    )


def derive_configuration(
    base: Configuration,
    new_config_id: str,
    *,
    udp_overrides: Optional[Dict[str, float]] = None,
    runtime_overrides: Optional[Dict[str, float]] = None,
    additional_presets: Optional[Iterable[VarPresetRef]] = None,
    notes: Optional[str] = None,
    mode_override: Optional[ModeRef] = None,
) -> Configuration:
    presets: List[VarPresetRef] = []
    for ref in base.var_presets:
        presets.append(_clone_model(ref))
    if additional_presets:
        existing = {(ref.group_name, ref.setting_name) for ref in presets}
        for ref in additional_presets:
            key = (ref.group_name, ref.setting_name)
            if key not in existing:
                presets.append(_clone_model(ref))
                existing.add(key)

    udp = dict(base.udp_overrides)
    if udp_overrides:
        udp.update(udp_overrides)
    runtime = dict(base.runtime_overrides)
    if runtime_overrides:
        runtime.update(runtime_overrides)

    mode_ref = _clone_model(mode_override) if mode_override is not None else _clone_model(base.mode)

    control_groups = [_clone_model(item) for item in base.control_surface_groups]
    hinges = [_clone_model(item) for item in base.hinges]
    payloads = [_clone_model(item) for item in base.payloads_toggle]

    return Configuration(
        config_id=new_config_id,
        mode=mode_ref,
        geom_set_index=base.geom_set_index,
        geom_set_name=base.geom_set_name,
        var_presets=presets,
        control_surface_groups=control_groups,
        hinges=hinges,
        payloads_toggle=payloads,
        udp_overrides=udp,
        runtime_overrides=runtime,
        notes=notes or base.notes,
    )


# Validation & creation helpers (new)

def validate_configuration_links(configuration: Configuration) -> List[str]:
    """Return list of validation error messages for missing Mode / presets / set references.
    Does NOT raise; caller can decide policy.
    """
    errors: List[str] = []
    mod = _get_vsp_module()
    if mod is None:
        errors.append("OpenVSP session not available")
        return errors

    # Mode validation
    if configuration.mode:
        available_modes = {m.get("mode_id") for m in list_modes()}
        if configuration.mode.mode_id not in available_modes:
            errors.append(f"Mode id '{configuration.mode.mode_id}' not found in current OpenVSP session")

    # Set validation (by name)
    if configuration.geom_set_name:
        sets = set(list_vsp_sets())
        if configuration.geom_set_name not in sets:
            errors.append(f"Set '{configuration.geom_set_name}' not present in current OpenVSP model")

    # Var preset groups & settings
    group_names = set(list_var_preset_groups())
    group_structure = {g: set(list_var_presets(g)) for g in group_names}
    for ref in configuration.var_presets:
        if ref.group_name not in group_names:
            errors.append(f"Var preset group '{ref.group_name}' missing")
            continue
        if ref.setting_name not in group_structure[ref.group_name]:
            errors.append(
                f"Var preset setting '{ref.setting_name}' missing in group '{ref.group_name}'"
            )
    return errors


def assert_configuration_valid(configuration: Configuration) -> None:
    errs = validate_configuration_links(configuration)
    if errs:
        raise ConfigurationIntrospectionError(
            "Configuration validation failed: " + "; ".join(errs)
        )


def create_configuration_from_active_mode(
    config_id: str,
    *,
    include_presets: bool = True,
    overrides_udp: Optional[Dict[str, float]] = None,
    overrides_runtime: Optional[Dict[str, float]] = None,
) -> Configuration:
    """Capture a Configuration from the currently active Mode (and its associated Set/presets).
    Assumes caller has already activated the desired Mode inside the GUI.
    """
    if _get_vsp_module() is None:
        raise ConfigurationIntrospectionError("No OpenVSP session; cannot snapshot mode")
    snap = snapshot_current_configuration(include_mode=True, include_presets=include_presets)
    if overrides_udp:
        snap["udp_overrides"] = {**snap.get("udp_overrides", {}), **overrides_udp}
    if overrides_runtime:
        snap["runtime_overrides"] = {**snap.get("runtime_overrides", {}), **overrides_runtime}
    cfg = build_configuration_model(config_id, snap)
    return cfg


def register_configuration_from_active_mode(
    project_root: Path,
    config_id: str,
    *,
    include_presets: bool = True,
    overrides_udp: Optional[Dict[str, float]] = None,
    overrides_runtime: Optional[Dict[str, float]] = None,
    validate: bool = True,
) -> Configuration:
    """Create + persist a Configuration derived from the currently active Mode.
    Optionally applies UDP/runtime overrides and validates references before saving.
    """
    cfg = create_configuration_from_active_mode(
        config_id,
        include_presets=include_presets,
        overrides_udp=overrides_udp,
        overrides_runtime=overrides_runtime,
    )
    if validate:
        assert_configuration_valid(cfg)
    save_configuration_json(project_root, cfg)
    return cfg


def revalidate_existing_configurations(configs: Sequence[Configuration]) -> Dict[str, List[str]]:
    """Batch revalidate multiple configurations; returns mapping config_id -> error list (empty if valid)."""
    results: Dict[str, List[str]] = {}
    for c in configs:
        results[c.config_id] = validate_configuration_links(c)
    return results


# --- Thread-safe wrappers & event emission (new) ---

# Best-effort event emission (no-op if EventBus absent)
def _publish_event(event):  # pragma: no cover
    try:
        from ..tui.event_bus import get_global_event_bus  # type: ignore
        bus = get_global_event_bus()
        if bus:
            bus.publish(event)
    except Exception:
        pass


@contextmanager
def _acquire_vsp_lock(analysis_manager=None):  # pragma: no cover - thin wrapper
    # Priority: manager's lock; fallback to session.vsp_guard(); final fallback: no-op
    if analysis_manager is not None:
        lock = getattr(analysis_manager, "_vsp_lock", None) or getattr(analysis_manager, "vsp_lock", None)
        if lock:
            with lock:
                yield
            return
    guard = getattr(_session, "vsp_guard", None)
    if callable(guard):
        with guard():
            yield
            return
    # no-op
    yield


def register_configuration_with_lock(project_root: Path, config_id: str, *, preferred_set: Optional[str] = None, analysis_manager=None, validate: bool = True) -> Configuration:
    with _acquire_vsp_lock(analysis_manager):
        cfg = register_current_configuration(project_root, config_id, preferred_set=preferred_set)
        if validate:
            errs = validate_configuration_links(cfg)
            if errs:
                raise ConfigurationIntrospectionError("Validation errors: " + "; ".join(errs))
    _publish_event(
        CatalogChangedEvent(
            kind="config",
            identifiers=(cfg.config_id,),
            project=str(project_root),
        )
    )
    _publish_event(
        ConfigurationCreatedEvent(
            config_id=cfg.config_id,
            project=str(project_root),
            source="snapshot",
        )
    )
    return cfg


def register_configuration_from_active_mode_with_lock(project_root: Path, config_id: str, *, include_presets: bool = True, overrides_udp: Optional[Dict[str, float]] = None, overrides_runtime: Optional[Dict[str, float]] = None, analysis_manager=None, validate: bool = True) -> Configuration:
    with _acquire_vsp_lock(analysis_manager):
        cfg = register_configuration_from_active_mode(
            project_root,
            config_id,
            include_presets=include_presets,
            overrides_udp=overrides_udp,
            overrides_runtime=overrides_runtime,
            validate=False,  # defer until after lock released if desired
        )
        if validate:
            assert_configuration_valid(cfg)
    _publish_event(
        CatalogChangedEvent(
            kind="config",
            identifiers=(cfg.config_id,),
            project=str(project_root),
        )
    )
    _publish_event(
        ConfigurationCreatedEvent(
            config_id=cfg.config_id,
            project=str(project_root),
            source="mode",
        )
    )
    return cfg


def revalidate_existing_configs_with_lock(configs: Sequence[Configuration], analysis_manager=None) -> Dict[str, List[str]]:
    with _acquire_vsp_lock(analysis_manager):
        result = revalidate_existing_configurations(configs)
    stale = {cid: errs for cid, errs in result.items() if errs}
    if stale:
        for cfg_id, errs in stale.items():
            _publish_event(
                ConfigurationStaleEvent(
                    config_id=cfg_id,
                    errors=tuple(errs),
                )
            )
    return result
