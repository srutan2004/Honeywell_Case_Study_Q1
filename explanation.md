# Eco-Loop Building Agents — Explanation

A simple, step-by-step explanation of what was built, how it works, and what the results mean.

---

## What Is This Project?

This project is a **Proof of Concept (PoC)** that shows:

> *"Can an AI (local LLM) control a building's air conditioning in real-time and save energy compared to a fixed schedule — while keeping people comfortable?"*

**The answer: Yes.** We achieved **6.34% HVAC energy savings** with **zero comfort degradation**.

---

## The Core Idea (The "Loop")

Think of it like this:

```
Step 1: The building simulator runs and produces sensor readings
            (room temperature, outdoor temperature, power usage)
                              |
                              v
Step 2: Those readings are sent to an AI (local LLM running on your PC)
                              |
                              v
Step 3: The AI thinks: "The room is cool enough at 23.5°C, I can raise
            the cooling setpoint to 24.5°C to save some energy"
                              |
                              v
Step 4: That decision (24.5°C) is written BACK into the running simulation
                              |
                              v
Step 5: Repeat for every timestep (every 15 minutes of simulated time)
```

This is called a **"closed loop"** because the output of the AI feeds back into the simulation, which produces new sensor data, which the AI reads again, and so on.

---

## What Tools Are Used?

| Tool | What It Does | Where It Runs |
|------|-------------|---------------|
| **EnergyPlus** | Simulates a real building — calculates temperatures, power usage, HVAC behavior minute by minute | Installed at `C:\EnergyPlusV26-1-0` |
| **Ollama** | Runs AI language models locally on your GPU (no internet needed, no API keys) | Running as a local service on your PC |
| **llama3:8b** | The specific AI model (8 billion parameters) that makes the setpoint decisions | Loaded by Ollama into GPU memory |
| **Python** | Glues everything together — calls EnergyPlus API, calls Ollama, logs data, builds dashboard | Python 3.12 |
| **Chart.js** | JavaScript library for drawing interactive charts in the browser | Loaded from CDN in the dashboard |

---

## Step-by-Step: How Each File Works

### Step 1: Configuration — [config.py](file:///d:/Honeywell_Case_Study/config.py)

This file is the **central settings file**. Everything reads from here:

- **Where is EnergyPlus installed?** → `C:\EnergyPlusV26-1-0`
- **Which building model to use?** → `5ZoneAirCooled.idf` (a 5-room office building)
- **Which weather file?** → Chicago, Illinois (hot summers for cooling testing)
- **Which AI model?** → `llama3:8b` via Ollama
- **Safety limits:** Cooling setpoint must stay between **23°C and 28°C**
- **Comfort band:** Room temperature should be between **21°C and 26°C** during working hours (6am-8pm)
- **Simulation period:** July 1-2 (48 hours of hot summer)

---

### Step 2: Prepare Building Files — [idf_patcher.py](file:///d:/Honeywell_Case_Study/src/idf_patcher.py)

EnergyPlus uses `.idf` files to describe a building (walls, rooms, HVAC systems, schedules). We need TWO versions:

**Baseline IDF** (`5ZoneAirCooled_baseline.idf`):
- The original building with its normal fixed cooling schedule
- Cooling set to 23.9°C during work hours, 29.4°C at night
- Run period shortened from full year to just July 1-2 (for faster testing)
- Extra output variables added so we can read power and temperature data

**AI IDF** (`5ZoneAirCooled_ai.idf`):
- Same as baseline, BUT with one key change:
- A new **`Schedule:Constant`** named `AI_Cooling_Setpoint_Sch` is added
- The thermostat is re-wired to read from this new schedule instead of the original fixed one
- This schedule acts as a **"remote control"** — our Python code can change its value at runtime to override the cooling setpoint

> [!NOTE]
> The patcher works by doing text find-and-replace on the IDF file. It's simple but effective — we don't need a full IDF parser for these targeted changes.

---

### Step 3: EnergyPlus Bridge — [ep_bridge.py](file:///d:/Honeywell_Case_Study/src/ep_bridge.py)

This is the **translation layer** between EnergyPlus and our Python code.

**What it does:**
1. **Starts EnergyPlus** in "library mode" (runs inside our Python process, not as a separate program)
2. **Registers a callback function** — EnergyPlus calls our Python function at every timestep (every 15 minutes of simulated time)
3. **Reads 7 sensors** at each timestep:
   - Room temperature (SPACE1-1 zone)
   - Outdoor temperature
   - Current cooling setpoint
   - Zone cooling rate (watts)
   - Chiller power (watts)
   - HVAC total power (watts)
   - Building total power (watts)
