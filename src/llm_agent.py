"""
Eco-Loop Building Agents - LLM Agent

Uses Ollama (llama3:8b) to make HVAC cooling setpoint decisions based on
current building sensor data. Returns structured JSON decisions with
validation, clamping, and fallback heuristics.

The agent is called at each EnergyPlus timestep via the ep_bridge callback.

Usage:
    python -m src.llm_agent --test   # Test with mock sensor data
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
    print("[ERROR] 'ollama' package not installed. Run: pip install ollama")
    sys.exit(1)


# ─── System Prompt ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an HVAC optimization AI controlling the cooling setpoint for zone SPACE1-1 in a commercial building. Your goal is to minimize cooling energy consumption while maintaining occupant thermal comfort.

COMFORT CONSTRAINTS:
- Zone temperature must stay within 21-26 degrees C during occupied hours (6am-8pm)
- Occupant comfort is the PRIMARY constraint - never sacrifice it for energy savings

ENERGY OPTIMIZATION RULES:
- During UNOCCUPIED hours (before 6am, after 8pm): Set setpoint to 27-28 degrees C to save maximum energy
- During OCCUPIED hours (6am-8pm): Optimize setpoint between 24-25.5 degrees C
- If zone temp is well below 24 degrees C, RAISE the setpoint to 25 degrees C to reduce unnecessary cooling
- If zone temp is approaching 26 degrees C, LOWER the setpoint to 24 degrees C to prevent comfort violations
- If outdoor temp is mild (below 20 degrees C), raise setpoint slightly since less cooling is needed
- If outdoor temp is hot (above 30 degrees C), keep setpoint steady to avoid overworking the chiller
- Prefer small adjustments (0.5-1.0 degrees C) over large jumps for system stability
- The baseline uses a fixed 23.9 degrees C during occupied hours - try to beat it by using higher setpoints when possible

ABSOLUTE LIMITS:
- NEVER set below 23 degrees C or above 28 degrees C
- The minimum of 23 degrees C is required because the heating setpoint is 22.2 degrees C and cooling must stay above it
- These are hard safety limits that cannot be exceeded

You must respond with ONLY a JSON object, no other text."""


# ─── User Prompt Template ──────────────────────────────────────────────────

USER_PROMPT_TEMPLATE = """Current sensor readings at hour {hour}:00 on day {day}:

- Zone temperature: {zone_temp} degrees C
- Outdoor temperature: {outdoor_temp} degrees C
- Current cooling setpoint: {cooling_setpoint} degrees C
- Zone cooling rate: {cooling_rate_w} W
- Chiller power: {chiller_power_w} W
- HVAC power: {hvac_power_w} W
- Total building power: {total_power_w} W

Decide the optimal cooling setpoint. Respond with JSON only:
{{"action": "set_cooling_setpoint", "zone": "SPACE1-1", "value_c": <number>}}"""


# ─── JSON Schema for Ollama ─────────────────────────────────────────────────

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "zone": {"type": "string"},
        "value_c": {"type": "number"}
    },
    "required": ["action", "zone", "value_c"]
}


