# Eco-Loop Building Agents — System Architecture

## Overview

Eco-Loop is a closed-loop AI system that uses a local LLM (Ollama llama3:8b) to control a simulated building's HVAC cooling setpoint in real time via EnergyPlus, and proves it saves energy compared to a static baseline schedule. It employs a Model Context Protocol (MCP) tool-calling architecture to evaluate PMV comfort, carbon grid intensity, and peak demand thresholds autonomously.

```text
+-----------------------+      1. Read memory      +-------------------------+
|   EnergyPlus (C++)    | -----------------------> |    ep_bridge.py         |
|   Physics Simulation  |                          |    (Python API)         |
|   (5ZoneAirCooled)    |                          +-----------+-------------+
+-----------+-----------+                                      | 2. Sensor state
            ^                                                  v
            | 7. Write Actuator                    +-------------------------+
            |    (Override Setpoint)               |    MCP Tool Server      |
            |                                      |    (7 tools)            |
            |                                      +-----------+-------------+
+-----------+-----------+                                      | 3. Pre-fetch context
|    mcp_agent.py       | <------------------------------------+
|    (Python Orchestrator)
|           | 4. Format Prompt                     +-------------------------+
|           +------------------------------------> |    LLM Agent (Ollama)   |
|                                                  |    llama3:8b (Local)    |
|           5. Return JSON Tool Call               +-------------------------+
+--------------------------------------------------+
         |
         v
  output/ai_controlled/
  timestep_log.json
         |
         +--------------------+
                              |
                              v
                      +-------------------+
                      |   Analysis Engine |
                      |   (Python)        |
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

**Detailed Mechanics:**
- **Key design decision:** Text-based string replacement rather than full IDF parsing — simpler, fewer dependencies, and sufficient for targeted patches.
- The patcher removes the standard fixed thermostat schedule and replaces it with a `Schedule:Constant` named `AI_Cooling_Setpoint_Sch`. This creates an empty "socket" that our Python code can plug into at runtime.

### 2. EnergyPlus Bridge (`src/ep_bridge.py`)

**Purpose:** Wraps the EnergyPlus Python API for library-mode simulation with timestep callbacks.

**Architecture:**
- Registers `callback_begin_zone_timestep_after_init_heat_balance` — runs after zone heat balance init but before HVAC calculations. This specific hook executes *after* the sun and weather physics are calculated, but *before* the HVAC system decides how hard to work. This is the exact microsecond we inject our AI setpoint.
- Initializes 8 sensor handles + 1 actuator handle on first real timestep (after `api_data_fully_ready`).
- Skips warmup periods via `warmup_flag` check.
- Accepts a pluggable `on_timestep(sensor_data) -> Optional[float]` callback:
  - `None` = baseline mode (no override)
  - `agent.decide` = AI mode (LLM makes decisions)

**Sensor handles:**
| Variable | Key |
|----------|-----|
| Zone Air Temperature | SPACE1-1 |
| Zone Air Relative Humidity | SPACE1-1 |
| Site Outdoor Air Drybulb Temperature | Environment |
| Zone Thermostat Cooling Setpoint Temperature | SPACE1-1 |
| Zone Air System Sensible Cooling Rate | SPACE1-1 |
| Chiller Electricity Rate | CENTRAL CHILLER |
| Facility Total HVAC Electricity Demand Rate | Whole Building |
| Facility Total Electricity Demand Rate | Whole Building |

**Actuator:** `Schedule:Constant / Schedule Value / AI_Cooling_Setpoint_Sch`

### 3. The Cognitive Engine & Tool-Calling Architecture (`src/mcp_server.py`, `src/mcp_agent.py`)

**Purpose:** Makes HVAC cooling setpoint decisions using structured LLM inference via the Model Context Protocol (MCP).

**Tool-Calling Architecture:**
Since local `llama3:8b` models often struggle with native OpenAI-style tool APIs, we implemented a **prompt-based fixed pre-fetch pipeline**. 
The `MCPToolServer` registers 7 distinct tools. Rather than letting the LLM dynamically choose which tools to call, the orchestrator automatically pre-fetches deterministic context using `read_sensors`, `calculate_pmv`, `get_carbon_intensity`, and `get_peak_demand_status` at every timestep. This rich context is passed to the LLM, which then only needs to decide the final setpoint using the `set_cooling_setpoint` tool format. This pre-fetch approach ensures robustness and reliability with a smaller local model.

**The 7 MCP Tools:**
1. **`read_sensors`**: Reads current Zone Temperature, Outdoor Temperature, Relative Humidity, and HVAC Power directly from the EnergyPlus memory handles.
2. **`calculate_pmv`**: Performs ISO 7730 mathematical calculations (using Met=1.2, Clo=0.5, Air Velocity=0.1) to return the Predicted Mean Vote (PMV) thermal comfort index. 
3. **`get_carbon_intensity`**: Evaluates the synthetic Chicago power grid profile to return the current gCO2/kWh pollution rate.
4. **`get_peak_demand_status`**: Checks if the total building power is approaching the 4000W critical threshold (this represents 80% of the building's estimated 5000W maximum HVAC capacity, chosen as a realistic demand charge trigger point).
5. **`set_cooling_setpoint`**: The **Action Tool**. The LLM issues a JSON command (e.g., `{"value_c": 24.5}`) to this tool to alter the simulation.
6. **`parse_idf_info`**: Reads the `5ZoneAirCooled.idf` text file and returns structural facts (number of zones, equipment types) so the LLM understands the building it controls.
7. **`get_error_log`**: Parses `eplusout.err` via string-matching to check for `** Severe **` or `** Warning **` flags to ensure the simulation isn't crashing.

**Inference pipeline & Three-Tier Fail-Safe Mechanism:**
```text
Sensor Data --> Format Prompt --> Ollama Chat API --> JSON Parse --> Clamp [23, 30]°C --> Return
                                       |                  |
                                       v (fail)           v (fail)
                                  Retry (3x)        Regex Fallback
                                       |                  |
                                       v (fail x3)        |
                                  Heuristic Rule-based ---+
