"""Engine bench → deck: the fits proven against a PLANTED synthetic staircase (known τ, known slew,
known ṁ(N)), the ingest against both converter timestamp spellings, the deck against the real
Icarus bags (contract-valid, deterministic, provenance honest about the missing load cell)."""

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from aerodb_contract import canonical_json, load as contract_load
from streamline.engine import deck as deck_mod, fit as fit_mod, ingest

REPO = Path(__file__).resolve().parents[1]
BENCH = REPO / "projects" / "icarus" / "engine" / "bench"


def _write_csv(path: Path, header: list[str], rows: list[list]):
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _synthetic_bag(tmp_path: Path, *, time_key="timestamp", tau=1.5, slew=10000.0,
                   plateaus=((40000, 25), (60000, 25), (90000, 25), (115000, 25), (70000, 25), (40000, 25)),
                   dt=0.1, ff_of_n=lambda n: 30.0 + 0.006 * n) -> Path:
    """An ECU that slew-limits its setpoint at `slew` rpm/s and whose rotor tracks with first-order
    τ; fuel flow a known affine function of rpm; EGT constant 550 °C once lit."""
    d = tmp_path / "rosbag2_synth"
    d.mkdir()
    t0 = 1_700_000_000_000_000_000
    t = 0.0
    set_rpm = 40000.0
    real = 40000.0
    rows_e, rows_f = [], []
    for target, hold_s in plateaus:
        n = int(hold_s / dt)
        for _ in range(n):
            step = np.clip(target - set_rpm, -slew * dt, slew * dt)
            set_rpm += step
            real += (set_rpm - real) * (1 - np.exp(-dt / tau))
            ts = t0 + int(t * 1e9)
            rows_e.append([ts, f"{real:.1f}", f"{set_rpm:.1f}", "550", "40", "3", "RUNNING"])
            if len(rows_e) % 2 == 0:
                rows_f.append([ts, ff_of_n(real), 0.0, 18.0, 945.0])
            t += dt
    _write_csv(d / "h20pro_engine_data.csv",
               [time_key, "real_rpm", "set_rpm", "egt", "pump_power", "state", "state_name"], rows_e)
    _write_csv(d / "h20pro_fuel_ambient.csv",
               [time_key, "fuel_flow", "fuel_consumed", "ambient_temperature", "engine_box_pressure"], rows_f)
    _write_csv(d / "h20pro_throttle_command.csv", [time_key, "data"], [[t0, 10.0], [t0 + 10**9, 50.0]])
    return d


@pytest.mark.parametrize("time_key", ["timestap", "timestamp"])
def test_ingest_accepts_both_converter_timestamp_spellings(tmp_path, time_key):
    run = ingest.load_bag(_synthetic_bag(tmp_path, time_key=time_key))
    assert run.engine.t_s[0] == 0.0
    assert run.duration_s == pytest.approx(150.0, abs=0.2)
    assert run.has_throttle()
    assert set(run.file_sha256) == {"h20pro_engine_data.csv", "h20pro_fuel_ambient.csv",
                                    "h20pro_throttle_command.csv"}


