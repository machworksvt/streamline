# Icarus engine — Hybl H20PRO bench data and deck provenance

`streamline engine fit spec.json` → `engine_deck.json`. Everything below is what the deck's
per-field `source` tags point at.

## Bench sources (`bench/`)

Static ground runs of the Icarus H20PRO, ECU telemetry over CAN logged by machpilot as rosbag2,
converted to per-topic CSV by `machpilot/bag_to_csv.py`. Raw `.db3` on Git LFS; CSVs plain.

| bag | duration | content | role |
|---|---|---|---|
| `rosbag2_2025_11_16-15_25_29` | 611 s | full 0–100 % throttle staircase, up and down repeatedly, 37 → 117.8 kRPM (ECU setpoint saturates at 123 000, rotor holds ~118 k at 100 %); 2.74 L consumed | **primary**: ṁ(N) 41–117 kRPM, EGT(N), spool |
| `rosbag2_2025_10_26-13_08_39` | 479 s | 6-plateau staircase 0/10/20/30/40/50 % to 80 kRPM | ṁ(N) lower half, spool |
| `rosbag2_2025_11_16-14_49_59` | 168 s | single slow ramp to 100 % command, rotor lagging, shut down mid-descent | spool (slew) only |
| `rosbag2_2025_03_01-15_33_38` | 1 581 s | one ~60 s light to 40.7 kRPM, no throttle topic | idle-region ṁ anchor |

Recovered 2026-08-17 from `~/machpilot`, `C:\Users\natha\Downloads`, and the personal OneDrive
`Documents`; three further March/April 2025 bags exist but are starter cranks that never lit
(EGT ≤ 24 °C) and carry no engine data — not copied.

Channel facts (`h20pro_*` topics): `engine_data` real_rpm / set_rpm / egt [°C] / pump_power [%];
`fuel_ambient` fuel_flow [**mL/min**] / fuel_consumed [mL] / ambient_temperature [°C] /
engine_box_pressure [hPa]; `throttle_command` data [%] (Oct 2025+ only). Time column is
`timestap` (Mar 2025 converter typo) or `timestamp` (Oct 2025+); ns since epoch.

## Fuel-flow unit, verified three ways

1. Manual §8.6: the ECU reports **volumetric** flow computed from fuel-pump revolutions,
   explicitly *uncalibrated* ("sensitive to fuel used, fuel temperature, inlet fuel filter, fuel
   pump condition and pump to pump variation").
2. ∫fuel_flow·dt over the primary run = 2 737 mL vs the ECU's own `fuel_consumed` counter 2 740.
3. Bench 771 mL/min at 117 kRPM ≈ 617 g/min at 0.80 kg/L vs the manual's "~540 g/min @ 200 N" —
   same ballpark; the ~14 % gap is the uncalibrated-multiplier caveat above. The datasheet point
   is included in the fit and pulls the top of the curve toward spec.

## Datasheet (H20PRO Engine USER MANUAL rev 10 EN, §2.4, 15 °C / 1013 hPa)

Max physical rotor speed 123 000 RPM (1 min); max continuous 118 000; min idle 37 000; thrust
200 ± 5 N @ 123 kRPM; EGT ~680 °C @ 123 k; EGT limiter 732 °C; fuel ~540 g/min @ 200 N; dry
mass 1 650 g; Ø111 × 280 mm; Jet A-1 / kerosene + 4–6 % turbine oil.

## What the deck is and is not

| field | source | note |
|---|---|---|
| `static.fuel_flow_kg_s` | **fitted** | degree-2 polynomial through 13 steady bench windows + datasheet point, RMS 41 mL/min |
| `static.egt_K` | **measured** | steady windows, linear interp |
| `static.thrust_N` | **estimated** | **no load cell exists**: `T = 200·(N/123000)^2`, exponent declared in `spec.json`. Replace `thrust_model.kind` with `measured` the day a load-cell run exists — same schema. |
| `limits.*` | datasheet | |
| `dynamics.slew_*` | **fitted** | ~12 kRPM/s up and down: the ECU's acceleration schedule (p90 of smoothed dN/dt, reads ≤ 25 % low on short ramps — conservative) |
| `dynamics.spool_*_time_constant_s` | **fitted** | tracking τ ≈ 1.2 s from the clean setpoint holds (down-holds; up-transients are rate-limited, not exponential — τ_up inherits τ_down, `n_steps_up = 0` recorded) |
| `fuel.capacity_kg` | **placeholder 4.0** | pending the aircraft tankage number |
| `thrust_line` | geometry | H20PRO stack bbox centre in `icarus-B.vsp3`, FRD from the datum |

Consumer structure the constants were fitted for (icarus-dynamics builds the ODE, not this repo):
`setpoint_cmd = throttle→rpm map; setpoint_lim' = clamp(…, −slew_down, +slew_up);
rpm' = (setpoint_lim − rpm)/τ(direction); T = deck.thrust(rpm); ṁ = deck.fuel_flow(rpm)`.
Ram/altitude thrust lapse is NOT in the deck (static bench only) — the consumer applies its own
lapse model and says so.