4. **Writes 1 actuator** (in AI mode only): sets the `AI_Cooling_Setpoint_Sch` value
5. **Logs everything** to a list of dictionaries for later analysis

**The clever design:** The bridge accepts a `on_timestep` callback parameter:
- Pass `None` → **Baseline mode** (no override, the building runs on its original schedule)
- Pass `agent.decide` → **AI mode** (the LLM makes decisions and they're written into the simulation)

This means the **same bridge code** runs both simulations — the only difference is whether an AI callback is plugged in.

---

### Step 4: The AI Brain — [llm_agent.py](file:///d:/Honeywell_Case_Study/src/llm_agent.py)

This is where the intelligence lives. At each timestep, the bridge calls `agent.decide(sensor_data)`.

**How a single decision works:**

```
1. Receive sensor data: {zone_temp: 24.5, outdoor_temp: 22.0, hour: 14, ...}
                              |
2. Format into a prompt:  "Current readings at hour 14:
                           Zone temp: 24.5°C, Outdoor: 22.0°C, ..."
                              |
3. Send to Ollama:        ollama.chat(model='llama3:8b',
                                      messages=[system_prompt, user_prompt],
                                      format=JSON_SCHEMA)
                              |
4. Receive JSON response: {"action": "set_cooling_setpoint",
                            "zone": "SPACE1-1", "value_c": 24.5}
                              |
5. Parse the number:      value_c = 24.5
                              |
6. Clamp to safe range:   max(23.0, min(28.0, 24.5)) = 24.5
                              |
7. Return 24.5 to the bridge
```

**The System Prompt** tells the LLM:
- "You are an HVAC optimization AI"
- "Keep room temp between 21-26°C during work hours"
- "During occupied hours, use setpoints between 24-25.5°C" (higher than baseline's 23.9°C → less cooling energy)
- "At night, set it to 27-28°C" (save maximum energy)
- "NEVER go below 23°C or above 28°C" (hard safety limits)

**Safety pipeline (3 layers):**
1. **Primary:** Parse the JSON response normally
2. **Fallback 1:** If JSON parsing fails, use regex to extract the number
3. **Fallback 2:** If the LLM is completely down, use a simple rule-based heuristic (no AI needed)

After any method, the value is always **clamped** to [23, 28]°C so the building can never get an unsafe command.

> [!IMPORTANT]
> **Why 23°C minimum?** The building also has a heating system set to 22.2°C during work hours. If we set cooling below 22.2°C, EnergyPlus crashes with a "DualSetPointWithDeadBand" error because the cooling target would be lower than the heating target (contradiction). So we use 23°C as the floor (22.2 + 0.8 safety margin).

---

### Step 5: Run Both Simulations

**[baseline_runner.py](file:///d:/Honeywell_Case_Study/src/baseline_runner.py)** — Runs the building with its original fixed schedule:
```python
bridge = EnergyPlusBridge(idf_path=BASELINE_IDF, on_timestep=None)
bridge.run()
# Result: 192 timesteps logged, 76.61 kWh HVAC energy, ~0.4 sec runtime
```

**[ai_runner.py](file:///d:/Honeywell_Case_Study/src/ai_runner.py)** — Runs the building with the LLM making decisions:
```python
agent = LLMAgent(model='llama3:8b')
bridge = EnergyPlusBridge(idf_path=AI_IDF, on_timestep=agent.decide, enable_actuator=True)
bridge.run()
# Result: 192 timesteps, 192 LLM calls, 71.75 kWh HVAC energy, ~3 min runtime
```

Each run produces a `timestep_log.json` with 192 entries (4 per hour × 48 hours), containing every sensor reading and every AI decision.

---

### Step 6: Analyze & Compare — [comfort.py](file:///d:/Honeywell_Case_Study/src/comfort.py) + [analysis.py](file:///d:/Honeywell_Case_Study/src/analysis.py)

**Comfort analysis** checks: during work hours (6am-8pm), what percentage of timesteps had the room temperature within the comfort band [21, 26]°C?

**Energy analysis** calculates: total kWh consumed by HVAC in each run.

**Results exported to:**
- `results/comparison_data.json` (32 KB) — all data the dashboard needs
- `results/summary_report.md` — human-readable report

---

### Step 7: Dashboard — [dashboard/](file:///d:/Honeywell_Case_Study/dashboard/)

A single-page web app served locally at `http://localhost:8080/dashboard/index.html`.

**What it shows:**
1. **Hero card:** "6.3% HVAC Energy Savings" in big green text
2. **4 stat cards:** Total savings, AI setpoint, LLM latency, peak power
3. **Chart 1:** HVAC power over 48 hours (baseline red vs AI green)
4. **Chart 2:** Zone temperature with the comfort band highlighted in yellow
5. **Chart 3:** Setpoint decisions — the fixed baseline schedule vs the AI's adaptive decisions

**How it works:** The JavaScript (`app.js`) fetches `comparison_data.json` and renders 3 interactive Chart.js charts. No build tools, no npm — pure vanilla HTML/CSS/JS.

---

### Step 8: Main Orchestrator — [main.py](file:///d:/Honeywell_Case_Study/main.py)

Runs everything in order: `Patch IDF → Baseline Sim → AI Sim → Analysis → Dashboard`

```bash
python main.py              # Full pipeline (~3-4 min)
python main.py --skip-sim   # Skip sims, just re-analyze existing logs (~0.1s)
python main.py --no-dashboard  # Don't open browser
```

---

## The Results

| Metric | Baseline (Fixed Schedule) | AI-Controlled (LLM) | Difference |
|--------|--------------------------|---------------------|------------|
| **HVAC Energy** | 76.61 kWh | 71.75 kWh | **-6.34%** |
| **Total Energy** | 324.76 kWh | 319.90 kWh | **-1.5%** |
| **Comfort %** | 98.2% | 98.2% | **0%** (no degradation) |
| **Avg Zone Temp** | 22.32°C | 22.49°C | +0.17°C |
| **Max Zone Temp** | 23.9°C | 24.8°C | +0.9°C (still in comfort) |

**How did the AI save energy?** By raising the average cooling setpoint from 23.9°C (fixed) to **24.42°C** (adaptive). A higher setpoint means the air conditioner works less, which saves electricity. The room gets slightly warmer (24.8°C max vs 23.9°C) but stays well within the 21-26°C comfort band.

---

## What is NOT Implemented

> [!WARNING]
> **MCP (Model Context Protocol) Server is NOT implemented.**
>
> The current system calls Ollama directly via the Python `ollama` library:
> ```python
> response = ollama.chat(model='llama3:8b', messages=[...], format=JSON_SCHEMA)
> ```
> There is no MCP server wrapping this. If MCP is required, it would need to be added as an additional layer between the EP bridge and the Ollama API.

**Other items NOT implemented (manual tasks):**
- PoC demo video (needs manual screen recording)
- Presentation slides (needs manual creation)

---

## Project File Map

```
d:\Honeywell_Case_Study\
│
├── config.py                  ← All settings in one place
├── main.py                    ← "Run everything" script
├── run_dashboard.py           ← HTTP server for the dashboard
├── requirements.txt           ← pip dependencies (4 packages)
├── README.md                  ← Setup instructions
│
├── src\
│   ├── __init__.py
│   ├── idf_patcher.py         ← Step 2: Prepares building model files
│   ├── ep_bridge.py           ← Step 3: Talks to EnergyPlus
│   ├── llm_agent.py           ← Step 4: AI brain (Ollama calls)
│   ├── baseline_runner.py     ← Step 5a: Runs baseline simulation
│   ├── ai_runner.py           ← Step 5b: Runs AI simulation
│   ├── comfort.py             ← Step 6a: Comfort band analysis
│   └── analysis.py            ← Step 6b: Compare & export results
│
├── idf_files\
│   ├── 5ZoneAirCooled_baseline.idf   ← Building with fixed schedule
│   └── 5ZoneAirCooled_ai.idf         ← Building with AI remote control
│
├── weather\
│   └── USA_IL_Chicago-OHare...epw    ← Chicago summer weather data
│
├── output\
│   ├── baseline\
│   │   └── timestep_log.json         ← 192 sensor readings (no AI)
│   └── ai_controlled\
│       ├── timestep_log.json         ← 192 sensor readings (with AI)
│       └── llm_decisions.json        ← 192 AI decisions with latency
│
├── results\
│   ├── comparison_data.json          ← Dashboard data (32 KB)
│   └── summary_report.md            ← Human-readable report
│
├── dashboard\
│   ├── index.html                    ← Dashboard page
│   ├── index.css                     ← Dark glassmorphism styles
│   └── app.js                        ← Chart.js visualization
│
└── docs\
    └── architecture.md               ← System architecture document
```

---

## How to Run It

```bash
# Quick: just view existing results (no simulation needed)
python main.py --skip-sim

# Full: run everything from scratch (~3-4 minutes, needs Ollama running)
python main.py

# Just the dashboard
python run_dashboard.py
```
