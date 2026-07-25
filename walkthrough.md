# Eco-Loop Building Agents — Walkthrough

---

## Phase 1: Project Scaffolding & Configuration ✅

**Completed:** 2026-07-25

### What Was Done

- Created 8-directory project structure
- Created [config.py](file:///d:/Honeywell_Case_Study/config.py) with all paths for EnergyPlus V26-1-0
- Created [requirements.txt](file:///d:/Honeywell_Case_Study/requirements.txt) — all 4 deps installed
- Copied Chicago weather file (1.6 MB) to `weather/`
- Created [README.md](file:///d:/Honeywell_Case_Study/README.md) and [src/\_\_init\_\_.py](file:///d:/Honeywell_Case_Study/src/__init__.py)

### Verification: 3/3 PASSED
- pyenergyplus v26.1.0 imports OK
- Ollama llama3:8b responds OK
- Config validation: 8/8 checks passed

---

## Phase 2: IDF File Preparation ✅

**Completed:** 2026-07-25

### What Was Done

#### Created [idf_patcher.py](file:///d:/Honeywell_Case_Study/src/idf_patcher.py)

A self-contained script that reads the original `5ZoneAirCooled.idf` from the EnergyPlus installation and creates two patched versions via text-based string replacement. Handles both LF and CRLF line endings.

#### Baseline IDF — [5ZoneAirCooled_baseline.idf](file:///d:/Honeywell_Case_Study/idf_files/5ZoneAirCooled_baseline.idf) (166 KB)

| Patch | Detail |
|-------|--------|
| **RunPeriod** | Changed Jan 1 - Dec 31 -> **Jul 1 - Jul 2** (2-day summer scenario, 48 timesteps) |
| **Output: Facility Total Electricity Demand Rate** | Added hourly output for total building electric demand (W) |
| **Output: Facility Total HVAC Electricity Demand Rate** | Added hourly output for HVAC-specific electric demand (W) |
| **Output: Zone Thermostat Cooling Setpoint Temperature** | Added hourly output to track cooling setpoint over time |
| **Output: Zone Thermostat Heating Setpoint Temperature** | Added hourly output for heating setpoint tracking |

> [!NOTE]
> The original IDF already includes `Zone Air Temperature`, `Site Outdoor Air Drybulb Temperature`, `Chiller Electricity Rate`, and `Cooling Coil Total Cooling Rate` at hourly frequency — no need to add those.

#### AI-Controlled IDF — [5ZoneAirCooled_ai.idf](file:///d:/Honeywell_Case_Study/idf_files/5ZoneAirCooled_ai.idf) (166.5 KB)

All baseline patches, plus:

| Patch | Detail |
|-------|--------|
| **Schedule:Constant** | Added `AI_Cooling_Setpoint_Sch` (Temperature type, initial 23.9°C) — this is the schedule the Python API will actuate at each timestep |
| **ThermostatSetpoint:SingleCooling** | Changed `CoolingSetpoint` schedule reference from `Clg-SetP-Sch` -> `AI_Cooling_Setpoint_Sch` |
| **ThermostatSetpoint:DualSetpoint** | Changed `DualSetPoint` cooling schedule reference from `Clg-SetP-Sch` -> `AI_Cooling_Setpoint_Sch` |

> [!IMPORTANT]
> **Actuator Strategy:** The Python API will override `AI_Cooling_Setpoint_Sch` via the EMS actuator path `("Schedule:Constant", "Schedule Value", "AI_Cooling_Setpoint_Sch")`. This is cleaner than directly manipulating thermostat internals — the schedule value changes, and the thermostat reads it natively.

#### Bug Fix: Output Variable Name

During testing, discovered that EnergyPlus V26 uses `Facility Total Electricity Demand Rate` (not `Facility Total Electric Demand Power`). Found the correct name by inspecting the `.rdd` file from a test run. Fixed the patcher accordingly.

### Verification Results

#### Patcher Self-Verification (15/15 PASSED)

```
Baseline IDF:
  [PASS] RunPeriod
  [PASS] SimulationControl
  [PASS] Zone (SPACE1-1)
  [PASS] ZoneControl:Thermostat
  [PASS] Output:Variable
  [PASS] Run period month = 7

AI IDF:
  [PASS] RunPeriod
  [PASS] SimulationControl
  [PASS] Zone (SPACE1-1)
  [PASS] ZoneControl:Thermostat
  [PASS] Output:Variable
  [PASS] Run period month = 7

AI-specific:
  [PASS] Schedule:Constant (AI_Cooling_Setpoint_Sch)
  [PASS] SingleCooling -> AI schedule
  [PASS] DualSetpoint -> AI schedule
```

#### EnergyPlus Simulation Test

Ran the baseline IDF through EnergyPlus V26 (library mode) to confirm it simulates correctly:

```
EnergyPlus Completed Successfully-- 2 Warning; 0 Severe Errors
Run Time: 0.34 sec
No warnings about missing output variables
```

The 2 warnings are standard EnergyPlus informational messages (not related to our patches).

### Files Created/Modified

| File | Size | Status |
|------|------|--------|
| [idf_patcher.py](file:///d:/Honeywell_Case_Study/src/idf_patcher.py) | 12 KB | Created |
| [5ZoneAirCooled_baseline.idf](file:///d:/Honeywell_Case_Study/idf_files/5ZoneAirCooled_baseline.idf) | 166 KB | Generated |
| [5ZoneAirCooled_ai.idf](file:///d:/Honeywell_Case_Study/idf_files/5ZoneAirCooled_ai.idf) | 166.5 KB | Generated |

---

### Next: Phase 3 — EnergyPlus Bridge (`ep_bridge.py`)
Build the Python API wrapper that reads sensor values and writes actuator setpoints during simulation callbacks.
