"""Reduce bench runs to the deck's numbers. Every reduction is a pure function of the ingested
arrays and the declared parameters, and every step's evidence (windows found, steps fitted, R²)
comes back with the result so the deck can record it.

Three reductions:

1. `steady_windows` — stretches where the ECU held rotor speed (|Δrpm| < tol over ≥ min_s) and
   the engine was lit (EGT above a floor). These are the ṁ(N)/EGT(N) samples.
2. `fit_fuel_flow` — ṁ(N) as a monotone low-order polynomial through the steady windows plus the
   manufacturer's spec point if declared; volumetric mL/min → kg/s with a declared density.
3. `fit_spool` — first-order time constants from setpoint steps: after each step in `set_rpm`,
   fit real_rpm(t) = N_target + (N_0 − N_target)·exp(−t/τ) over the following window; up and
   down steps separately (turbojets are asymmetric: acceleration is EGT/surge-limited by the
   governor, deceleration is fuel-cut-limited). Reported with per-step R² and the count kept.

Thrust is NOT fitted here — no bench thrust exists. `deck.py` builds it from a declared model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .ingest import BenchRun


@dataclass(frozen=True)
class SteadyWindow:
    run: str
    t_start_s: float
    t_end_s: float
    rpm: float
    egt_C: float
    fuel_flow_ml_min: float
    pump_power_pct: float


def steady_windows(run: BenchRun, *, min_s: float = 5.0, rpm_tol_frac: float = 0.02,
                   rpm_floor: float = 30000.0, egt_floor_C: float = 300.0) -> list[SteadyWindow]:
    """Non-overlapping windows of ≥ min_s where rpm stays within ±rpm_tol_frac of its mean, above
    rpm_floor, with EGT above egt_floor_C (i.e. lit, not a starter crank)."""
    t = run.engine.t_s
    rpm = run.engine.cols["real_rpm"]
    egt = run.engine.cols["egt"]
    pump = run.engine.cols["pump_power"]
    ff = np.interp(t, run.fuel.t_s, run.fuel.cols["fuel_flow"])
    out = []
    i = 0
    n = t.size
    while i < n:
        j = int(np.searchsorted(t, t[i] + min_s))
        if j >= n:
            break
        seg = rpm[i:j]
        m = float(seg.mean())
        if m > rpm_floor and np.ptp(seg) < rpm_tol_frac * m and egt[i:j].mean() > egt_floor_C:
            # extend while still steady
            k = j
            while k < n and abs(rpm[k] - m) < rpm_tol_frac * m:
                k += 1
            out.append(SteadyWindow(run=run.name, t_start_s=float(t[i]), t_end_s=float(t[k - 1]),
                                    rpm=float(rpm[i:k].mean()), egt_C=float(egt[i:k].mean()),
                                    fuel_flow_ml_min=float(ff[i:k].mean()),
                                    pump_power_pct=float(pump[i:k].mean())))
            i = k
        else:
            i += 1
    return out


@dataclass(frozen=True)
class FuelFlowFit:
    coeffs_ml_min_per_rpm: tuple[float, ...]   # polynomial in N (highest power first), mL/min
    degree: int
    n_points: int
    rms_ml_min: float
    rpm_range: tuple[float, float]
    spec_point_used: bool


def fit_fuel_flow(windows: list[SteadyWindow], *, degree: int = 2,
                  spec_point: tuple[float, float] | None = None) -> FuelFlowFit:
    """Least-squares polynomial ṁ_vol(N) through the steady windows (mL/min vs rpm), optionally
    with the manufacturer's (rpm, mL/min) spec point appended. Refuses non-monotone fits over the
    data range — a turbojet's fuel flow rises with speed, full stop."""
    if len(windows) < degree + 1:
        raise ValueError(f"need ≥ {degree + 1} steady windows for a degree-{degree} fit, have {len(windows)}")
    x = np.array([w.rpm for w in windows], float)
    y = np.array([w.fuel_flow_ml_min for w in windows], float)
    if spec_point is not None:
        x = np.append(x, spec_point[0]); y = np.append(y, spec_point[1])
    c = np.polyfit(x, y, degree)
    pred = np.polyval(c, x)
    rms = float(np.sqrt(np.mean((pred - y) ** 2)))
    grid = np.linspace(x.min(), x.max(), 200)
    if np.any(np.diff(np.polyval(c, grid)) < 0):
        raise ValueError("fuel-flow fit is non-monotone over the data range; lower the degree or add points")
    return FuelFlowFit(coeffs_ml_min_per_rpm=tuple(float(v) for v in c), degree=degree,
                       n_points=int(x.size), rms_ml_min=rms,
                       rpm_range=(float(x.min()), float(x.max())), spec_point_used=spec_point is not None)


