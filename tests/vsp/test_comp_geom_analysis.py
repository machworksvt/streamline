from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from streamline.vsp.analyses.comp_geom import run_comp_geom, _materialize_comp_geom
from streamline.vsp.contracts.comp_geom import CompGeomTicket, CompGeomPayload
from streamline.analysis.manager import AnalysisJob


class FakeVSP:
    def __init__(self) -> None:
        self.int_inputs: dict[tuple[str, str], list[int]] = {}
        self.updated = False
        self.deleted_ids: list[str] = []
        self.cleared_results: list[str] = []

    def SetAnalysisInputDefaults(self, analysis: str) -> None:
        self.defaults = analysis

    def SetIntAnalysisInput(self, analysis: str, name: str, values):
        if analysis != "CompGeom":
            raise RuntimeError("unexpected analysis")
        if name == "FileExportFlags" and values[0] < 0:
            raise RuntimeError("bad value")
        self.int_inputs[(analysis, name)] = list(values)

    def Update(self) -> None:
        self.updated = True

    def ExecAnalysis(self, analysis: str) -> str:
        assert analysis == "CompGeom"
        return "results-id"

    def GetAllDataNames(self, results_id: str):
        assert results_id == "results-id"
        return ["Wet_Area", "Mesh_GeomID", "Component_Wet_Area"]

    def GetResultsType(self, results_id: str, name: str) -> str:
        if name == "Mesh_GeomID":
            return "RES_DATA_STRING"
        return "RES_DATA_DOUBLE"

    def GetDoubleResults(self, results_id: str, name: str):
        if name == "Wet_Area":
            return [12.5]
        if name == "Component_Wet_Area":
            return [7.5, 5.0]
        return []

    def GetStringResults(self, results_id: str, name: str):
        if name == "Mesh_GeomID":
            return ["mesh_1"]
        return []

    def DeleteGeomVec(self, geom_ids):
        self.deleted_ids.extend(list(geom_ids))

    def ClearResults(self, results_id: str):
        self.cleared_results.append(results_id)

    def GetSetName(self, idx: int) -> str:
        return {2: "MySet"}.get(idx, "")

    def GetNumSets(self) -> int:
        return 3


@pytest.fixture()
def fake_manager(tmp_path):
    project_root = tmp_path / "project"
    results_root = project_root / "results"
    results_root.mkdir(parents=True, exist_ok=True)
    manager = SimpleNamespace(results_root=results_root, versions={"openvsp_api": "test"})
    return manager


def test_run_comp_geom_collects_results_and_sets_inputs():
    vsp = FakeVSP()
    ticket = CompGeomTicket(set_index=2, half_mesh_flag=True, write_csv_flag=False, file_export_types=[1, 2])

    payload = run_comp_geom(vsp, ticket)

    assert isinstance(payload, CompGeomPayload)
    assert vsp.int_inputs[("CompGeom", "Set")] == [2]
    assert vsp.int_inputs[("CompGeom", "HalfMeshFlag")] == [1]
    assert vsp.int_inputs[("CompGeom", "WriteCSVFlag")] == [0]
    assert vsp.int_inputs[("CompGeom", "FileExportFlags")] == [3]
    assert payload.summary["Wet_Area"] == pytest.approx(12.5)
    assert payload.results_data["Component_Wet_Area"] == pytest.approx([7.5, 5.0])
    assert vsp.deleted_ids == ["mesh_1"]
    assert vsp.cleared_results == ["results-id"]


def test_materialize_comp_geom_writes_artifacts(fake_manager):
    ticket = CompGeomTicket(set_index=1, half_mesh_flag=False)
    payload = CompGeomPayload(
        analysis_name="CompGeom",
        set_index=1,
        set_name="All",
        half_mesh_flag=False,
        write_csv_flag=True,
        file_export_mask=4,
        results_available={"Wet_Area": "RES_DATA_DOUBLE"},
        summary={"Wet_Area": 10.0},
        results_data={"Wet_Area": [10.0]},
        mesh_geom_ids=["mesh_1"],
        applied_var_presets=[],
        parm_overrides={},
    )
    started = datetime.utcnow()
    ended = started + timedelta(seconds=5)
    job = AnalysisJob(
        job_id="job",
        analysis_key="comp_geom",
        ticket=ticket,
        context_extras={},
        runtime_kwargs={},
        dependency_keys=set(),
        wait_for=set(),
        priority=0,
    )
    ticket_sha = ticket.sha256()

    receipt = _materialize_comp_geom(fake_manager, job, ticket_sha, payload, started, ended)

    run_dirs = list(fake_manager.results_root.glob("comp_geom/*"))
    assert run_dirs, "run directory not created"
    run_dir = run_dirs[0]
    assert (run_dir / "ticket.json").exists()
    assert (run_dir / "settings.json").exists()
    assert (run_dir / "results.json").exists()
    manifest_path = run_dir / "run_manifest.json"
    assert manifest_path.exists()

    index_path = fake_manager.results_root.parent / "results" / "index.json"
    assert index_path.exists()

    assert receipt.summary == {"Wet_Area": 10.0}
    assert receipt.available_results == {"Wet_Area": "RES_DATA_DOUBLE"}
