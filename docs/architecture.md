# Eco-Loop Building Agents — System Architecture

## Overview

Eco-Loop is a closed-loop AI system that uses a local LLM (Ollama llama3:8b) to control a simulated building's HVAC cooling setpoint in real time via EnergyPlus, and proves it saves energy compared to a static baseline schedule.

```
+-------------------+     sensor data     +-------------------+
|   EnergyPlus      | ------------------> |   LLM Agent       |
|   Simulation      |                     |   (Ollama)        |
|   (5-Zone Office) | <------------------ |   llama3:8b       |
+-------------------+     setpoint        +-------------------+
         |                                         |
         v                                         v
  output/baseline/                          output/ai_controlled/
  timestep_log.json                         timestep_log.json
         |                                         |
         +------------+       +--------------------+
                      |       |
                      v       v
              +-------------------+
              |   Analysis        |
              |   Engine          |
              +-------------------+
                      |
                      v
              results/comparison_data.json
                      |
                      v
              +-------------------+
              |   Web Dashboard   |
              |   (Chart.js)      |
              +-------------------+
```

## Component Details

### 1. IDF Patcher (`src/idf_patcher.py`)

**Purpose:** Prepares two variants of the 5ZoneAirCooled.idf building model.

| IDF | Description |
|-----|-------------|
| `baseline` | Original cooling schedule (Clg-SetP-Sch), run period shortened to Jul 1-2, extra output variables added |
| `ai` | All baseline patches + `Schedule:Constant` actuator (`AI_Cooling_Setpoint_Sch`) + thermostat references patched to use it |

**Key design decision:** Text-based string replacement rather than full IDF parsing — simpler, fewer dependencies, and sufficient for targeted patches.

### 2. EnergyPlus Bridge (`src/ep_bridge.py`)

**Purpose:** Wraps the EnergyPlus Python API for library-mode simulation with timestep callbacks.

**Architecture:**
- Registers `callback_begin_zone_timestep_after_init_heat_balance` — runs after zone heat balance init but before HVAC calculations (ideal for setpoint injection)
- Initializes 7 sensor handles + 1 actuator handle on first real timestep (after `api_data_fully_ready`)
- Skips warmup periods via `warmup_flag` check
- Accepts a pluggable `on_timestep(sensor_data) -> Optional[float]` callback
  - `None` = baseline mode (no override)
  - `agent.decide` = AI mode (LLM makes decisions)

**Sensor handles:**
| Variable | Key |
|----------|-----|
| Zone Air Temperature | SPACE1-1 |
| Site Outdoor Air Drybulb Temperature | Environment |
| Zone Thermostat Cooling Setpoint Temperature | SPACE1-1 |
| Zone Air System Sensible Cooling Rate | SPACE1-1 |
| Chiller Electricity Rate | CENTRAL CHILLER |
| Facility Total HVAC Electricity Demand Rate | Whole Building |
| Facility Total Electricity Demand Rate | Whole Building |

**Actuator:** `Schedule:Constant / Schedule Value / AI_Cooling_Setpoint_Sch`

### 3. LLM Agent (`src/llm_agent.py`)

**Purpose:** Makes HVAC cooling setpoint decisions using structured LLM inference.

**Inference pipeline:**
```
Sensor Data --> Format Prompt --> Ollama Chat API --> JSON Parse --> Clamp [23, 28]°C --> Return
                                       |                  |
                                       v (fail)           v (fail)
                                  Retry (3x)        Regex Fallback
                                       |                  |
                                       v (fail x3)        |
                                  Heuristic Rule-based ---+
```

**Key design decisions:**
- **JSON schema enforcement** via Ollama `format=` parameter (not free-text parsing)
- **Temperature 0.3** for consistency (low randomness in setpoint decisions)
- **Clamping floor at 23°C** (not 20°C) to prevent crossing below the heating setpoint (22.2°C) + deadband, which causes EnergyPlus DualSetPoint errors
- **Heuristic fallback** ensures the system never crashes even if the LLM is down

### 4. Runners (`src/baseline_runner.py`, `src/ai_runner.py`)

**Purpose:** Execute simulations and save results.

- **Baseline:** `EnergyPlusBridge(on_timestep=None, enable_actuator=False)`
- **AI:** `EnergyPlusBridge(on_timestep=agent.decide, enable_actuator=True)`

### 5. Analysis Engine (`src/analysis.py`, `src/comfort.py`)

**Purpose:** Compares baseline vs AI runs quantitatively.

**Metrics calculated:**
- Energy: total kWh, HVAC kWh, peak power, savings %
- Comfort: % occupied timesteps within [21, 26]°C, violation counts, excursions
- Agent: average setpoint, latency, failure rate

**Outputs:**
- `results/comparison_data.json` — structured data for dashboard (32 KB)
- `results/summary_report.md` — human-readable findings

### 6. Dashboard (`dashboard/`)

**Purpose:** Interactive visualization of results.

- **Technology:** Vanilla HTML/CSS/JS + Chart.js 4.x
- **Design:** Dark glassmorphism with green/blue accents
- **Charts:**
  1. HVAC Power over time (baseline vs AI, area chart)
  2. Zone Temperature with comfort band annotation
  3. Cooling Setpoint decisions (stepped line, LLM vs fixed schedule)

### 7. Orchestrator (`main.py`)

**Purpose:** End-to-end pipeline runner.

```
python main.py              # Full pipeline (~3-4 min)
python main.py --skip-sim   # Reuse existing sim logs
python main.py --no-dashboard
```

## Data Flow

```
1. idf_patcher.py
   Input:  C:\EnergyPlusV26-1-0\ExampleFiles\5ZoneAirCooled.idf
   Output: idf_files/5ZoneAirCooled_baseline.idf
           idf_files/5ZoneAirCooled_ai.idf

2. baseline_runner.py
   Input:  idf_files/5ZoneAirCooled_baseline.idf + weather/
   Output: output/baseline/timestep_log.json (192 entries)

3. ai_runner.py
   Input:  idf_files/5ZoneAirCooled_ai.idf + weather/ + Ollama
   Output: output/ai_controlled/timestep_log.json (192 entries)
           output/ai_controlled/llm_decisions.json (192 entries)

4. analysis.py
   Input:  output/baseline/timestep_log.json
           output/ai_controlled/timestep_log.json
   Output: results/comparison_data.json
           results/summary_report.md

5. dashboard/
   Input:  results/comparison_data.json
   Output: Interactive browser visualization
```

## Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Building Simulator | EnergyPlus | V26-1-0 (API V25.2.0) |
| Python API | pyenergyplus-lbnl | (bundled with EP) |
| Local LLM | Ollama + llama3 | 8B parameters |
| Data Analysis | Python (json, os) | 3.12+ |
| Dashboard | Chart.js | 4.4.4 |
| Design | Vanilla CSS | Glassmorphism |

## Key Metrics Achieved

| Metric | Value |
|--------|-------|
| HVAC Energy Savings | **6.34%** |
| Total Energy Savings | **1.5%** |
| Comfort Maintained | 98.2% (no degradation) |
| LLM Reliability | 192/192 (100%) |
| LLM Latency | 863ms avg |
| Simulation Runtime | ~3 min (incl. LLM calls) |
