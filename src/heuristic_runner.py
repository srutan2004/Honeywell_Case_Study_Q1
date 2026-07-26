"""
Eco-Loop Building Agents - Heuristic Baseline Runner

Runs the EnergyPlus simulation with a simple heuristic rules-based controller.
Used to compare against the LLM agent to prove the LLM provides additional value
beyond a simple rule.
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.ep_bridge import EnergyPlusBridge


def heuristic_callback(sensor_data):
    """
    Simple rules-based controller.
    """
    hour = sensor_data.get("hour", 12)
    zone_temp = sensor_data.get("zone_temp", 23.0)
    is_occupied = config.OCCUPIED_START_HOUR <= hour < config.OCCUPIED_END_HOUR

    if not is_occupied:
        return 29.5

    # Base occupied setpoint
    base = 24.5

    # Temperature-based adjustment
    if zone_temp > 25.0:
        base -= 0.5
    elif zone_temp < 22.0:
        base += 0.5

    return max(config.COOLING_SETPOINT_MIN,
               min(config.COOLING_SETPOINT_MAX, base))


def run_heuristic_controlled():
    """Run the heuristic-controlled simulation."""
    print("=" * 60)
    print("  Heuristic Runner")
    print("  (Simple rules-based controller)")
    print("=" * 60)

    # Ensure AI IDF exists (we reuse it since it has the actuator)
    if not os.path.isfile(config.AI_IDF):
        print(f"  [ERROR] AI IDF not found: {config.AI_IDF}")
        print("  Run 'python -m src.idf_patcher' first.")
        sys.exit(1)

    # Create bridge in AI mode but with heuristic callback
    bridge = EnergyPlusBridge(
        idf_path=config.AI_IDF,
        epw_path=config.WEATHER_FILE,
        output_dir=config.HEURISTIC_OUTPUT,
        on_timestep=heuristic_callback,
        enable_actuator=True,
    )

    # Run simulation
    ret = bridge.run()

    if ret != 0:
        print(f"\n  [FAIL] Heuristic simulation failed (exit code {ret})")
        sys.exit(1)

    # Save timestep log
    log_path = os.path.join(config.HEURISTIC_OUTPUT, "timestep_log.json")
    bridge.save_log(log_path)

    # Print summary
    summary = bridge.get_summary()
    print(f"\n  === Heuristic Summary ===")
    for k, v in summary.items():
        print(f"    {k}: {v}")

    # Save summary
    summary_path = os.path.join(config.HEURISTIC_OUTPUT, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  Summary saved: {summary_path}")

    print(f"\n  [PASS] Heuristic run complete!")
    return bridge


if __name__ == "__main__":
    run_heuristic_controlled()
