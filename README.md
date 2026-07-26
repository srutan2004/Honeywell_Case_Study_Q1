# Eco-Loop Building Agents

AI-driven HVAC optimization using a local LLM (Ollama llama3:8b) to control a simulated building's cooling setpoint in real time via EnergyPlus, proving energy savings vs. a static baseline schedule.

## Key Results

*Validated over 7-day extended simulation (June 25 – July 1, Chicago IL)*

| Metric | Value |
|--------|-------|
| **HVAC Energy Savings** | **12.6%** |
| Total Energy Savings | 3.4% |
| Heuristic-only Savings | 7.5% |
| LLM Incremental (over heuristic) | 5.05% |
| Comfort Maintained | 97.7% |
| PMV Average (Occupied) | -0.26 (near-neutral) |
| LLM Reliability | 672/672 decisions (100%) |
| LLM Token Usage | ~557 Prompt / 24 Completion |
| LLM Latency | 788ms avg per decision |
| Fail-Safe Tested | 3/3 scenarios validated (0 triggered in live run) |
| Recovery Spikes | 15 events (&Delta; &ge; 1.5&deg;C) |

## Architecture

```
EnergyPlus  -->  Sensor Data  -->  LLM Agent  -->  Setpoint  -->  EnergyPlus
(5-Zone)         (zone temp,       (Ollama         (23-30 C,      (actuator
                  outdoor,          llama3:8b)       clamped)       write)
                  HVAC power)
```

See [docs/architecture.md](docs/architecture.md) for full system design.

## Quick Start

### Prerequisites

- **Python 3.12+**
- **EnergyPlus V26-1-0** installed at `C:\EnergyPlusV26-1-0`
- **Ollama** running with `llama3:8b` model pulled

### Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Verify everything works
python -c "from pyenergyplus.api import EnergyPlusAPI; print('EP OK')"
python -c "import ollama; print(ollama.chat(model='llama3:8b', messages=[{'role':'user','content':'hi'}])['message']['content'][:50])"
```

### Run Full Pipeline

```bash
# Full pipeline: patch IDF -> baseline sim -> AI sim -> analysis -> dashboard
python main.py

# Skip simulations (reuse existing results)
python main.py --skip-sim

# Without dashboard
python main.py --no-dashboard
```

### Run Individual Steps

```bash
# 1. Prepare IDF files
python -m src.idf_patcher --verify

# 2. Run baseline simulation
python -m src.baseline_runner

# 3. Run AI-controlled simulation (~3 min, requires Ollama)
python -m src.ai_runner

# 4. Analyze and compare
python -m src.analysis

# 5. Launch dashboard
python run_dashboard.py
```

### View Dashboard

```bash
python run_dashboard.py          # Opens browser at localhost:8080
python run_dashboard.py --port 3000  # Custom port
```

## Project Structure

```
Honeywell_Case_Study/
  config.py                 # Central configuration
  main.py                   # End-to-end pipeline orchestrator
  run_dashboard.py          # Dashboard HTTP server
  requirements.txt          # Python dependencies
  src/
    __init__.py
    idf_patcher.py          # IDF file preparation
    ep_bridge.py            # EnergyPlus API wrapper
    mcp_server.py           # MCP Tool Server (7 tools)
    mcp_agent.py            # LLM agent with MCP tool calling
    baseline_runner.py      # Baseline simulation runner
    ai_runner.py            # AI-controlled simulation runner
    heuristic_runner.py     # Heuristic rules-based runner
    comfort.py              # Thermal comfort analysis
    pmv.py                  # ISO 7730 PMV calculation
    analysis.py             # Comparison & reporting
  tests/
    test_failsafe.py        # 3-tier fail-safe validation
  idf_files/
    5ZoneAirCooled_baseline.idf
    5ZoneAirCooled_ai.idf
  weather/
    USA_IL_Chicago-OHare...epw
  output/
    baseline/               # Baseline simulation outputs
    ai_controlled/          # AI simulation outputs
    heuristic_controlled/   # Heuristic simulation outputs
  results/
    comparison_data.json    # Structured comparison data
    summary_report.md       # Human-readable findings
  dashboard/
    index.html              # Dashboard page
    index.css               # Dark glassmorphism styles
    app.js                  # Chart.js visualization
  docs/
    architecture.md         # System architecture document
```

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Building Simulator | EnergyPlus V26-1-0 |
| Python API | pyenergyplus-lbnl |
| Local LLM | Ollama + llama3:8b |
| Dashboard | Chart.js 4.x + Vanilla CSS |
| Design | Dark Glassmorphism |
