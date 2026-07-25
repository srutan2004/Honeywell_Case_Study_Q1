# Eco-Loop Building Agents — System Architecture

## Overview

Eco-Loop is a closed-loop AI system that uses a local LLM (Ollama llama3:8b) to control a simulated building's HVAC cooling setpoint in real time via EnergyPlus. It employs a Model Context Protocol (MCP) tool-calling architecture to evaluate PMV comfort, carbon grid intensity, and peak demand thresholds autonomously.

```
+-------------------+     sensor data     +-------------------+
|   EnergyPlus      | ------------------> |   MCP Tool Server |
|   Simulation      |                     |   (7 tools)       |
|   (5-Zone Office) | <------------------ |                   |
+-------------------+      setpoint       +---------+---------+
         |                                          ^
         v                                          | (JSON tool calls)
  output/baseline/                        +---------+---------+
  timestep_log.json                       |   LLM Agent       |
         |                                |   (Ollama)        |
         |                                |   llama3:8b       |
         |                                +-------------------+
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

### 1. The Cognitive Engine & Tool-Calling Architecture (`src/mcp_server.py`, `src/mcp_agent.py`)

**Tool-Calling Architecture:**
Since local `llama3:8b` models often struggle with native OpenAI-style tool APIs, we implemented a **prompt-based agentic tool-calling architecture**.
- The `MCPToolServer` registers 7 tools (e.g., `calculate_pmv`, `get_carbon_intensity`, `get_peak_demand_status`, `parse_idf_info`, `get_error_log`).
- At each timestep, the agent pre-fetches deterministic context (PMV, carbon, peak demand) using these tools.
- The agent passes this rich context to the LLM and demands a strict JSON tool call response (e.g., `{"tool": "set_cooling_setpoint", "args": {"value_c": 24.5}}`).
- The Python orchestrator parses the JSON, executes the MCP tool on the server, and injects the result back into EnergyPlus.

### 2. Prompt Engineering Strategies

- **Strict JSON Enforcement:** We use Ollama's `format` parameter with a strict JSON schema for the tool call to eliminate parsing errors and hallucinated formatting.
- **Context Distillation:** Instead of dumping raw IDF files into the prompt, the agent uses the `parse_idf_info` tool to extract only relevant building parameters.
- **Rules-Based Guardrails:** The system prompt explicitly defines operational boundaries:
  - "During occupied hours (6am-8pm): Use 24.0-25.5°C"
  - "If PMV > 0.5 (warm): Lower setpoint by 0.5°C"
  - "NEVER set below 23°C or above 28°C"
- **Low Temperature:** We use a generation temperature of `0.3` to ensure deterministic, highly focused responses.

### 3. Prompt Latency Management

- **Local GPU Execution:** We host Ollama locally, eliminating network round-trips and API rate limits.
- **Context Truncation:** We pass only the current timestep's sensor readings rather than the entire historical log. The LLM acts as a Markov decision process (relying only on current state), drastically reducing prompt token count and keeping latency under 1 second per decision.
- **Pre-fetching:** Deterministic tools (like PMV math and carbon lookups) are executed *before* calling the LLM, reducing the number of LLM inference cycles required per timestep.

### 4. Handling Lengthy Simulation Logs

- **In-Memory Streaming vs Disk I/O:** Rather than writing logs to disk and parsing them later, the `ep_bridge.py` uses the `pyenergyplus` API to stream variables in memory via callbacks (`callback_begin_zone_timestep_after_init_heat_balance`).
- **Targeted Extraction:** The MCP `get_error_log` tool uses targeted string matching (`** Severe **` and `** Warning **`) to parse the `eplusout.err` file efficiently without loading the entire multi-megabyte log into memory or the LLM's context window.

### 5. EnergyPlus Bridge (`src/ep_bridge.py`)

**Purpose:** Wraps the EnergyPlus Python API for library-mode simulation with timestep callbacks.

**Architecture:**
- Registers `callback_begin_zone_timestep_after_init_heat_balance` — runs after zone heat balance init but before HVAC calculations (ideal for setpoint injection)
- Initializes 8 sensor handles (including Zone Humidity for PMV) + 1 actuator handle on first real timestep (after `api_data_fully_ready`)
- Skips warmup periods via `warmup_flag` check
- Accepts a pluggable `on_timestep(sensor_data) -> Optional[float]` callback

**Actuator:** `Schedule:Constant / Schedule Value / AI_Cooling_Setpoint_Sch`

### 6. Runners (`src/baseline_runner.py`, `src/ai_runner.py`)

**Purpose:** Execute simulations and save results.

- **Baseline:** `EnergyPlusBridge(on_timestep=None, enable_actuator=False)`
- **AI:** `EnergyPlusBridge(on_timestep=agent.decide, enable_actuator=True)`

### 7. Analysis Engine (`src/analysis.py`, `src/comfort.py`, `src/pmv.py`)

**Purpose:** Compares baseline vs AI runs quantitatively.

**Metrics calculated:**
- Energy: total kWh, HVAC kWh, peak power, savings %
- Comfort: ISO 7730 PMV/PPD index tracking, % occupied timesteps within [21, 26]°C
- Costs: Dollar savings calculated via hourly grid usage
- Agent: average setpoint, latency, tool calls

**Outputs:**
- `results/comparison_data.json` — structured data for dashboard (32 KB)
- `results/summary_report.md` — human-readable findings

### 8. Dashboard (`dashboard/`)

**Purpose:** Interactive visualization of results.

- **Technology:** Vanilla HTML/CSS/JS + Chart.js 4.x
- **Design:** Dark glassmorphism with green/blue accents
- **Charts:**
  1. HVAC Power over time (baseline vs AI, area chart)
  2. Zone Temperature with comfort band annotation
  3. Cooling Setpoint decisions (stepped line, LLM vs fixed schedule)

### 9. Orchestrator (`main.py`)

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
| HVAC Energy Savings | **7.53%** |
| Total Energy Savings | **1.78%** |
| Cost Savings | **$0.69 / 48hr** |
| Carbon Reductions | **3.04 kgCO2** |
| Comfort Maintained | **PMV -0.30 (Neutral)** |
| LLM Reliability | **100%** (192/192 decisions) |
| Tool Calls | **768** (4 tools per decision) |
| Avg Latency | **~728ms** |
