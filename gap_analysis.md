# Requirements Gap Analysis

A line-by-line comparison of every requirement against what's implemented.

---

## Requirement 1: The Simulation Engine (EnergyPlus)

| Requirement | Status | Details |
|-------------|--------|---------|
| Utilize EnergyPlus for high-fidelity simulations | ✅ **Done** | EnergyPlus V26-1-0 with 5ZoneAirCooled.idf |
| Use functional libraries (eppy, PyEnergyPlus, EMS/BCVTB) | ✅ **Done** | Using `pyenergyplus` Python API (library mode with EMS actuators + callbacks) |
| Bridge Python with the IDF | ✅ **Done** | `ep_bridge.py` uses `EnergyPlusAPI` with runtime callbacks |

**Verdict: Fully satisfied** ✅

---

## Requirement 2: The Cognitive Engine & Protocol (OSS LLM & MCP)

| Requirement | Status | Details |
|-------------|--------|---------|
| Deploy modern Open-Source LLM (Llama 3, Mistral, Qwen) | ✅ **Done** | Ollama running llama3:8b locally |
| Running locally or via self-hosted API | ✅ **Done** | Ollama local server on GPU |
| **Implement an MCP Server** | ❌ **MISSING** | Not implemented. LLM is called directly via `ollama.chat()` Python library |
| **OR custom agentic tools** | ⚠️ **Partial** | We have the `decide()` function but it's not exposed as a formal "tool" the LLM invokes |
| LLM must use tools to **parse files** | ❌ **MISSING** | LLM doesn't parse IDF files or logs autonomously |
| LLM must use tools to **extract runtime errors** | ❌ **MISSING** | Error handling is in Python code, not LLM-driven |
| Execute tasks **without human code modification** | ⚠️ **Partial** | The loop runs autonomously, but the LLM can't modify code or configs on its own |

> [!CAUTION]
> **MCP Server is a critical gap.** The brief says *"Implement an MCP Server or custom agentic tools"*. We have neither. The LLM is called as a simple chat API, not as an agent with tools it can invoke.

**Verdict: Partially satisfied — MCP Server or agentic tools needed** ⚠️

---

## Requirement 3: Closed-Loop Execution Framework

### 3a. Feedback (EnergyPlus → AI)

| Required Metric | Status | Details |
|----------------|--------|---------|
| Zone temperatures | ✅ **Done** | `Zone Air Temperature` for SPACE1-1 |
| Energy consumption | ✅ **Done** | Total power, HVAC power, chiller power |
| **Indoor air quality** | ❌ **MISSING** | Not tracked (CO2, humidity, etc.) |
| **PMV thermal comfort indices** | ❌ **MISSING** | Not calculated. We use simple temp-band comfort [21-26°C] instead of the proper PMV/PPD model |
| Continuous/streaming metrics | ✅ **Done** | Callback fires every 15 simulated minutes (192 timesteps) |

### 3b. Reasoning

| Requirement | Status | Details |
|-------------|--------|---------|
| Evaluate against occupancy comfort | ✅ **Done** | Comfort band [21-26°C] during occupied hours |
| Evaluate against **peak demand thresholds** | ❌ **MISSING** | LLM sees power values but has no explicit peak demand target/penalty |
| Evaluate against **local carbon grid intensity** | ❌ **MISSING** | No carbon intensity signal — LLM doesn't know when the grid is "dirty" vs "clean" |

### 3c. Control Actions (AI → EnergyPlus)

| Requirement | Status | Details |
|-------------|--------|---------|
| Calculate optimal ECMs | ⚠️ **Partial** | Only cooling setpoint is controlled. Full ECMs would include lighting, ventilation, blinds, etc. |
| Update dynamic set-points | ✅ **Done** | LLM sets cooling setpoint via `Schedule:Constant` actuator |

### 3d. Forward Injection

