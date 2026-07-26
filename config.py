"""
Eco-Loop Building Agents — Central Configuration
All paths, model settings, setpoint bounds, and comfort parameters.
"""

import os

# ─── EnergyPlus Installation ────────────────────────────────────────────────
ENERGYPLUS_DIR = r"C:\EnergyPlusV26-1-0"
IDF_SOURCE = os.path.join(ENERGYPLUS_DIR, "ExampleFiles", "5ZoneAirCooled.idf")
WEATHER_SOURCE = os.path.join(
    ENERGYPLUS_DIR, "WeatherData",
    "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw"
)

# ─── Project Paths ──────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
IDF_DIR = os.path.join(PROJECT_ROOT, "idf_files")
WEATHER_DIR = os.path.join(PROJECT_ROOT, "weather")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")

# IDF file paths (created by idf_patcher.py)
BASELINE_IDF = os.path.join(IDF_DIR, "5ZoneAirCooled_baseline.idf")
AI_IDF = os.path.join(IDF_DIR, "5ZoneAirCooled_ai.idf")

# Weather file (copied to project)
WEATHER_FILE = os.path.join(WEATHER_DIR, "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw")

# Output directories
BASELINE_OUTPUT = os.path.join(OUTPUT_DIR, "baseline")
AI_OUTPUT = os.path.join(OUTPUT_DIR, "ai_controlled")
HEURISTIC_OUTPUT = os.path.join(OUTPUT_DIR, "heuristic_controlled")

# Results
COMPARISON_DATA = os.path.join(RESULTS_DIR, "comparison_data.json")
SUMMARY_REPORT = os.path.join(RESULTS_DIR, "summary_report.md")

# ─── Ollama / LLM ──────────────────────────────────────────────────────────
OLLAMA_MODEL = "llama3:8b"
LLM_TIMEOUT = 30          # seconds
LLM_MAX_RETRIES = 3       # retry on parse failure

# ─── Building / Zone ────────────────────────────────────────────────────────
TARGET_ZONE = "SPACE1-1"
ALL_ZONES = ["SPACE1-1", "SPACE2-1", "SPACE3-1", "SPACE4-1", "SPACE5-1"]

# ─── Setpoint Bounds ────────────────────────────────────────────────────────
COOLING_SETPOINT_MIN = 23.0   # °C — safety floor (must stay above heating setpoint + deadband)
COOLING_SETPOINT_MAX = 30.0   # °C — safety ceiling (never set higher)
BASELINE_COOLING_SETPOINT_OCCUPIED = 23.9    # °C — from Clg-SetP-Sch (weekdays 6am-8pm)
BASELINE_COOLING_SETPOINT_UNOCCUPIED = 29.4  # °C — from Clg-SetP-Sch (nights/weekends)

# Heating setpoint values (from Htg-SetP-Sch in the IDF)
HEATING_SETPOINT_OCCUPIED = 22.2     # °C — weekdays 6am-8pm
HEATING_SETPOINT_UNOCCUPIED = 16.7   # °C — nights/weekends
DEADBAND_OFFSET = 0.5                # °C — min gap between heating and cooling setpoints

# ─── Comfort Band ───────────────────────────────────────────────────────────
COMFORT_TEMP_MIN = 21.0   # °C — lower comfort bound
COMFORT_TEMP_MAX = 26.0   # °C — upper comfort bound

# Occupied hours (for comfort evaluation)
OCCUPIED_START_HOUR = 6    # 6:00 AM
OCCUPIED_END_HOUR = 20     # 8:00 PM (20:00)

# ─── Simulation Period ──────────────────────────────────────────────────────
RUN_PERIOD_BEGIN_MONTH = 6
RUN_PERIOD_BEGIN_DAY = 25
RUN_PERIOD_END_MONTH = 7
RUN_PERIOD_END_DAY = 1

# ─── Timestep Settings ──────────────────────────────────────────────────────
TIMESTEPS_PER_HOUR = 4  # 15-minute intervals (set in IDF: Timestep, 4;)

# ─── AI Cooling Schedule Name (added to AI IDF) ────────────────────────────
AI_SCHEDULE_NAME = "AI_Cooling_Setpoint_Sch"

# ─── Peak Demand & Cost ────────────────────────────────────────────────────
PEAK_DEMAND_THRESHOLD = 4000.0   # Watts — HVAC peak demand limit
ELECTRICITY_RATE = 0.12          # $/kWh (Illinois commercial average)

# ─── PMV Comfort Settings ──────────────────────────────────────────────────
PMV_COMFORTABLE_RANGE = 0.7      # PMV within [-0.7, +0.7] is comfortable
DEFAULT_AIR_VELOCITY = 0.1       # m/s (typical office)
DEFAULT_CLOTHING_CLO = 0.5       # clo (summer office attire)
DEFAULT_METABOLIC_MET = 1.2      # met (seated office work)
