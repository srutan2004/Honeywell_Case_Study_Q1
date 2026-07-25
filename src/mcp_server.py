"""
Eco-Loop Building Agents - MCP Tool Server

Implements an MCP (Model Context Protocol) compatible tool server that
exposes building control and analysis tools for the LLM agent.

Tools registered:
  1. read_sensors       - Get current sensor data from EnergyPlus
  2. set_cooling_setpoint - Write a cooling setpoint to the actuator
  3. calculate_pmv      - Calculate PMV/PPD thermal comfort index
  4. get_carbon_intensity - Get current grid carbon intensity (gCO2/kWh)
  5. get_peak_demand_status - Check if HVAC is near peak demand threshold
  6. parse_idf_info     - Parse and return building model information
  7. get_error_log      - Read EnergyPlus error log for runtime errors

The tools are invoked by the LLM via Ollama's function calling capability.

Usage:
    server = MCPToolServer()
    server.update_sensors(sensor_data)
    result = server.call_tool("read_sensors", {})
"""

import os
import sys
import json
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.pmv import calculate_pmv, is_pmv_comfortable


# ─── Carbon Intensity Schedule (synthetic for Chicago IL) ────────────────────
# gCO2 per kWh, varies by hour (cleaner at night, dirtier during peak)
CARBON_INTENSITY_BY_HOUR = {
    0: 380, 1: 370, 2: 360, 3: 355, 4: 360, 5: 375,
    6: 420, 7: 460, 8: 490, 9: 510, 10: 520, 11: 530,
    12: 535, 13: 530, 14: 525, 15: 520, 16: 530, 17: 540,
    18: 510, 19: 480, 20: 450, 21: 420, 22: 400, 23: 390,
}

# ─── Electricity Rate ($/kWh for Illinois commercial) ────────────────────────
ELECTRICITY_RATE = 0.12  # $/kWh