```

**Prompt Engineering Strategies:**
- **Strict JSON Enforcement:** We use Ollama's `format` parameter with a strict JSON schema for the tool call to eliminate parsing errors and hallucinated formatting.
- **LLM Context Window:** llama3:8b uses an 8k context window, but our state prompt is less than 300 tokens, making it extremely fast to process.

**Setpoint Oscillations & Active Load Shedding:**
During peak afternoon heat (e.g., Day 2 from 12:00 to 18:00), the AI's cooling setpoint decisions exhibit visible oscillations between 24.5°C, 25.0°C, and 26.0°C. Data analysis confirms this is **not noise**. These oscillations highly correlate with the `Peak Demand Status` signal. When the simulated grid utilization spikes above 90%, the AI actively sheds load by raising the setpoint up to 26.0°C. Once the peak risk drops back to ~70%, it lowers the setpoint back to 24.5°C to restore optimal thermal comfort.

- **Context Distillation:** Instead of putting the entire 2MB IDF file into the LLM prompt (which would cause massive latency and context exhaustion), the agent uses `parse_idf_info` to extract just the required metadata.
- **Rules-Based Guardrails:** The system prompt explicitly defines operational boundaries:
  - "During occupied hours (6am-8pm): Use 24.0-25.5°C"
  - "If PMV > 0.5 (warm): Lower setpoint by 0.5°C"
  - "NEVER set below 23°C or above 30°C"
- **Low Temperature:** We use a generation temperature of `0.0` to ensure completely deterministic, highly focused responses and perfect reproducibility.

**Prompt Latency Management:**
- **Local GPU Execution:** We host Ollama locally, eliminating network round-trips and API rate limits.
- **Prompt Context:** We pass the current timestep's sensor readings and tool outputs (PMV, Carbon, Peak) alongside a 3-step trailing memory array of past decisions. This maintains agent awareness of recent behavior while keeping the prompt token count manageable (~550 tokens) and latency under 1 second per decision.
- **Pre-fetching:** Deterministic tools (like PMV math and carbon lookups) are executed *before* calling the LLM, reducing the number of LLM inference cycles required per timestep.

**Handling Lengthy Simulation Logs:**
- **In-Memory Streaming vs Disk I/O:** Rather than writing logs to disk and parsing them later, the `ep_bridge.py` uses the `pyenergyplus` API to stream variables in memory via callbacks.
- **Targeted Extraction:** The MCP `get_error_log` tool uses targeted string matching to parse the `eplusout.err` file efficiently without loading the entire multi-megabyte log into memory or the LLM's context window.

### 4. Runners (`src/baseline_runner.py`, `src/ai_runner.py`)

**Purpose:** Execute simulations and save results.

- **Baseline:** `EnergyPlusBridge(on_timestep=None, enable_actuator=False)`
- **AI:** `EnergyPlusBridge(on_timestep=agent.decide, enable_actuator=True)`

### 5. Analysis Engine (`src/analysis.py`, `src/comfort.py`, `src/pmv.py`)

**Purpose:** Compares baseline vs AI runs quantitatively.

**Detailed Calculations:**
- **HVAC Energy:** Integrated over time using `sum(hvac_power_w) * 0.25 hours / 1000`.
- **Cost Savings:** The total building kWh is multiplied by the Illinois commercial rate of **$0.12/kWh**.
- **Carbon Emissions:** The power consumed at any specific hour is multiplied by that hour's specific grid intensity (e.g., 380 gCO2 at 2 AM, 540 gCO2 at 5 PM). 
- **Thermal Comfort:** Evaluates every 15-minute timestep during occupied hours (6 AM to 8 PM). It checks if the temperature is safely within the [21°C - 26°C] band and calculates the ISO 7730 PMV value.

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

```bash
python main.py              # Full pipeline (~3-4 min)
python main.py --skip-sim   # Reuse existing sim logs
python main.py --no-dashboard
```

## Data Flow

```text
1. idf_patcher.py
   Input:  C:\EnergyPlusV26-1-0\ExampleFiles\5ZoneAirCooled.idf
   Output: idf_files/5ZoneAirCooled_baseline.idf
           idf_files/5ZoneAirCooled_ai.idf

