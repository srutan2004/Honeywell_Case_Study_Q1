# Eco-Loop Building Agents — Task Checklist

---

## Phase 1: Project Scaffolding & Configuration
- [x] Create directory structure (`src/`, `idf_files/`, `weather/`, `dashboard/`, `output/baseline/`, `output/ai_controlled/`, `results/`, `docs/`)
- [x] Create `requirements.txt` with all dependencies
- [x] Install dependencies (`pip install -r requirements.txt`)
- [x] Create `config.py` with all paths, model config, setpoint bounds, comfort band
- [x] Create `src/__init__.py`
- [x] Copy weather file from `C:\EnergyPlusV26-1-0\WeatherData\` to `weather/`
- [x] Create `README.md` with project overview
- [x] **Verify:** `from pyenergyplus.api import EnergyPlusAPI` imports successfully
- [x] **Verify:** `import ollama; ollama.chat(model='llama3:8b', messages=[{'role':'user','content':'hi'}])` works

---

## Phase 2: IDF File Preparation
- [x] Create `src/idf_patcher.py`
- [x] Implement: copy source IDF to `idf_files/5ZoneAirCooled_baseline.idf`
- [x] Implement: patch RunPeriod from Jan 1–Dec 31 -> Jul 1–Jul 2
- [x] Implement: add `Output:Variable` for `Facility Total Electricity Demand Rate` (hourly)
- [x] Implement: add `Output:Variable` for `Zone Thermostat Cooling Setpoint Temperature` (hourly)
- [x] Implement: copy baseline to `idf_files/5ZoneAirCooled_ai.idf`
- [x] Implement: add `Schedule:Constant` named `AI_Cooling_Setpoint_Sch` (Temperature type, initial 23.9)
- [x] Implement: update `ThermostatSetpoint:SingleCooling` -> reference `AI_Cooling_Setpoint_Sch`
- [x] Implement: update `ThermostatSetpoint:DualSetpoint` -> cooling schedule -> `AI_Cooling_Setpoint_Sch`
- [x] **Verify:** Run patcher script, both IDF files created (15 checks PASSED)
- [x] **Verify:** Baseline IDF runs in EnergyPlus without errors (0 Severe Errors, 0 missing variable warnings)

---

## Phase 3: EnergyPlus Bridge (`ep_bridge.py`)
- [ ] Create `src/ep_bridge.py` with `EnergyPlusBridge` class
- [ ] Implement `__init__` with API initialization, state creation
- [ ] Implement callback registration (`callback_begin_timestep_before_predictor`)
- [ ] Implement sensor handle initialization (check `api_data_fully_ready`)
  - [ ] `Zone Air Temperature` for `SPACE1-1`
  - [ ] `Site Outdoor Air Drybulb Temperature` for `Environment`
  - [ ] `Chiller Electricity Rate` (wildcard or specific key)
  - [ ] `Facility Total Electricity Demand Rate`
  - [ ] `Zone Thermostat Cooling Setpoint Temperature` for `SPACE1-1`
- [ ] Implement actuator handle initialization (`Schedule:Constant`, `Schedule Value`, `AI_Cooling_Setpoint_Sch`)
- [ ] Implement `get_variable_value` calls in callback to read all sensors
- [ ] Implement `set_actuator_value` call when callback returns a setpoint
- [ ] Implement current simulation hour/day extraction (`api.exchange.hour`, `api.exchange.day_of_month`)
- [ ] Implement timestep data logging (list of dicts with timestamp + all sensor values + setpoint decision)
- [ ] Implement `run()` method that calls `api.runtime.run_energyplus`
- [ ] Implement `get_log()` method to return collected timestep data
- [ ] Implement warmup period detection (skip warmup timesteps)
- [ ] **Verify:** Bridge runs with baseline IDF, sensors return non-zero values

---

## Phase 4: LLM Agent (`llm_agent.py`)
- [ ] Create `src/llm_agent.py` with `LLMAgent` class
- [ ] Implement system prompt with optimization rules and comfort constraints
- [ ] Implement user prompt template with sensor data formatting
- [ ] Implement `decide(sensor_data: dict) -> float` method
- [ ] Implement Ollama API call with JSON schema enforcement (`format=` parameter)
- [ ] Implement JSON response parsing (primary: `json.loads`)
- [ ] Implement fallback parsing (regex extraction of `value_c`)
- [ ] Implement setpoint clamping to [20, 28]°C
- [ ] Implement retry logic (up to 3 attempts on parse failure)
- [ ] Implement heuristic fallback when all retries fail
- [ ] Implement call logging (prompt, raw response, parsed value, clamped value, latency_ms)
- [ ] Implement `--test` mode with mock sensor data
- [ ] **Verify:** `python -m src.llm_agent --test` returns valid clamped setpoint values
- [ ] **Verify:** LLM response latency < 5 seconds on RTX 4060

---

## Phase 5: Baseline Runner
- [ ] Create `src/baseline_runner.py`
- [ ] Implement: create `EnergyPlusBridge` with baseline IDF and `on_timestep=None`
- [ ] Implement: run simulation and save timestep log to `output/baseline/timestep_log.json`
- [ ] Implement: print summary stats (total energy, avg zone temp)
- [ ] **Verify:** Baseline simulation completes without errors
- [ ] **Verify:** `output/baseline/timestep_log.json` contains 48 timesteps with valid data
- [ ] **Verify:** Zone temperatures are in plausible range (18-35°C)

---

## Phase 6: AI Runner (Close the Loop!)
- [ ] Create `src/ai_runner.py`
- [ ] Implement: create `LLMAgent` instance
- [ ] Implement: create `EnergyPlusBridge` with AI IDF and LLM callback
- [ ] Implement: the callback function that calls `agent.decide(sensor_data)` and returns setpoint
- [ ] Implement: run simulation and save timestep log to `output/ai_controlled/timestep_log.json`
- [ ] Implement: save LLM decision log to `output/ai_controlled/llm_decisions.json`
- [ ] Implement: print summary stats (total energy, avg zone temp, avg LLM latency)
- [ ] **Verify:** AI simulation completes without crashing
- [ ] **Verify:** LLM makes a decision at each timestep
- [ ] **Verify:** Setpoints vary across timesteps (not constant)
- [ ] **Verify:** Zone temperatures stay within reasonable bounds

---

## Phase 7: Comfort Analysis
- [ ] Create `src/comfort.py`
- [ ] Implement `analyze_comfort(timestep_log) -> dict` function
- [ ] Calculate: % of occupied hours within [21, 26]°C comfort band
- [ ] Calculate: count of comfort violations (too hot / too cold)
- [ ] Calculate: max temperature excursion outside comfort band
- [ ] Calculate: average zone temperature during occupied hours
- [ ] **Verify:** Comfort analysis runs on both baseline and AI logs

---

## Phase 8: Analysis & Comparison
- [ ] Create `src/analysis.py`
- [ ] Implement: load timestep logs from both runs
- [ ] Implement: calculate total kWh for each run (`sum(W * hours) / 1000`)
- [ ] Implement: calculate % energy savings
- [ ] Implement: call comfort analysis for both runs
- [ ] Implement: calculate peak demand (W) for both runs
- [ ] Implement: export `results/comparison_data.json`
- [ ] Implement: generate `results/summary_report.md` with tables and key findings
- [ ] **Verify:** `comparison_data.json` is valid JSON with all expected fields
- [ ] **Verify:** Energy savings % is computed correctly

---

## Phase 9: Dashboard
- [ ] Create `dashboard/index.css` — dark glassmorphism design system
- [ ] Create `dashboard/index.html` — page structure
- [ ] Create `dashboard/app.js` — chart logic
- [ ] Create `run_dashboard.py` — HTTP server wrapper
- [ ] **Verify:** Dashboard loads in browser
- [ ] **Verify:** All charts render with correct data
- [ ] **Verify:** Savings % matches analysis output

---

## Phase 10: Orchestrator & Documentation
- [ ] Create `main.py` — end-to-end pipeline
- [ ] Create `docs/architecture.md`
- [ ] Update `README.md` with final setup instructions
- [ ] **Verify:** `python main.py` runs full pipeline without errors
- [ ] **Verify:** All deliverable files exist and contain expected content

---

## Final Checklist (All Deliverables)
- [ ] Fully Functional Source Code — unified Python codebase
- [ ] Building Models — `5ZoneAirCooled_baseline.idf` + `5ZoneAirCooled_ai.idf`
- [ ] Quantitative Savings Dashboard — proves % kWh reduction with comfort analysis
- [ ] System Architecture Document — `docs/architecture.md`
- [ ] PoC Demo Video — 3-minute recording of the loop in action (manual recording)
- [ ] Presentation — slides using provided template (manual)