class LLMAgent:
    """
    LLM-based HVAC optimization agent using Ollama.
    Accepts sensor data and returns a clamped cooling setpoint.
    """

    def __init__(self, model=None, verbose=True):
        """
        Args:
            model: Ollama model name (default: config.OLLAMA_MODEL)
            verbose: Whether to print decisions to console
        """
        self.model = model or config.OLLAMA_MODEL
        self.verbose = verbose

        # Decision log
        self._decisions = []
        self._call_count = 0
        self._fail_count = 0
        self._fallback_count = 0

        # Last good setpoint (for fallback)
        self._last_setpoint = config.BASELINE_COOLING_SETPOINT_OCCUPIED

    def decide(self, sensor_data):
        """
        Main entry point: given sensor data, return an optimal cooling setpoint.

        Args:
            sensor_data: dict with keys from ep_bridge (zone_temp, outdoor_temp, etc.)

        Returns:
            float: cooling setpoint in degrees C, clamped to [20, 28]
        """
        self._call_count += 1

        # Build user prompt
        user_msg = USER_PROMPT_TEMPLATE.format(
            hour=sensor_data.get("hour", 0),
            day=sensor_data.get("day", 1),
            zone_temp=sensor_data.get("zone_temp", 23.0),
            outdoor_temp=sensor_data.get("outdoor_temp", 20.0),
            cooling_setpoint=sensor_data.get("cooling_setpoint", 23.9),
            cooling_rate_w=sensor_data.get("cooling_rate_w", 0),
            chiller_power_w=sensor_data.get("chiller_power_w", 0),
            hvac_power_w=sensor_data.get("hvac_power_w", 0),
            total_power_w=sensor_data.get("total_power_w", 0),
        )

        # Try LLM call with retries
        for attempt in range(config.LLM_MAX_RETRIES):
            t_start = time.time()
            raw_response = None
            parsed_value = None

            try:
                response = ollama.chat(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    format=RESPONSE_SCHEMA,
                    options={"temperature": 0.3},  # Low temp for consistency
                )
                latency_ms = (time.time() - t_start) * 1000.0
                raw_response = response["message"]["content"]

                # Parse JSON
                parsed_value = self._parse_response(raw_response)
                if parsed_value is not None:
                    clamped = self._clamp(parsed_value)
                    self._last_setpoint = clamped

                    # Log decision
                    self._log_decision(
                        sensor_data, user_msg, raw_response,
                        parsed_value, clamped, latency_ms, "llm"
                    )

                    if self.verbose and self._call_count % 6 == 1:
                        print(f"    [LLM] Decided: {clamped:.1f}C "
                              f"(raw: {parsed_value:.1f}C, "
                              f"latency: {latency_ms:.0f}ms)")
                    return clamped

            except Exception as e:
                latency_ms = (time.time() - t_start) * 1000.0
                if self.verbose:
                    print(f"    [LLM] Attempt {attempt+1} failed: {e}")
                self._fail_count += 1

        # All retries failed - use heuristic fallback
        return self._heuristic_fallback(sensor_data)

    def _parse_response(self, raw):
        """Parse the LLM response to extract value_c."""
        try:
            data = json.loads(raw)
            value = data.get("value_c")
            if value is not None and isinstance(value, (int, float)):
                return float(value)
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

        # Fallback: try regex extraction
        match = re.search(r'"value_c"\s*:\s*([0-9]+\.?[0-9]*)', raw)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

        return None

    def _clamp(self, value):
        """Clamp setpoint to safety bounds."""
        return max(config.COOLING_SETPOINT_MIN,
                   min(config.COOLING_SETPOINT_MAX, value))

    def _heuristic_fallback(self, sensor_data):
        """
        Rule-based fallback when LLM is unavailable or fails.
        Simple but effective energy-saving strategy.
        Must respect deadband: cooling setpoint > heating setpoint + offset.
        """
        self._fallback_count += 1
        hour = sensor_data.get("hour", 12)
        zone_temp = sensor_data.get("zone_temp", 23.0)
        outdoor_temp = sensor_data.get("outdoor_temp", 20.0)

        # Unoccupied hours: set high to save energy
        if hour < config.OCCUPIED_START_HOUR or hour >= config.OCCUPIED_END_HOUR:
            setpoint = 28.0
        else:
            # Occupied hours: adaptive strategy
            if zone_temp < 23.0:
                # Room is cool enough, raise setpoint to save energy
                setpoint = min(25.5, self._last_setpoint + 0.5)
            elif zone_temp > 25.0:
                # Getting warm, lower setpoint
                setpoint = max(23.5, self._last_setpoint - 0.5)
            elif outdoor_temp < 20.0:
                # Mild outside, can be more relaxed
                setpoint = min(25.0, self._last_setpoint + 0.3)
            else:
                # Default: slightly above baseline to save energy
                setpoint = 24.5

        clamped = self._clamp(setpoint)
        self._last_setpoint = clamped

        self._log_decision(
            sensor_data, "", "", setpoint, clamped, 0.0, "heuristic"
        )

        if self.verbose and self._call_count % 6 == 1:
            print(f"    [FALLBACK] Heuristic setpoint: {clamped:.1f}C")

        return clamped

    def _log_decision(self, sensor_data, prompt, raw_response,
                      parsed_value, clamped_value, latency_ms, method):
        """Log a decision for post-analysis."""
        self._decisions.append({
            "call_number": self._call_count,
            "hour": sensor_data.get("hour", 0),
            "day": sensor_data.get("day", 1),
            "zone_temp": sensor_data.get("zone_temp", 0),
            "outdoor_temp": sensor_data.get("outdoor_temp", 0),
            "parsed_value": round(parsed_value, 2) if parsed_value else None,
            "clamped_value": round(clamped_value, 2),
            "latency_ms": round(latency_ms, 1),
            "method": method,
            "raw_response": raw_response[:200] if raw_response else "",
        })

    def get_decisions(self):
        """Return the decision log."""
        return self._decisions

    def save_decisions(self, filepath):
        """Save decisions to JSON file."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(self._decisions, f, indent=2)
        print(f"  Decisions saved: {filepath} ({len(self._decisions)} entries)")

    def get_stats(self):
        """Return agent statistics."""
        latencies = [d["latency_ms"] for d in self._decisions if d["latency_ms"] > 0]
        return {
            "total_calls": self._call_count,
            "llm_failures": self._fail_count,
            "heuristic_fallbacks": self._fallback_count,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
            "max_latency_ms": round(max(latencies), 1) if latencies else 0,
            "min_latency_ms": round(min(latencies), 1) if latencies else 0,
        }


# ─── Test Mode ──────────────────────────────────────────────────────────────

def run_test():
    """Test the LLM agent with mock sensor data scenarios."""
    print("=" * 60)
    print("  LLM Agent Test")
    print("=" * 60)
    print(f"  Model: {config.OLLAMA_MODEL}")
    print(f"  Setpoint bounds: [{config.COOLING_SETPOINT_MIN}, "
          f"{config.COOLING_SETPOINT_MAX}] C")
    print()

    agent = LLMAgent(verbose=True)

    # Test scenarios
    scenarios = [
        {
            "name": "Occupied, comfortable",
            "data": {"hour": 10, "day": 1, "zone_temp": 23.5,
                     "outdoor_temp": 22.0, "cooling_setpoint": 23.9,
                     "cooling_rate_w": 2500, "chiller_power_w": 1500,
                     "hvac_power_w": 3000, "total_power_w": 8000},
        },
        {
            "name": "Occupied, warm zone",
            "data": {"hour": 14, "day": 1, "zone_temp": 25.2,
                     "outdoor_temp": 32.0, "cooling_setpoint": 24.0,
                     "cooling_rate_w": 4000, "chiller_power_w": 3000,
                     "hvac_power_w": 5000, "total_power_w": 12000},
        },
        {
            "name": "Unoccupied, night",
            "data": {"hour": 22, "day": 1, "zone_temp": 21.0,
                     "outdoor_temp": 16.0, "cooling_setpoint": 29.4,
                     "cooling_rate_w": 0, "chiller_power_w": 0,
                     "hvac_power_w": 0, "total_power_w": 500},
        },
        {
            "name": "Occupied, cool zone (over-cooling)",
            "data": {"hour": 8, "day": 2, "zone_temp": 21.5,
                     "outdoor_temp": 18.0, "cooling_setpoint": 23.0,
                     "cooling_rate_w": 1000, "chiller_power_w": 800,
                     "hvac_power_w": 1500, "total_power_w": 6000},
        },
    ]

    all_passed = True
    for scenario in scenarios:
        name = scenario["name"]
        data = scenario["data"]
        print(f"\n  --- Scenario: {name} ---")
        print(f"  Input: zone={data['zone_temp']}C, outdoor={data['outdoor_temp']}C, "
              f"hour={data['hour']}")

        t_start = time.time()
        setpoint = agent.decide(data)
        latency = (time.time() - t_start) * 1000.0

        # Validate
        in_bounds = config.COOLING_SETPOINT_MIN <= setpoint <= config.COOLING_SETPOINT_MAX
        is_number = isinstance(setpoint, (int, float))

        status = "PASS" if (in_bounds and is_number) else "FAIL"
        if not (in_bounds and is_number):
            all_passed = False

        print(f"  Result: {setpoint:.1f}C | In bounds: {in_bounds} | "
              f"Latency: {latency:.0f}ms | [{status}]")

    # Print stats
    stats = agent.get_stats()
    print(f"\n  === Agent Stats ===")
    for k, v in stats.items():
        print(f"    {k}: {v}")

    if all_passed:
        print(f"\n  [PASS] All {len(scenarios)} scenarios passed!")
    else:
        print(f"\n  [FAIL] Some scenarios failed!")
        sys.exit(1)


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_test()
    else:
        print("Usage: python -m src.llm_agent --test")
        print("  Runs test scenarios with mock sensor data")
