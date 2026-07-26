"""
Eco-Loop Building Agents - MCP Agent (Prompt-Based Agentic Tool Calling)

An agent that uses prompt-based tool calling with the MCP server.
Instead of Ollama's native `tools` parameter (which llama3:8b doesn't support),
we describe tools in the system prompt and parse JSON tool calls from the LLM.

Agentic loop per timestep:
  1. LLM receives sensor summary + tool descriptions
  2. LLM outputs a JSON tool call (e.g. {"tool": "calculate_pmv", "args": {}})
  3. We execute the tool via MCP server and return the result
  4. LLM processes the result and either calls another tool or outputs final setpoint
  5. Loop continues until set_cooling_setpoint is called or max iterations reached

Usage:
    agent = MCPAgent(model='llama3:8b')
    setpoint = agent.decide(sensor_data, mcp_server)

    python -m src.mcp_agent --test
"""

import os
import sys
import json
import time
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

try:
    import ollama
except ImportError:
    print("[ERROR] 'ollama' not installed. Run: pip install ollama")
    sys.exit(1)

from src.mcp_server import MCPToolServer


# ─── System Prompt with Tool Descriptions ───────────────────────────────────

SYSTEM_PROMPT = """You are an autonomous HVAC optimization agent controlling zone SPACE1-1. You have MCP tools available.

AVAILABLE TOOLS (call by outputting JSON):
1. {"tool": "read_sensors", "args": {}} - Get zone temp, outdoor temp, power, humidity, occupancy
2. {"tool": "calculate_pmv", "args": {}} - Get PMV/PPD thermal comfort index for current conditions
3. {"tool": "get_carbon_intensity", "args": {}} - Get grid carbon intensity (gCO2/kWh)
4. {"tool": "get_peak_demand_status", "args": {}} - Check if near peak demand threshold
5. {"tool": "set_cooling_setpoint", "args": {"value_c": 24.5}} - Set cooling setpoint (23-30°C)

WORKFLOW: First analyze conditions, then set the optimal setpoint.

RULES:
- During occupied hours (6am-8pm): Use 24.0-25.5°C (baseline uses fixed 23.9°C)
- During unoccupied hours: Use 28.5-29.5°C to maximize savings (baseline uses 29.4°C)
- Review Recent History in the prompt. Avoid erratic swings by making gradual changes (0.5°C at a time).
- If PMV > 0.5 (warm): Lower setpoint by 0.5°C
- If carbon intensity > 500: Raise setpoint 0.5°C to reduce carbon
- If near peak demand (>85%): Raise setpoint to shed load
- NEVER set below 23°C or above 30°C

OUTPUT: You MUST output exactly one JSON object per response. No other text."""


# JSON schema for the structured response
TOOL_CALL_SCHEMA = {
    "type": "object",
    "properties": {
        "tool": {"type": "string"},
        "args": {"type": "object"},
    },
    "required": ["tool", "args"],
}


