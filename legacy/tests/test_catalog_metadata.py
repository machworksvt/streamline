from __future__ import annotations

import json
from pathlib import Path

import pytest

from streamline.core.schema import Configuration, ModeRef, OperatingPoint, VarPresetRef
from streamline.main import create_new_project
from streamline.tui.context import SessionConfig
from streamline.tui.event_bus import EventBus
from streamline.tui.session import ProjectSession
from streamline.tui import session as session_module
from streamline.vsp import configure as vsp_config
from streamline.vsp.configure import (
    ModeDetails,
    ModeGroupSetting,
    configuration_from_mode,
    derive_configuration,
    save_configuration_json,
)
from streamline.io.config_catalog import load_config_catalog
from streamline.io.op_catalog import (
    load_op_catalog,
    load_operating_point_metadata,
    save_operating_point_json,
)


class StubManager:
    def __init__(self) -> None:
        self.results_root: Path | None = None
        self.invalidate_calls: list[tuple[str, ...]] = []

    def set_results_root(self, path: Path) -> None:
        self.results_root = path

    def cache_summaries(self):
        return []

    def invalidate(self, keys):
        keys = tuple(keys)
        self.invalidate_calls.append(keys)
        return set()

    def job_state(self, job_id: str):
        raise KeyError(job_id)


def write_project_with_config(tmp_path: Path) -> Path:
    projects_root = tmp_path / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    project_root = create_new_project(projects_root, "demo")
    config = Configuration(
        config_id="clean",
        mode=ModeRef(mode_id="MODE1", mode_name="BaseMode", use_mode_flag=True),
        geom_set_index=1,
        geom_set_name="Set1",
        var_presets=[VarPresetRef(group_name="GroupA", setting_name="Setting1")],
        notes="test configuration",
    )
    save_configuration_json(project_root, config)
    op = OperatingPoint(op_name="cruise", altitude_m=250.0, mach=0.2, notes="demo op")
    save_operating_point_json(project_root, op)
    return project_root


def test_configuration_metadata_round_trip(tmp_path: Path) -> None:
    project_root = write_project_with_config(tmp_path)
    summaries = load_config_catalog(project_root)
    assert summaries, "Expected at least one configuration summary"
    summary = next(s for s in summaries if s.config_id == "clean")
    assert summary.mode_id == "MODE1"
    assert summary.mode_use_flag is True
    assert summary.preset_pairs == [("GroupA", "Setting1")]
    assert summary.metadata_path is not None and summary.metadata_path.exists()

    metadata = json.loads(summary.metadata_path.read_text(encoding="utf-8"))
    assert metadata["config_id"] == "clean"
    assert metadata["mode_id"] == "MODE1"
    assert metadata["geom_set_name"] == "Set1"
    assert metadata["preset_pairs"] == [["GroupA", "Setting1"]]


def test_operating_point_metadata_round_trip(tmp_path: Path) -> None:
    project_root = write_project_with_config(tmp_path)
    summaries = load_op_catalog(project_root)
    summary = next(s for s in summaries if s.op_id == "cruise")
    assert summary.metadata_path is not None and summary.metadata_path.exists()
    metadata = load_operating_point_metadata(summary.path)
    assert metadata.get("op_id") == "cruise"
    assert "checksum_sha256" in metadata
    assert summary.checksum == metadata.get("checksum_sha256")


def test_configuration_from_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    details = ModeDetails(
        mode_id="MODE42",
        mode_name="Mode42",
        use_mode_flag=True,
        normal_set=0,
        degen_set=None,
        group_settings=[
            ModeGroupSetting(
                group_id="GID",
                group_name="GroupA",
                setting_id="SID",
                setting_name="SettingA",
            )
        ],
    )
    monkeypatch.setattr(vsp_config, "get_mode_details", lambda mode_id, resolve_names=True: details)
    monkeypatch.setattr(session_module, "list_vsp_sets", lambda: ["Set0", "Set1"])
    monkeypatch.setattr(vsp_config, "list_vsp_sets", lambda: ["GroupSet"])
    monkeypatch.setattr(vsp_config, "vsp", object(), raising=False)

    config = configuration_from_mode(
        "generated",
        "MODE42",
        include_presets=True,
        notes="generated",
    )
    assert config.config_id == "generated"
    assert config.mode and config.mode.mode_id == "MODE42"
    assert config.var_presets == [VarPresetRef(group_name="GroupA", setting_name="SettingA")]


def test_derive_configuration_applies_overrides() -> None:
    base = Configuration(
        config_id="base",
        mode=ModeRef(mode_id="MODE_BASE", mode_name="Base", use_mode_flag=True),
        geom_set_index=2,
        geom_set_name="Set2",
        var_presets=[VarPresetRef(group_name="GroupA", setting_name="Setting1")],
        udp_overrides={"A": 1.0},
        runtime_overrides={"B": 2.0},
    )
    derived = derive_configuration(
        base,
        "derived",
        udp_overrides={"A": 3.0, "C": 4.0},
        runtime_overrides={"D": 5.0},
        additional_presets=[VarPresetRef(group_name="GroupB", setting_name="Setting2")],
        notes="derived",
    )
    assert derived.config_id == "derived"
    assert {ref.group_name for ref in derived.var_presets} == {"GroupA", "GroupB"}
    assert derived.udp_overrides["A"] == 3.0 and derived.udp_overrides["C"] == 4.0
    assert derived.runtime_overrides["B"] == 2.0
    assert derived.runtime_overrides["D"] == 5.0
    assert derived.notes == "derived"


def test_refresh_project_assets_detects_mode_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = write_project_with_config(tmp_path)

    details = ModeDetails(
        mode_id="MODE1",
        mode_name="BaseMode",
        use_mode_flag=False,
        normal_set=0,
        degen_set=None,
        group_settings=[
            ModeGroupSetting(
                group_id="GID",
                group_name="GroupA",
                setting_id="SID",
                setting_name="Setting2",
            )
        ],
    )
    monkeypatch.setattr(session_module, "list_mode_details", lambda resolve_names=True: [details])
    monkeypatch.setattr(vsp_config, "list_mode_details", lambda resolve_names=True: [details])
    monkeypatch.setattr(vsp_config, "list_vsp_sets", lambda: ["Set0", "Set1"])
    monkeypatch.setattr(vsp_config, "vsp", object(), raising=False)

    config = SessionConfig(projects_root=project_root.parent, project_id=project_root.name, auto_start_workers=False)
    manager = StubManager()
    bus = EventBus()
    session = ProjectSession(project_root=project_root, manager=manager, config=config, event_bus=bus)
    session.refresh_project_assets()

    stored = session.state.config_provenance["clean"]["preset_pairs"]
    assert stored == (("GroupA", "Setting1"),)

    actual_pairs = tuple((gs.group_name, gs.setting_name) for gs in details.group_settings)
    assert actual_pairs == (("GroupA", "Setting2"),)
    assert stored != actual_pairs
    drift = session.state.mode_drift_configs.get("clean")
    assert drift, "Expected drift messages for configuration 'clean'"
    assert any(s.mode_id == "MODE1" for s in session.state.config_catalog)
    assert any("preset assignments" in msg for msg in drift)
    assert manager.invalidate_calls, "Expected invalidate to be called for drifted configuration"
    assert "clean" in session.state.stale_configs