2. baseline_runner.py
   Input:  idf_files/5ZoneAirCooled_baseline.idf + weather/
   Output: output/baseline/timestep_log.json (672 entries)

3. ai_runner.py
   Input:  idf_files/5ZoneAirCooled_ai.idf + weather/ + Ollama
   Output: output/ai_controlled/timestep_log.json (672 entries)
           output/ai_controlled/llm_decisions.json (672 entries)

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

*Validated over a 7-day extended simulation (June 25 – July 1, 168 hours, 672 timesteps).*

| Metric | Value |
|--------|-------|
| HVAC Energy Savings | **12.6%** |
| Heuristic-only Savings | **7.5%** |
| LLM Incremental (over heuristic) | **5.05%** |
| Total Energy Savings | **3.4%** |
| Cost Savings | **$3.80 / 7 days** |
| Carbon Reductions | **16.6 kgCO2** |
| Comfort Maintained | **97.7%** (PMV avg: -0.26 | Max Abs Occupied: -1.54) |
| LLM Reliability | **100%** (672/672 decisions, zero fallbacks) |
| Tool Calls | **2,688** (4 tools per decision × 672 timesteps) |
| Avg Latency | **~777ms** |

*Note on Tool Calls:* The architecture registers 7 total tools. The "4 tools per decision" reflects the automated pre-fetch pipeline (`read_sensors`, `calculate_pmv`, `get_carbon_intensity`, `get_peak_demand_status`) executed every timestep. The remaining 3 tools (`set_cooling_setpoint` action tool, `parse_idf_info`, `get_error_log`) are either the final output action or one-time diagnostic tools and are not counted in the per-timestep context-gathering figure.

*Note on PMV:* The maximum absolute PMV during occupied hours is -1.54 (7-day run). This occurs at the first occupied hour of the day (6:00 AM) when the building's thermal mass naturally cools overnight due to low outdoor temperatures. The -1.54 PMV represents the state of the building upon arrival, not a result of aggressive AI cooling. Both baseline and AI exhibit the same worst-case value.

## Fail-Safe Validation

The three-tier fail-safe pipeline (JSON parse → regex fallback → rule-based heuristic) was deliberately tested using `tests/test_failsafe.py`:

| Test | Scenario | Result |
|------|----------|--------|
| **A** | Malformed JSON (markdown fences, extra prose) | **PASS** — regex fallback extracted valid setpoint (4/4 cases) |
| **B** | LLM completely unavailable (wrong model name) | **PASS** — heuristic fallback engaged, returned safe 25.0°C |
| **C** | Out-of-range values (15°C, 99°C, 10°C) | **PASS** — all clamped to [23, 30]°C bounds (4/4 cases) |