class MCPAgent:
    """
    Agentic LLM that uses prompt-based tool calling with MCP server.
    Executes a multi-step reasoning loop at each timestep.
    """

    def __init__(self, model=None, verbose=False):
        self.model = model or config.OLLAMA_MODEL
        self.verbose = verbose
        self.call_count = 0
        self.total_latency = 0
        self.max_latency = 0
        self.min_latency = float("inf")
        self.decision_log = []
        self.failures = 0
        self.fallbacks = 0
        self.total_tool_calls = 0
        self.memory = []  # Stores last few (zone_temp, setpoint) dicts

    def decide(self, sensor_data, mcp_server):
        """
        Make a setpoint decision using MCP tools in a prompt-based agentic loop.

        Args:
            sensor_data: dict from ep_bridge with sensor readings
            mcp_server: MCPToolServer instance

        Returns:
            float: cooling setpoint in [23, 30]°C
        """
        start = time.time()
        self.call_count += 1

        # Update MCP server state
        mcp_server.update_sensors(sensor_data)

        hour = sensor_data.get("hour", 0)
        zone_t = sensor_data.get("zone_temp", 22.0)
        out_t = sensor_data.get("outdoor_temp", 20.0)
        hvac_w = sensor_data.get("hvac_power_w", 0)
        rh = sensor_data.get("humidity", 50.0)
        is_occ = config.OCCUPIED_START_HOUR <= hour < config.OCCUPIED_END_HOUR

        # Step 1: Pre-fetch context from MCP tools (deterministic)
        pmv_data = json.loads(mcp_server.call_tool("calculate_pmv", {}))
        carbon_data = json.loads(mcp_server.call_tool("get_carbon_intensity", {}))
        peak_data = json.loads(mcp_server.call_tool("get_peak_demand_status", {}))

        # Prepare recent history
        history_str = "None (first timestep)"
        if self.memory:
            history_str = ", ".join([f"T-{len(self.memory)-i}: Temp {m['zone_temp']:.1f}°C, Setpoint {m['setpoint']:.1f}°C" for i, m in enumerate(self.memory)])

        # Step 2: Build rich context prompt
        user_msg = (
            f"Timestep data:\n"
            f"- Hour: {hour}, Occupied: {is_occ}\n"
            f"- Zone temp: {zone_t:.1f}°C, Outdoor: {out_t:.1f}°C\n"
            f"- Humidity: {rh:.0f}%, HVAC power: {hvac_w:.0f}W\n"
            f"- PMV: {pmv_data['pmv']} ({pmv_data['category']}), PPD: {pmv_data['ppd']}%\n"
            f"- Carbon intensity: {carbon_data['carbon_intensity_gco2_kwh']} gCO2/kWh"
            f" ({'HIGH' if carbon_data['is_peak_carbon'] else 'normal'})\n"
            f"- Peak demand: {peak_data['utilization_pct']}% of {peak_data['peak_threshold_w']}W"
            f" ({'NEAR PEAK' if peak_data['near_peak'] else 'OK'})\n"
            f"- Recent History: {history_str}\n\n"
            f"Based on this data, call set_cooling_setpoint with the optimal value."
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        setpoint = None
        tool_calls_made = ["calculate_pmv", "get_carbon_intensity", "get_peak_demand_status"]
        self.total_tool_calls += 3

        try:
            # Step 3: Ask LLM for the setpoint decision
            response = ollama.chat(
                model=self.model,
                messages=messages,
                format=TOOL_CALL_SCHEMA,
                options={"temperature": 0.0},
            )

            content = response.get("message", {}).get("content", "")
            parsed = self._parse_tool_call(content)

            if parsed and parsed.get("tool") == "set_cooling_setpoint":
                value = parsed.get("args", {}).get("value_c")
                if value is not None:
                    result = mcp_server.call_tool("set_cooling_setpoint", {"value_c": float(value)})
                    result_data = json.loads(result)
                    setpoint = result_data.get("setpoint_c")
                    tool_calls_made.append("set_cooling_setpoint")
                    self.total_tool_calls += 1

            elif parsed and parsed.get("tool"):
                # LLM called a different tool first - execute it then try again
                tool_name = parsed["tool"]
                tool_result = mcp_server.call_tool(tool_name, parsed.get("args", {}))
                tool_calls_made.append(tool_name)
                self.total_tool_calls += 1

                # Second round: provide tool result and ask for setpoint
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content":
                    f"Tool result: {tool_result}\n\nNow call set_cooling_setpoint with your decision."
                })

                response2 = ollama.chat(
                    model=self.model,
                    messages=messages,
                    format=TOOL_CALL_SCHEMA,
                    options={"temperature": 0.0},
                )
                content2 = response2.get("message", {}).get("content", "")
                parsed2 = self._parse_tool_call(content2)

                if parsed2 and parsed2.get("args", {}).get("value_c") is not None:
                    value = float(parsed2["args"]["value_c"])
                    result = mcp_server.call_tool("set_cooling_setpoint", {"value_c": value})
                    result_data = json.loads(result)
                    setpoint = result_data.get("setpoint_c")
                    tool_calls_made.append("set_cooling_setpoint")
                    self.total_tool_calls += 1

            # Try extracting from raw content if structured parse failed
            if setpoint is None:
                setpoint = self._extract_setpoint_from_text(content)
                if setpoint is not None:
                    result = mcp_server.call_tool("set_cooling_setpoint", {"value_c": setpoint})
                    result_data = json.loads(result)
                    setpoint = result_data.get("setpoint_c", setpoint)
                    tool_calls_made.append("set_cooling_setpoint(extracted)")
                    self.total_tool_calls += 1

        except Exception as e:
            self.failures += 1
            if self.verbose:
                print(f"    [MCP-Agent] Error: {e}")

        # Fallback if no setpoint decided
        if setpoint is None:
            setpoint = self._heuristic_fallback(sensor_data, pmv_data, carbon_data, peak_data)
            self.fallbacks += 1
            tool_calls_made.append("heuristic_fallback")

        # Final clamp
        setpoint = max(config.COOLING_SETPOINT_MIN,
                       min(config.COOLING_SETPOINT_MAX, setpoint))

        # Update memory
        self.memory.append({"zone_temp": zone_t, "setpoint": setpoint})
        if len(self.memory) > 3:
            self.memory.pop(0)

        elapsed = (time.time() - start) * 1000
        self.total_latency += elapsed
        self.max_latency = max(self.max_latency, elapsed)
        self.min_latency = min(self.min_latency, elapsed)

        # Log
        self.decision_log.append({
            "timestep": self.call_count,
            "hour": hour,
            "zone_temp": zone_t,
            "outdoor_temp": out_t,
            "humidity": rh,
            "pmv": pmv_data["pmv"],
            "ppd": pmv_data["ppd"],
            "carbon_gco2": carbon_data["carbon_intensity_gco2_kwh"],
            "peak_util_pct": peak_data["utilization_pct"],
            "setpoint": setpoint,
            "tools_called": tool_calls_made,
            "latency_ms": round(elapsed, 1),
            "used_fallback": "heuristic_fallback" in tool_calls_made,
        })

        if self.verbose:
            tools_str = " -> ".join(tool_calls_made)
            print(f"    [MCP] {tools_str} | Decided: {setpoint}C ({elapsed:.0f}ms)")

        return setpoint

    def _parse_tool_call(self, text):
        """Parse a JSON tool call from LLM output."""
        # Strip markdown fences if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first and last lines (fences)
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        try:
            data = json.loads(cleaned)
            if "tool" in data:
                return data
        except (json.JSONDecodeError, TypeError):
            pass

        # Try to find JSON in text (supports one level of nesting for args)
        match = re.search(r'\{[^{}]*"tool"[^{}]*\{[^{}]*\}[^{}]*\}', text)
        if not match:
            # Fallback: try flat JSON without nested braces
            match = re.search(r'\{[^{}]*"tool"[^{}]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None

    def _extract_setpoint_from_text(self, text):
        """Extract setpoint value from free text."""
        patterns = [
            r'"value_c"\s*:\s*([0-9]+\.?[0-9]*)',
            r'setpoint.*?([0-9]{2}\.[0-9])',
            r'([0-9]{2}\.[0-9])\s*°?C',
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                val = float(m.group(1))
                if 20 <= val <= 30:
                    return val
        return None

    def _heuristic_fallback(self, sensor_data, pmv_data, carbon_data, peak_data):
        """
        Enhanced rule-based fallback that uses MCP tool data.
        This is smarter than the basic heuristic because it considers
        PMV, carbon intensity, and peak demand.
        """
        hour = sensor_data.get("hour", 12)
        zone_temp = sensor_data.get("zone_temp", 23.0)
        is_occupied = config.OCCUPIED_START_HOUR <= hour < config.OCCUPIED_END_HOUR

        if not is_occupied:
            return 29.5

        # Start with a base setpoint
        base = 24.5

        # PMV adjustments
        pmv = pmv_data.get("pmv", 0)
        if pmv > 0.5:
            base -= 0.5  # Too warm, cool more
        elif pmv < -0.5:
            base += 0.5  # Too cool, save energy

        # Carbon intensity adjustment
        if carbon_data.get("is_peak_carbon", False):
            base += 0.5  # High carbon, reduce load

        # Peak demand adjustment
        if peak_data.get("near_peak", False):
            base += 0.5  # Near peak, shed load

        # Temperature-based adjustment
        if zone_temp > 25.0:
            base -= 0.5
        elif zone_temp < 22.0:
            base += 0.5

        return max(config.COOLING_SETPOINT_MIN,
                   min(config.COOLING_SETPOINT_MAX, base))

    def get_stats(self):
        """Return agent performance statistics."""
        return {
            "total_decisions": self.call_count,
            "llm_failures": self.failures,
            "heuristic_fallbacks": self.fallbacks,
            "llm_success_rate": round((self.call_count - self.fallbacks) / max(1, self.call_count) * 100, 1),
            "total_mcp_tool_calls": self.total_tool_calls,
            "avg_tools_per_decision": round(self.total_tool_calls / max(1, self.call_count), 1),
            "avg_latency_ms": round(self.total_latency / max(1, self.call_count), 1),
            "max_latency_ms": round(self.max_latency, 1),
            "min_latency_ms": round(self.min_latency, 1),
        }

    def save_decisions(self, path):
        """Save decision log to JSON file."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.decision_log, f, indent=2)
        print(f"  Decisions saved: {path} ({len(self.decision_log)} entries)")


# ─── Test Mode ──────────────────────────────────────────────────────────────

def test():
    """Test the MCP agent with mock sensor scenarios."""
    print("=" * 60)
    print("  MCP Agent Test (Prompt-Based Agentic Tool Calling)")
    print("=" * 60)

    agent = MCPAgent(verbose=True)
    server = MCPToolServer()

    scenarios = [
        {"name": "Morning Startup", "zone_temp": 21.5, "outdoor_temp": 18.0, "hour": 7,
         "hvac_power_w": 1500, "humidity": 45, "cooling_setpoint": 23.9,
         "total_power_w": 12000, "chiller_power_w": 800, "cooling_rate_w": 1200,
         "day": 1, "month": 7, "timestep_num": 1},
        {"name": "Hot Afternoon", "zone_temp": 24.8, "outdoor_temp": 32.0, "hour": 14,
         "hvac_power_w": 3800, "humidity": 60, "cooling_setpoint": 24.0,
         "total_power_w": 15000, "chiller_power_w": 2500, "cooling_rate_w": 3500,
         "day": 1, "month": 7, "timestep_num": 1},
        {"name": "Evening Unoccupied", "zone_temp": 23.0, "outdoor_temp": 22.0, "hour": 21,
         "hvac_power_w": 500, "humidity": 50, "cooling_setpoint": 24.5,
         "total_power_w": 10000, "chiller_power_w": 300, "cooling_rate_w": 400,
         "day": 1, "month": 7, "timestep_num": 1},
    ]

    for i, scenario in enumerate(scenarios):
        name = scenario.pop("name")
        print(f"\n  --- Scenario {i+1}: {name} ---")
        result = agent.decide(scenario, server)
        print(f"  Result: {result}°C")

    print(f"\n  Stats: {json.dumps(agent.get_stats(), indent=2)}")
    print(f"\n  [PASS] MCP Agent test complete!")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test()
