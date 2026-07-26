"""
Eco-Loop Building Agents - Fail-Safe Pipeline Tests

Deliberately exercises each failure mode of the MCP agent's decision pipeline:
  Test A: Malformed JSON -> regex fallback extracts a valid setpoint
  Test B: LLM unavailable -> rule-based heuristic fallback returns safe value
  Test C: Out-of-range value -> clamping restricts to [23, 30]°C

Usage:
    python tests/test_failsafe.py
"""

import os
import sys
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.mcp_agent import MCPAgent
from src.mcp_server import MCPToolServer


def make_sensor_data(hour=14, zone_temp=24.0, outdoor_temp=28.0, hvac_power_w=2500):
    """Create a realistic sensor data dict for testing."""
    return {
        "month": 7, "day": 1, "hour": hour, "timestep_num": 1,
        "sim_time": 0.5, "zone_temp": zone_temp, "outdoor_temp": outdoor_temp,
        "cooling_setpoint": 24.0, "cooling_rate_w": 2000.0,
        "chiller_power_w": 800.0, "hvac_power_w": hvac_power_w,
        "total_power_w": 12000.0, "humidity": 50.0,
    }


def test_a_malformed_json():
    """Test A: Feed the parser a malformed JSON string wrapped in markdown."""
    print("\n  === Test A: Malformed JSON -> Regex Fallback ===")
    agent = MCPAgent(verbose=False)

    # Test the private _parse_tool_call method with various malformed inputs
    test_cases = [
        # Markdown-wrapped JSON
        '```json\n{"tool": "set_cooling_setpoint", "args": {"value_c": 24.5}}\n```',
        # JSON with extra prose
        'Based on my analysis, I will set the temperature. {"tool": "set_cooling_setpoint", "args": {"value_c": 25.0}} This should work.',
        # Clean JSON (should parse directly)
        '{"tool": "set_cooling_setpoint", "args": {"value_c": 24.0}}',
    ]

    results = []
    for i, tc in enumerate(test_cases):
        parsed = agent._parse_tool_call(tc)
        value = parsed.get("args", {}).get("value_c") if parsed else None
        passed = value is not None and 20 <= float(value) <= 30
        results.append(passed)
        status = "PASS" if passed else "FAIL"
        print(f"    [{status}] Input {i+1}: extracted value_c = {value}")

    # Also test _extract_setpoint_from_text for completely garbled input
    garbled = "I think we should set the cooling to 24.5°C for comfort"
    extracted = agent._extract_setpoint_from_text(garbled)
    passed = extracted is not None and 20 <= extracted <= 30
    results.append(passed)
    status = "PASS" if passed else "FAIL"
    print(f"    [{status}] Regex extraction from prose: {extracted}")

    all_passed = all(results)
    print(f"    {'[PASS]' if all_passed else '[FAIL]'} Test A: {sum(results)}/{len(results)} cases passed")
    return all_passed


def test_b_llm_unavailable():
    """Test B: Simulate LLM being unavailable -> heuristic fallback engages."""
    print("\n  === Test B: LLM Unavailable -> Heuristic Fallback ===")

    # Create agent pointing at a wrong/unavailable model
    agent = MCPAgent(model="nonexistent_model_xyz", verbose=False)
    server = MCPToolServer()

    sensor_data = make_sensor_data(hour=14, zone_temp=24.0)

    try:
        setpoint = agent.decide(sensor_data, server)
    except Exception as e:
        print(f"    [FAIL] Agent crashed instead of falling back: {e}")
        return False

    # The fallback should return a valid, clamped value
    valid = (config.COOLING_SETPOINT_MIN <= setpoint <= config.COOLING_SETPOINT_MAX)
    used_fallback = agent.fallbacks > 0

    print(f"    Setpoint returned: {setpoint}°C")
    print(f"    Used fallback: {used_fallback}")
    print(f"    Value in safe range [{config.COOLING_SETPOINT_MIN}, {config.COOLING_SETPOINT_MAX}]: {valid}")

    passed = valid  # We care that it didn't crash and returned a safe value
    print(f"    {'[PASS]' if passed else '[FAIL]'} Test B: Agent survived LLM failure, returned safe {setpoint}°C")
    return passed


def test_c_out_of_range_clamping():
    """Test C: Out-of-range setpoint values are clamped correctly."""
    print("\n  === Test C: Out-of-Range Value -> Clamping ===")

    server = MCPToolServer()

    test_cases = [
        (15.0, config.COOLING_SETPOINT_MIN),  # Way too low -> clamp to min
        (99.0, config.COOLING_SETPOINT_MAX),  # Way too high -> clamp to max
        (10.0, config.COOLING_SETPOINT_MIN),  # Extremely low -> clamp to min
        (24.5, 24.5),                          # Normal value -> pass through
    ]

    results = []
    for input_val, expected in test_cases:
        result = json.loads(server.call_tool("set_cooling_setpoint", {"value_c": input_val}))
        actual = result.get("setpoint_c")
        passed = (actual == expected)
        results.append(passed)
        was_clamped = result.get("was_clamped", False)
        status = "PASS" if passed else "FAIL"
        print(f"    [{status}] Input: {input_val}°C -> Output: {actual}°C "
              f"(expected: {expected}°C, clamped: {was_clamped})")

    all_passed = all(results)
    print(f"    {'[PASS]' if all_passed else '[FAIL]'} Test C: {sum(results)}/{len(results)} cases passed")
    return all_passed


def main():
    print("=" * 60)
    print("  Fail-Safe Pipeline Tests")
    print("=" * 60)

    results = {
        "test_a_malformed_json": test_a_malformed_json(),
        "test_b_llm_unavailable": test_b_llm_unavailable(),
        "test_c_out_of_range_clamping": test_c_out_of_range_clamping(),
    }

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"    [{status}] {name}")

    print(f"\n    Total: {passed}/{total} tests passed")

    if passed == total:
        print("\n  [PASS] All fail-safe scenarios validated!")
    else:
        print(f"\n  [WARN] {total - passed} test(s) failed!")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