def eval_fuel_flow_ml_min(fit: FuelFlowFit, rpm: np.ndarray) -> np.ndarray:
    return np.polyval(np.asarray(fit.coeffs_ml_min_per_rpm), np.asarray(rpm, float))


@dataclass(frozen=True)
class SpoolStep:
    run: str
    t_step_s: float
    n_from: float
    n_to: float
    tau_s: float
    r2: float
    direction: str        # 'up' | 'down'


@dataclass(frozen=True)
class SpoolFit:
    """Two-part characterisation of how rotor speed follows throttle, matching how the H20PRO ECU
    actually behaves (measured on the Nov 2025 bags): the ECU SLEW-RATE-LIMITS its own setpoint
    (~12 kRPM/s up, ~15 kRPM/s down, one 0.1 s sample at a time), and real_rpm tracks that moving
    setpoint with a short first-order lag. A pure first-order model of throttle→rpm would be wrong
    in the way that matters most (big transients are rate-limited, not exponential); so the deck
    ships BOTH: the setpoint slew limits (dominant for large throttle changes) and the tracking τ
    (dominant for small ones). The consumer builds: setpoint = rate-limited(throttle map);
    rpm' = (setpoint − rpm)/τ."""
    tau_up_s: float
    tau_down_s: float
    slew_up_rpm_s: float
    slew_down_rpm_s: float
    steps: tuple[SpoolStep, ...]
    n_up: int
    n_down: int
    n_slew_up: int
    n_slew_down: int
    method: str = ("slew: per-run p90 of 1 s-smoothed |dN/dt| while lit between idle floor and "
                   "max-continuous, median over runs, per direction — reads LOW by up to ~25% on "
                   "short ramps (rotor lags a rate-limited setpoint by tau*slew), i.e. conservative; "
                   "tracking τ: first-order exp fit of real_rpm toward set_rpm after setpoint HOLDS, "
                   "median over steps, per direction; up-τ inherits down-τ when no up-hold passes R² "
                   "(acceleration is a rate schedule, not an exponential)")


def _slew_rates(runs: list[BenchRun], *, rpm_floor: float = 30000.0, rpm_ceiling: float = 121000.0,
                smooth_s: float = 1.0, min_rate: float = 2000.0) -> tuple[list[float], list[float]]:
    """Sustained rotor acceleration / deceleration capability, per run: the 90th percentile of the
    smoothed |dN/dt| while lit and between the idle floor and the max-continuous ceiling. p90 (not
    max) rejects the flameout/relight spikes visible in the Nov 2025 bags (>50 kRPM/s glitches);
    p90 (not median) reads the ECU's schedule limit rather than the gentle-ramp average. Returns
    one value per run per direction, so the deck's median is over RUNS."""
    ups, downs = [], []
    for run in runs:
        t = run.engine.t_s
        rr = run.engine.cols["real_rpm"]
        egt = run.engine.cols["egt"]
        if t.size < 10:
            continue
        dt = float(np.median(np.diff(t)))
        w = max(3, int(round(smooth_s / dt)))
        rs = np.convolve(rr, np.ones(w) / w, mode="same")
        drdt = np.gradient(rs, t)
        lit = (egt > 300.0) & (rr > rpm_floor) & (rr < rpm_ceiling)
        acc = drdt[lit & (drdt > min_rate)]
        dec = -drdt[lit & (drdt < -min_rate)]
        if acc.size >= 10:
            ups.append(float(np.percentile(acc, 90)))
        if dec.size >= 10:
            downs.append(float(np.percentile(dec, 90)))
    return ups, downs