def test_ingest_refuses_a_bag_without_engine_data(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(ingest.BenchIngestError, match="engine_data"):
        ingest.load_bag(tmp_path / "empty")


def test_steady_windows_find_the_planted_plateaus(tmp_path):
    run = ingest.load_bag(_synthetic_bag(tmp_path))
    ws = fit_mod.steady_windows(run)
    rpms = sorted(round(w.rpm, -3) for w in ws)
    # every plateau ≥ 40k appears (60k/90k/115k/70k/40k×2); each held ≥ 5 s at ±2%
    assert {60000, 90000, 115000, 70000, 40000} <= set(rpms), rpms
    for w in ws:
        assert w.egt_C == pytest.approx(550.0)


def test_fuel_flow_fit_recovers_the_planted_affine_law(tmp_path):
    run = ingest.load_bag(_synthetic_bag(tmp_path))
    ws = fit_mod.steady_windows(run)
    f = fit_mod.fit_fuel_flow(ws, degree=1)
    a, b = f.coeffs_ml_min_per_rpm
    assert a == pytest.approx(0.006, rel=0.02)
    assert b == pytest.approx(30.0, abs=3.0)
    assert f.rms_ml_min < 2.0
    with pytest.raises(ValueError, match="need"):
        fit_mod.fit_fuel_flow(ws[:1], degree=1)


def test_spool_fit_recovers_the_planted_tau_and_slew(tmp_path):
    run = ingest.load_bag(_synthetic_bag(tmp_path, tau=1.5, slew=10000.0))
    sp = fit_mod.fit_spool([run])
    # tracking τ from the holds; the synthetic ECU tracks symmetrically so up == down
    assert sp.tau_down_s == pytest.approx(1.5, rel=0.15), sp
    assert sp.n_down >= 1
    # slew: p90 of the 1 s-smoothed |dN/dt|. The rotor lags a rate-limited setpoint by τ·slew, so
    # over short synthetic ramps p90 reads BELOW the planted limit (a known, conservative bias —
    # documented in SpoolFit.method); it must land in [0.7, 1.0]× the planted value.
    assert 0.7 * 10000.0 < sp.slew_up_rpm_s <= 10000.0 * 1.02, sp
    assert 0.7 * 10000.0 < sp.slew_down_rpm_s <= 10000.0 * 1.02, sp


def _spec(tmp_path, bags):
    return {
        "engine": "synthetic H20", "bench_bags": bags,
        "datasheet": {"rpm_idle": 40000, "rpm_max_continuous": 118000, "rpm_max_transient": 123000,
                      "thrust_N_at_max_transient": 200.0, "fuel_g_min_at_max_thrust": 540.0,
                      "source": "datasheet"},
        "thrust_model": {"kind": "power_law", "exponent": 2.0},
        "fuel": {"capacity_kg": 4.0, "density_kg_m3": 800.0, "type": "kerosene"},
        "fuel_fit_degree": 1,
        "setting_axis_rpm": [40000, 60000, 80000, 100000, 118000, 123000],
        "thrust_line": {"point_m": [-0.4, 0.0, -0.05], "direction_b": [1.0, 0.0, 0.0]},
        "test_date": "2025-01-01", "notes": "synthetic",
    }


def test_deck_builds_contract_valid_from_synthetic_and_is_honest_about_thrust(tmp_path):
    bag = _synthetic_bag(tmp_path)
    (tmp_path / "bench").mkdir()
    bag.rename(tmp_path / "bench" / bag.name)
    spec_p = tmp_path / "spec.json"
    spec_p.write_text(json.dumps(_spec(tmp_path, [bag.name])))
    doc = deck_mod.build_from_spec(spec_p)
    ed = contract_load.EngineDeck.from_doc(doc)          # schema.check inside
    assert ed.thrust(123000.0) == pytest.approx(200.0)
    # the tabulated axis carries the power law exactly at its breakpoints: (60/123)^2 · 200
    assert ed.thrust(60000.0) == pytest.approx(200.0 * (60000.0 / 123000.0) ** 2)
    assert doc["static"]["source"]["thrust_N"] == "estimated"
    assert doc["static"]["source"]["fuel_flow_kg_s"] == "fitted"
    assert doc["status"] == "estimated"
    assert doc["dynamics"]["source"] == "fitted"
    assert ed.spool_time_constants_s is not None
    # planted ṁ(60k) = 30 + 360 = 390 mL/min → kg/s at 800 kg/m³
    assert ed.fuel_flow(60000.0) == pytest.approx(390.0 * 800e-6 / 60.0, rel=0.05)


def test_spec_refuses_a_non_turbojet_exponent(tmp_path):
    spec = _spec(tmp_path, ["x"])
    spec["thrust_model"]["exponent"] = 7.0
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    with pytest.raises(deck_mod.EngineSpecError, match="exponent"):
        deck_mod.load_spec(p)


@pytest.mark.skipif(not (BENCH / "rosbag2_2025_11_16-15_25_29").exists(), reason="icarus bench bags not present")
def test_icarus_deck_from_real_bench_is_valid_deterministic_and_physically_sane():
    spec_p = REPO / "projects" / "icarus" / "engine" / "spec.json"
    d1 = deck_mod.build_from_spec(spec_p)
    d2 = deck_mod.build_from_spec(spec_p)
    assert canonical_json.dumps(d1) == canonical_json.dumps(d2)
    ed = contract_load.EngineDeck.from_doc(d1)
    st = d1["static"]
    # fuel flow monotone and in the small-turbojet band: idle ~1 g/s, max ~10 g/s
    ff = np.asarray(st["fuel_flow_kg_s"])
    assert np.all(np.diff(ff) > 0)
    assert 0.0006 < ff[0] < 0.002 and 0.008 < ff[-1] < 0.013
    # TSFC in the published band for this class (g/kN/h)
    tsfc = ff / np.asarray(st["thrust_N"]) * 1e3 * 3600
    assert np.all((120 < tsfc) & (tsfc < 260)), tsfc
    # ECU dynamics as measured: ~12 kRPM/s both ways, ~1 s tracking
    dy = d1["dynamics"]
    assert 8000 < dy["slew_up_per_s"] < 16000 and 8000 < dy["slew_down_per_s"] < 18000
    assert 0.5 < dy["spool_down_time_constant_s"] < 3.0
    assert d1["limits"]["setting_max_continuous"] == 118000.0
    assert len(d1["provenance"]["bench_files"]) >= 8
