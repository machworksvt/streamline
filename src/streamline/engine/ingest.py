"""Read the machpilot rosbag CSV conversions of the Hybl H20PRO ECU telemetry.

Format facts (measured across the 2025-03 → 2025-11 bags):
* one CSV per topic, `h20pro_<topic>.csv`; the time column is `timestap` (Mar 2025 converter
  typo) or `timestamp` (Oct 2025+) — both accepted; nanoseconds since epoch.
* `engine_data`: real_rpm, set_rpm, egt [°C], pump_power [%], state/state_name.
* `fuel_ambient`: fuel_flow [mL/min — VOLUMETRIC, ECU-computed from pump revolutions per the
  H20PRO manual §8.6, uncalibrated: "sensitive to fuel, temperature, filter, pump condition"],
  fuel_consumed [mL], ambient_temperature [°C], engine_box_pressure [hPa].
* `throttle_command` (Oct 2025+ only): `data` = commanded throttle [%].
Everything is returned as float arrays on each topic's own timebase; alignment is `fit`'s job.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_TIME_KEYS = ("timestap", "timestamp")


class BenchIngestError(ValueError):
    pass


@dataclass(frozen=True)
class Topic:
    name: str
    t_s: np.ndarray                    # seconds from the BAG's first engine_data sample
    cols: dict                         # column name → float array


@dataclass(frozen=True)
class BenchRun:
    path: Path
    name: str
    engine: Topic
    fuel: Topic
    throttle: Topic | None
    file_sha256: dict = field(default_factory=dict)   # basename → sha256 of every CSV read

    @property
    def duration_s(self) -> float:
        return float(self.engine.t_s[-1] - self.engine.t_s[0])

    def has_throttle(self) -> bool:
        return self.throttle is not None and self.throttle.t_s.size > 0


def _read_topic(path: Path, name: str, cols: tuple[str, ...], t0_ns: int | None) -> tuple[Topic, int]:
    """Read one topic CSV. Returns (Topic, t0_ns) — t0 is the first sample's ns stamp when the
    caller passed None (the engine_data topic sets the bag's timebase)."""
    times, data = [], {c: [] for c in cols}
    with path.open(newline="") as fh:
        rd = csv.DictReader(fh)
        tk = next((k for k in _TIME_KEYS if k in (rd.fieldnames or ())), None)
        if tk is None:
            raise BenchIngestError(f"{path.name}: no time column among {_TIME_KEYS}; have {rd.fieldnames}")
        missing = [c for c in cols if c not in (rd.fieldnames or ())]
        if missing:
            raise BenchIngestError(f"{path.name}: missing columns {missing}; have {rd.fieldnames}")
        for row in rd:
            try:
                t = int(row[tk])
                vals = [float(row[c]) for c in cols]
            except (ValueError, TypeError):
                continue
            times.append(t)
            for c, v in zip(cols, vals):
                data[c].append(v)
    if not times:
        raise BenchIngestError(f"{path.name}: no parseable rows")
    t_ns = np.asarray(times, dtype=np.int64)
    if t0_ns is None:
        t0_ns = int(t_ns[0])
    t_s = (t_ns - t0_ns) / 1e9
    return Topic(name=name, t_s=t_s, cols={c: np.asarray(v, dtype=float) for c, v in data.items()}), t0_ns


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_bag(bag_dir: Path | str) -> BenchRun:
    """Load one converted rosbag directory into a BenchRun. throttle_command is optional
    (absent on the March 2025 bags)."""
    d = Path(bag_dir)
    if not d.is_dir():
        raise BenchIngestError(f"{d} is not a directory")
    shas = {}
    ep = d / "h20pro_engine_data.csv"
    fp = d / "h20pro_fuel_ambient.csv"
    tp = d / "h20pro_throttle_command.csv"
    for p in (ep, fp):
        if not p.exists():
            raise BenchIngestError(f"{d.name}: {p.name} missing")
    engine, t0 = _read_topic(ep, "engine_data", ("real_rpm", "set_rpm", "egt", "pump_power"), None)
    fuel, _ = _read_topic(fp, "fuel_ambient", ("fuel_flow", "fuel_consumed", "ambient_temperature",
                                                "engine_box_pressure"), t0)
    shas[ep.name] = sha256_file(ep)
    shas[fp.name] = sha256_file(fp)
    throttle = None
    if tp.exists():
        throttle, _ = _read_topic(tp, "throttle_command", ("data",), t0)
        shas[tp.name] = sha256_file(tp)
    return BenchRun(path=d, name=d.name, engine=engine, fuel=fuel, throttle=throttle, file_sha256=shas)


def load_bags(bag_dirs: list[Path | str]) -> list[BenchRun]:
    return [load_bag(b) for b in bag_dirs]