def _fit_first_order(t: np.ndarray, y: np.ndarray, y_target: float) -> tuple[float, float]:
    """τ and R² for y(t) → y_target as a first-order response from y[0]. Linear in log space:
    ln|y − y_target| = ln|y0 − y_target| − t/τ, weighted toward the early samples where the
    signal is large. Returns (nan, 0) if the response is degenerate."""
    d = np.abs(y - y_target)
    d0 = d[0]
    if d0 <= 0 or d.size < 4:
        return float("nan"), 0.0
    m = d > 0.03 * d0                       # ignore the settled tail (log of noise)
    if m.sum() < 4:
        return float("nan"), 0.0
    tt = t[m] - t[0]
    ly = np.log(d[m])
    A = np.column_stack([np.ones_like(tt), tt])
    coef, *_ = np.linalg.lstsq(A, ly, rcond=None)
    slope = coef[1]
    if slope >= 0:
        return float("nan"), 0.0
    tau = -1.0 / slope
    pred = A @ coef
    ss_res = float(np.sum((ly - pred) ** 2))
    ss_tot = float(np.sum((ly - ly.mean()) ** 2)) or 1e-12
    return float(tau), float(1.0 - ss_res / ss_tot)


def fit_spool(runs: list[BenchRun], *, min_gap_rpm: float = 3000.0, hold_s: float = 3.0,
              rpm_floor: float = 30000.0, min_r2: float = 0.80) -> SpoolFit:
    """Tracking τ: at every moment the setpoint comes to a HOLD (unchanged for ≥ hold_s) while
    real_rpm is still ≥ min_gap_rpm away, fit real_rpm's approach to the held setpoint. Slew
    limits: from the sustained setpoint ramps. Medians per direction; the per-step evidence is
    kept for the deck's spool_fit record."""
    steps: list[SpoolStep] = []
    for run in runs:
        t = run.engine.t_s
        sr = run.engine.cols["set_rpm"]
        rr = run.engine.cols["real_rpm"]
        egt = run.engine.cols["egt"]
        n = sr.size
        i = 1
        while i < n:
            if sr[i] != sr[i - 1]:
                i += 1
                continue
            # start of a hold at i-1; find its extent
            j = i
            while j < n and sr[j] == sr[i - 1]:
                j += 1
            hold_len = t[j - 1] - t[i - 1]
            if hold_len >= hold_s and rr[i - 1] > rpm_floor and egt[i - 1] > 300.0 \
                    and abs(rr[i - 1] - sr[i - 1]) >= min_gap_rpm:
                target = float(sr[i - 1])
                tau, r2 = _fit_first_order(t[i - 1:j], rr[i - 1:j], target)
                if np.isfinite(tau) and r2 >= min_r2 and 0.05 < tau < 30.0:
                    steps.append(SpoolStep(run=run.name, t_step_s=float(t[i - 1]),
                                           n_from=float(rr[i - 1]), n_to=target, tau_s=tau, r2=r2,
                                           direction="up" if target > rr[i - 1] else "down"))
            i = j + 1
    ups = [s.tau_s for s in steps if s.direction == "up"]
    downs = [s.tau_s for s in steps if s.direction == "down"]
    slew_up, slew_down = _slew_rates(runs, rpm_floor=rpm_floor)
    if not downs:
        raise ValueError(f"no usable tracking steps at all ({len(ups)} up, {len(downs)} down)")
    if not slew_up or not slew_down:
        raise ValueError(f"insufficient setpoint ramps: {len(slew_up)} up, {len(slew_down)} down")
    # UP tracking is structurally ill-conditioned on this ECU (measured): acceleration is a
    # constant-rate governor schedule, not an exponential, so few up-holds pass the R² gate. When
    # none do, the up τ inherits the down τ and the deck's spool_fit record says n_up = 0 — the
    # rate limit (slew) carries the real up-transient physics anyway.
    tau_up = float(np.median(ups)) if ups else float(np.median(downs))
    return SpoolFit(tau_up_s=tau_up, tau_down_s=float(np.median(downs)),
                    slew_up_rpm_s=float(np.median(slew_up)), slew_down_rpm_s=float(np.median(slew_down)),
                    steps=tuple(steps), n_up=len(ups), n_down=len(downs),
                    n_slew_up=len(slew_up), n_slew_down=len(slew_down))
