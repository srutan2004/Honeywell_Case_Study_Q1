"""
Eco-Loop Building Agents - Baseline Runner

Runs the EnergyPlus simulation with the original fixed cooling schedule
(no AI override). This provides the baseline energy/comfort data that
the AI-controlled run will be compared against.

Usage:
    python -m src.baseline_runner
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.ep_bridge import EnergyPlusBridge


def run_baseline():
    """Run the baseline simulation and save results."""
    print("=" * 60)
    print("  Baseline Runner")
    print("  (Fixed cooling schedule, no AI override)")
    print("=" * 60)

    # Ensure IDF exists
    if not os.path.isfile(config.BASELINE_IDF):
        print(f"  [ERROR] Baseline IDF not found: {config.BASELINE_IDF}")
        print("  Run 'python -m src.idf_patcher' first.")
        sys.exit(1)

    # Create bridge in baseline mode (no callback, no actuator)
    bridge = EnergyPlusBridge(
        idf_path=config.BASELINE_IDF,
        epw_path=config.WEATHER_FILE,
        output_dir=config.BASELINE_OUTPUT,
        on_timestep=None,       # No override - native schedule runs
        enable_actuator=False,  # No actuator needed
    )

    # Run simulation
    ret = bridge.run()

    if ret != 0:
        print(f"\n  [FAIL] Baseline simulation failed (exit code {ret})")
        sys.exit(1)

    # Save timestep log
    log_path = os.path.join(config.BASELINE_OUTPUT, "timestep_log.json")
    bridge.save_log(log_path)

    # Print summary
    summary = bridge.get_summary()
    print(f"\n  === Baseline Summary ===")
    for k, v in summary.items():
        print(f"    {k}: {v}")

    # Save summary
    summary_path = os.path.join(config.BASELINE_OUTPUT, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  Summary saved: {summary_path}")

    # Quick data validation
    log = bridge.get_log()
    temps = [e["zone_temp"] for e in log]
    print(f"\n  === Data Validation ===")
    print(f"    Timesteps: {len(log)}")
    print(f"    Temp range: {min(temps):.1f} - {max(temps):.1f} C")
    print(f"    All temps plausible (15-40C): "
          f"{'PASS' if all(15 < t < 40 for t in temps) else 'FAIL'}")
    print(f"    Has HVAC data: "
          f"{'PASS' if any(e['hvac_power_w'] > 0 for e in log) else 'FAIL'}")

    print(f"\n  [PASS] Baseline run complete!")
    return bridge


if __name__ == "__main__":
    run_baseline()