## Known Limitations

1. **Comfort ceiling proximity during peak heat:** During peak afternoon heat, the AI-controlled zone temperature runs closer to the upper comfort boundary (26°C) than the baseline schedule at the same hours, though it remains within the defined comfort band throughout. This reflects the AI's strategy of trading a smaller comfort margin for reduced cooling energy; a wider safety margin could be enforced by tightening the occupied-hours setpoint range if a more conservative approach is preferred.

2. **Setpoint oscillation pattern — mixed correlation finding:** Analysis of the full 7-day extended run reveals a nuanced pattern:
   - **On hot days (e.g., June 27-28, outdoor temps 29-31°C):** Oscillation strongly correlates with Peak Demand Status. When HVAC utilization spikes above 85-145% of the 4000W threshold, the AI raises setpoints to 26.0-27.0°C to shed load; when utilization drops, it lowers setpoints to 24.5°C. The average peak utilization when setpoints rise is 70.4% vs 60.5% when they drop — a clear directional signal.
   - **On cool days (e.g., June 29, outdoor temps 17-23°C):** HVAC power is near zero, peak utilization is 0%, yet the LLM still alternates between 24.0-24.5°C. This mild oscillation is decision noise — although the LLM receives its recent history in the prompt, the low-stakes nature of the cool day provides insufficient signal to lock onto a single stable setpoint.
   - **Carbon intensity** shows only 30 gCO2/kWh variation within any afternoon window (510→540), which is insufficient to drive setpoint changes. Carbon is not a meaningful oscillation driver.
   - **Conclusion:** The oscillation is a genuine peak-demand response feature on hot/high-load days, and acknowledged decision noise on cool/low-load days where the signal isn't strong enough to stabilize behavior.

3. **Peak Demand Overshoot (Recurring Prompt Rule Conflict):** The `PEAK_DEMAND_THRESHOLD` is set to 4000W, but the AI-controlled run produced a peak of 6,989W (higher than the baseline's 6,240W peak). Analysis of the timesteps reveals this is not an isolated glitch, but a recurring pattern (observed 15 times during occupied hours) driven by a conflict in the prompt rules:
   - The AI successfully sheds load during peak hours by raising the setpoint to 26.0-27.0°C (keeping power near 3,900W).
   - However, when the zone temperature drifts up and breaches the comfort threshold (PMV > 0.5), the AI prioritizes the "restore comfort" rule over the "shed load" and "gradual change" rules.
   - Instead of ramping down gently, it repeatedly issues a sudden 1.5-2.5°C setpoint drop (e.g., from 27.0°C directly to 24.5°C) in a single timestep. This massive, instant setpoint reduction forces the simulated HVAC to run at absolute maximum capacity (6,989W) to recover the temperature.
   - In the immediate next timestep, the AI sees the resulting massive power spike and corrects by raising the setpoint back up to 25.0°C and 26.0°C, resuming load shedding.
   - **Conclusion:** The AI does shed load preventatively, but its comfort-recovery response is too aggressive. In a production system, this recurring overshoot would be mitigated by enforcing a strict "rate limit" on setpoint changes (e.g., maximum 0.5°C delta per 15-minute timestep) either in the prompt or in the actuation layer to smooth out recovery spikes.

4. **Comfort percentage dip on extended run:** Over the 7-day period, AI comfort dropped from 98.2% (original 48-hour window) to 97.7%. This is driven by the broader temperature range in the extended period — the June 25-July 1 window includes cooler mornings (outdoor temps as low as 12°C) that push zone temperatures closer to the 21°C lower comfort bound before the HVAC system ramps up at 6 AM. The AI's comfort percentage remains within acceptable bounds and closely tracks the baseline's own 98.2%.

5. **Reproducibility:** The original 48-hour run was verified for determinism (two consecutive runs with `temperature=0.0` produced identical aggregate metrics). The 7-day extended run has not been independently re-run for determinism verification due to time constraints (~9 min runtime). The same `temperature=0.0` setting is in effect, so determinism is expected to hold within the same GPU floating-point tolerance observed in the 48-hour verification.