| Requirement | Status | Details |
|-------------|--------|---------|
| Set-points feed back into active EnergyPlus instance | ✅ **Done** | `set_actuator_value()` writes into the running simulation |
| Supervisory overrides | ✅ **Done** | The AI overrides the native cooling schedule in real-time |

**Verdict: Core loop works, but missing PMV, IAQ, carbon intensity, peak demand** ⚠️

---

## Requirement 4: Hackathon Objective

| Requirement | Status | Details |
|-------------|--------|---------|
| Live, operational PoC | ✅ **Done** | Full pipeline runs end-to-end |
| Autonomous closed-loop control pipeline | ✅ **Done** | EP → LLM → setpoint → EP (no human in the loop) |
| AI ingests real-time sensor data | ✅ **Done** | 7 sensor values at each timestep |
| Continuously injects control actions | ✅ **Done** | 192 setpoint decisions over 48 hours |
| Prove **quantifiable energy savings** | ✅ **Done** | 6.34% HVAC savings with charts |
| Prove **cost savings** | ❌ **MISSING** | We show kWh reduction but not dollar/cost savings |

**Verdict: Core objective met, cost calculation missing** ⚠️

---

## Summary: What's Missing

### Critical Gaps (explicitly required)

| # | Gap | What's Needed | Effort |
|---|-----|--------------|--------|
| 1 | **MCP Server** | Wrap the LLM's tools (read sensors, set setpoint, parse errors) as MCP tools that the LLM can invoke. Or create a custom agentic tool framework. | Medium |
| 2 | **PMV Comfort Index** | Add the PMV (Predicted Mean Vote) calculation using zone temp, humidity, air velocity, clothing, metabolic rate. EnergyPlus can output `Zone Mean Air Temperature` and `Zone Mean Radiant Temperature` for this. | Small |
| 3 | **Indoor Air Quality** | Add CO2 concentration or humidity as additional sensor readings from EnergyPlus. | Small |

### Nice-to-Have Gaps (mentioned but not strictly required)

| # | Gap | What's Needed | Effort |
|---|-----|--------------|--------|
| 4 | **Carbon grid intensity** | Add a time-of-day carbon intensity signal (can be synthetic for Chicago) so the LLM can prefer shifting loads to "clean" hours. | Small |
| 5 | **Peak demand thresholds** | Give the LLM an explicit peak demand target (e.g., "don't exceed 4000W HVAC") so it can reason about demand management. | Small |
| 6 | **Cost savings** | Add $/kWh electricity rate and calculate dollar savings alongside kWh savings. | Small |

---

## What's Currently Working Well

| Feature | Status |
|---------|--------|
| EnergyPlus Python API (pyenergyplus) | ✅ Perfect — library mode, callbacks, sensors, actuators |
| Open-source LLM (llama3:8b via Ollama) | ✅ Perfect — 192/192 calls, 0 failures, 863ms avg |
| Closed-loop control | ✅ Perfect — sensor → LLM → setpoint → actuator → repeat |
| Energy savings proven | ✅ 6.34% HVAC savings with comfort maintained |
| Dashboard with charts | ✅ Dark glassmorphism, 3 interactive charts |
| Safety pipeline | ✅ JSON parse → regex fallback → heuristic → clamp [23,28]°C |

---

## Recommended Priority

1. **MCP Server** — This is the most critical gap since it's explicitly called out as a core requirement
2. **PMV Comfort Index** — Adds scientific rigor to the comfort analysis
3. **Cost Savings** — Easy win, just multiply kWh by electricity rate
4. **Carbon Intensity + Peak Demand** — Can be added to the LLM prompt as additional context

> [!IMPORTANT]
> Should I proceed with implementing these gaps? The MCP Server is the biggest item. I can implement it as a FastAPI-based MCP server that exposes tools like `read_sensors`, `set_cooling_setpoint`, `get_simulation_status`, and `parse_idf_file` — which the LLM would invoke as an agent.