class MCPToolServer:
    """
    MCP-compatible tool server for building HVAC control.
    Manages tool registration, sensor state, and tool execution.
    """

    def __init__(self, output_dir=None):
        self._sensors = {}
        self._last_setpoint = config.BASELINE_COOLING_SETPOINT_OCCUPIED
        self._setpoint_history = []
        self._output_dir = output_dir or config.AI_OUTPUT

        # Tool registry: name -> (function, schema)
        self._tools = {}
        self._register_all_tools()

    def _register_all_tools(self):
        """Register all available MCP tools."""
        self._tools["read_sensors"] = (
            self._tool_read_sensors,
            {
                "type": "function",
                "function": {
                    "name": "read_sensors",
                    "description": "Read current building sensor data including zone temperature, outdoor temperature, HVAC power, humidity, and current setpoint. Call this first to understand the current building state.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
        )

        self._tools["set_cooling_setpoint"] = (
            self._tool_set_setpoint,
            {
                "type": "function",
                "function": {
                    "name": "set_cooling_setpoint",
                    "description": "Set the cooling setpoint temperature for zone SPACE1-1. Value must be between 23.0 and 28.0 degrees C. Lower values mean more cooling (more energy), higher values mean less cooling (less energy). The heating setpoint is 22.2C so cooling must stay above 23.0C.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "value_c": {
                                "type": "number",
                                "description": "Cooling setpoint in degrees Celsius (23.0 to 28.0)",
                            }
                        },
                        "required": ["value_c"],
                    },
                },
            },
        )

        self._tools["calculate_pmv"] = (
            self._tool_calculate_pmv,
            {
                "type": "function",
                "function": {
                    "name": "calculate_pmv",
                    "description": "Calculate the Predicted Mean Vote (PMV) thermal comfort index for the current conditions. PMV ranges from -3 (cold) to +3 (hot). Comfortable range is -0.5 to +0.5. Use this to verify comfort before setting a new setpoint.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
        )

        self._tools["get_carbon_intensity"] = (
            self._tool_get_carbon,
            {
                "type": "function",
                "function": {
                    "name": "get_carbon_intensity",
                    "description": "Get the current grid carbon intensity in gCO2/kWh. Higher values mean dirtier electricity. Consider shifting loads to low-carbon hours when possible.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
        )

        self._tools["get_peak_demand_status"] = (
            self._tool_peak_demand,
            {
                "type": "function",
                "function": {
                    "name": "get_peak_demand_status",
                    "description": "Check if HVAC power is approaching the peak demand threshold (4000W). Returns current power, threshold, and utilization percentage.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
        )

        self._tools["parse_idf_info"] = (
            self._tool_parse_idf,
            {
                "type": "function",
                "function": {
                    "name": "parse_idf_info",
                    "description": "Parse the building model IDF file and return key building information like zone names, floor area, and HVAC system type.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
        )

        self._tools["get_error_log"] = (
            self._tool_get_errors,
            {
                "type": "function",
                "function": {
                    "name": "get_error_log",
                    "description": "Read the EnergyPlus error log to check for runtime warnings or severe errors in the current simulation.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
        )

    # ─── State Management ────────────────────────────────

    def update_sensors(self, sensor_data):
        """Update the current sensor state (called by ep_bridge at each timestep)."""
        self._sensors = dict(sensor_data)

    def get_tool_schemas(self):
        """Return Ollama-compatible tool schemas for all registered tools."""
        return [schema for _, schema in self._tools.values()]

    def call_tool(self, name, arguments):
        """
        Execute a tool by name and return the result.

        Args:
            name: Tool name (e.g. 'read_sensors')
            arguments: Dict of arguments

        Returns:
            str: JSON-encoded result
        """
        if name not in self._tools:
            return json.dumps({"error": f"Unknown tool: {name}"})

        func, _ = self._tools[name]
        try:
            result = func(arguments)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ─── Tool Implementations ────────────────────────────

    def _tool_read_sensors(self, args):
        """Read current sensor data."""
        if not self._sensors:
            return {"error": "No sensor data available yet"}

        hour = self._sensors.get("hour", 0)
        is_occupied = config.OCCUPIED_START_HOUR <= hour < config.OCCUPIED_END_HOUR

        return {
            "zone_temperature_c": self._sensors.get("zone_temp", 0),
            "outdoor_temperature_c": self._sensors.get("outdoor_temp", 0),
            "current_cooling_setpoint_c": self._sensors.get("cooling_setpoint", 0),
            "relative_humidity_pct": self._sensors.get("humidity", 50.0),
            "hvac_power_w": self._sensors.get("hvac_power_w", 0),
            "total_building_power_w": self._sensors.get("total_power_w", 0),
            "chiller_power_w": self._sensors.get("chiller_power_w", 0),
            "cooling_rate_w": self._sensors.get("cooling_rate_w", 0),
            "hour": hour,
            "day": self._sensors.get("day", 1),
            "is_occupied": is_occupied,
            "comfort_band_c": [config.COMFORT_TEMP_MIN, config.COMFORT_TEMP_MAX],
        }

    def _tool_set_setpoint(self, args):
        """Set cooling setpoint (validates and clamps)."""
        value = args.get("value_c")
        if value is None:
            return {"error": "Missing required parameter: value_c"}

        value = float(value)
        clamped = max(config.COOLING_SETPOINT_MIN,
                      min(config.COOLING_SETPOINT_MAX, value))

        self._last_setpoint = clamped
        self._setpoint_history.append(clamped)

        was_clamped = abs(clamped - value) > 0.01
        return {
            "setpoint_c": clamped,
            "was_clamped": was_clamped,
            "original_value": round(value, 2) if was_clamped else None,
            "bounds": [config.COOLING_SETPOINT_MIN, config.COOLING_SETPOINT_MAX],
        }

    def _tool_calculate_pmv(self, args):
        """Calculate PMV/PPD comfort index from current sensors."""
        ta = self._sensors.get("zone_temp", 23.0)
        rh = self._sensors.get("humidity", 50.0)
        result = calculate_pmv(ta=ta, rh=rh, vel=0.1, met=1.2, clo=0.5)
        result["is_comfortable"] = is_pmv_comfortable(result["pmv"])
        result["air_temp_c"] = ta
        result["humidity_pct"] = rh
        return result

    def _tool_get_carbon(self, args):
        """Get current grid carbon intensity."""
        hour = self._sensors.get("hour", 12)
        intensity = CARBON_INTENSITY_BY_HOUR.get(hour, 450)
        avg_intensity = sum(CARBON_INTENSITY_BY_HOUR.values()) / 24

        return {
            "carbon_intensity_gco2_kwh": intensity,
            "hour": hour,
            "is_peak_carbon": intensity > avg_intensity,
            "daily_average_gco2_kwh": round(avg_intensity, 0),
            "recommendation": "Consider reducing load" if intensity > 500 else "Grid is relatively clean",
        }

    def _tool_peak_demand(self, args):
        """Check peak demand status."""
        hvac_w = self._sensors.get("hvac_power_w", 0)
        threshold = config.PEAK_DEMAND_THRESHOLD
        utilization = round(hvac_w / threshold * 100, 1) if threshold > 0 else 0

        return {
            "hvac_power_w": round(hvac_w, 1),
            "peak_threshold_w": threshold,
            "utilization_pct": utilization,
            "near_peak": utilization > 85,
            "at_peak": utilization > 95,
            "recommendation": "Raise setpoint to reduce demand" if utilization > 85 else "Within normal range",
        }

    def _tool_parse_idf(self, args):
        """Parse IDF file and return building info."""
        try:
            idf_path = config.AI_IDF
            with open(idf_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Extract key info
            zone_count = content.count("Zone,")
            has_chiller = "Chiller:Electric" in content
            has_boiler = "Boiler:" in content

            return {
                "idf_file": os.path.basename(idf_path),
                "file_size_kb": round(os.path.getsize(idf_path) / 1024, 1),
                "zone_count": zone_count,
                "zones": config.ALL_ZONES,
                "target_zone": config.TARGET_ZONE,
                "has_chiller": has_chiller,
                "has_boiler": has_boiler,
                "cooling_schedule": config.AI_SCHEDULE_NAME,
                "run_period": f"{config.RUN_PERIOD_BEGIN_MONTH}/{config.RUN_PERIOD_BEGIN_DAY} - {config.RUN_PERIOD_END_MONTH}/{config.RUN_PERIOD_END_DAY}",
            }
        except Exception as e:
            return {"error": str(e)}

    def _tool_get_errors(self, args):
        """Read EnergyPlus error log."""
        err_path = os.path.join(self._output_dir, "eplusout.err")
        if not os.path.isfile(err_path):
            return {"status": "No error log found (simulation may not have started)"}

        try:
            with open(err_path, "r") as f:
                lines = f.readlines()

            severe = [l.strip() for l in lines if "** Severe  **" in l]
            warnings = [l.strip() for l in lines if "** Warning **" in l]

            return {
                "total_lines": len(lines),
                "severe_errors": len(severe),
                "warnings": len(warnings),
                "severe_messages": severe[:5],
                "warning_messages": warnings[:3],
                "status": "OK" if len(severe) == 0 else "ERRORS FOUND",
            }
        except Exception as e:
            return {"error": str(e)}
