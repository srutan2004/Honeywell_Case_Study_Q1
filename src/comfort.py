"""
Eco-Loop Building Agents - Comfort Analysis

Evaluates thermal comfort for a simulation run by analyzing zone temperature
against the comfort band [21, 26]C during occupied hours (6am-8pm).

Usage:
    python -m src.comfort    # Analyze both baseline and AI logs
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.pmv import calculate_pmv, is_pmv_comfortable


def analyze_comfort(timestep_log):
    """
    Analyze thermal comfort from a timestep log.

    Args:
        timestep_log: list of dicts with keys: hour, zone_temp, etc.

    Returns:
        dict with comfort metrics
    """
    total_steps = len(timestep_log)
    if total_steps == 0:
        return {"error": "Empty log"}

    # Separate occupied vs unoccupied timesteps
    occupied_steps = [
        e for e in timestep_log
        if config.OCCUPIED_START_HOUR <= e["hour"] < config.OCCUPIED_END_HOUR
    ]
    unoccupied_steps = [
        e for e in timestep_log
        if e["hour"] < config.OCCUPIED_START_HOUR or e["hour"] >= config.OCCUPIED_END_HOUR
    ]

    # --- Occupied hour analysis ---
    occ_temps = [e["zone_temp"] for e in occupied_steps]
    occ_count = len(occ_temps)

    if occ_count > 0:
        in_comfort = sum(
            1 for t in occ_temps
            if config.COMFORT_TEMP_MIN <= t <= config.COMFORT_TEMP_MAX
        )
        too_hot = sum(1 for t in occ_temps if t > config.COMFORT_TEMP_MAX)
        too_cold = sum(1 for t in occ_temps if t < config.COMFORT_TEMP_MIN)

        comfort_pct = round(in_comfort / occ_count * 100, 1)
        avg_occ_temp = round(sum(occ_temps) / occ_count, 2)

        # Temperature excursions
        hot_excursions = [t - config.COMFORT_TEMP_MAX for t in occ_temps if t > config.COMFORT_TEMP_MAX]
        cold_excursions = [config.COMFORT_TEMP_MIN - t for t in occ_temps if t < config.COMFORT_TEMP_MIN]

        max_hot_excursion = round(max(hot_excursions), 2) if hot_excursions else 0.0
        max_cold_excursion = round(max(cold_excursions), 2) if cold_excursions else 0.0
    else:
        comfort_pct = 100.0
        avg_occ_temp = 0.0
        in_comfort = 0
        too_hot = 0
        too_cold = 0
        max_hot_excursion = 0.0
        max_cold_excursion = 0.0

    # --- Unoccupied hour analysis ---
    unocc_temps = [e["zone_temp"] for e in unoccupied_steps]
    unocc_count = len(unocc_temps)
    avg_unocc_temp = round(sum(unocc_temps) / unocc_count, 2) if unocc_count > 0 else 0.0

    # --- Overall stats ---
    all_temps = [e["zone_temp"] for e in timestep_log]

    # Dangerous excursion flags
    dangerous_hot = sum(1 for t in all_temps if t > 30.0)
    dangerous_cold = sum(1 for t in all_temps if t < 18.0)

    return {
        "total_timesteps": total_steps,
        "occupied_timesteps": occ_count,
        "unoccupied_timesteps": unocc_count,
        # Comfort metrics (occupied hours only)
        "comfort_pct": comfort_pct,
        "in_comfort_count": in_comfort,
        "too_hot_count": too_hot,
        "too_cold_count": too_cold,
        "max_hot_excursion_c": max_hot_excursion,
        "max_cold_excursion_c": max_cold_excursion,
        # Temperature stats
        "avg_occupied_temp": avg_occ_temp,
        "avg_unoccupied_temp": avg_unocc_temp,
        "min_temp": round(min(all_temps), 2),
        "max_temp": round(max(all_temps), 2),
        "avg_temp": round(sum(all_temps) / len(all_temps), 2),
        # Safety
        "dangerous_hot_count": dangerous_hot,
        "dangerous_cold_count": dangerous_cold,
        # PMV analysis (occupied hours)
        **_calculate_pmv_stats(occupied_steps),
    }


def _calculate_pmv_stats(occupied_steps):
    """Calculate PMV/PPD stats for occupied timesteps."""
    if not occupied_steps:
        return {"avg_pmv": 0, "max_pmv": 0, "avg_ppd": 5.0, "pmv_comfort_pct": 100.0}

    pmv_values = []
    ppd_values = []
    for e in occupied_steps:
        ta = e.get("zone_temp", 23.0)
        rh = e.get("humidity", 50.0)
        result = calculate_pmv(ta=ta, rh=rh, vel=0.1, met=1.2, clo=0.5)
        pmv_values.append(result["pmv"])
        ppd_values.append(result["ppd"])

    pmv_comfortable = sum(1 for p in pmv_values if is_pmv_comfortable(p))

    return {
        "avg_pmv": round(sum(pmv_values) / len(pmv_values), 2),
        "max_pmv": round(max(pmv_values, key=abs), 2),
        "min_pmv": round(min(pmv_values), 2),
        "avg_ppd": round(sum(ppd_values) / len(ppd_values), 1),
        "pmv_comfort_pct": round(pmv_comfortable / len(pmv_values) * 100, 1),
    }


def print_comfort_report(name, comfort):
    """Print a formatted comfort report."""
    print(f"\n  === {name} Comfort Report ===")
    print(f"    Occupied timesteps: {comfort['occupied_timesteps']}")
    print(f"    Comfort band: [{config.COMFORT_TEMP_MIN}, {config.COMFORT_TEMP_MAX}] C")
    print(f"    In comfort: {comfort['in_comfort_count']}/{comfort['occupied_timesteps']} "
          f"({comfort['comfort_pct']}%)")
    print(f"    Too hot: {comfort['too_hot_count']} | Too cold: {comfort['too_cold_count']}")
    if comfort.get('avg_pmv') is not None:
        print(f"    PMV: avg={comfort['avg_pmv']}, max={comfort['max_pmv']} "
              f"(PPD={comfort['avg_ppd']}%)")
        print(f"    PMV comfort (|PMV|<0.7): {comfort['pmv_comfort_pct']}%")
    if comfort['max_hot_excursion_c'] > 0:
        print(f"    Max hot excursion: +{comfort['max_hot_excursion_c']} C above {config.COMFORT_TEMP_MAX} C")
    if comfort['max_cold_excursion_c'] > 0:
        print(f"    Max cold excursion: -{comfort['max_cold_excursion_c']} C below {config.COMFORT_TEMP_MIN} C")
    print(f"    Avg occupied temp: {comfort['avg_occupied_temp']} C")
    print(f"    Avg unoccupied temp: {comfort['avg_unoccupied_temp']} C")
    if comfort['dangerous_hot_count'] or comfort['dangerous_cold_count']:
        print(f"    [WARNING] Dangerous temps: {comfort['dangerous_hot_count']} hot (>30C), "
              f"{comfort['dangerous_cold_count']} cold (<18C)")


def main():
    """Analyze comfort for both baseline and AI runs."""
    print("=" * 60)
    print("  Comfort Analysis")
    print("=" * 60)

    results = {}

    for name, output_dir in [("Baseline", config.BASELINE_OUTPUT),
                              ("AI-Controlled", config.AI_OUTPUT)]:
        log_path = os.path.join(output_dir, "timestep_log.json")
        if not os.path.isfile(log_path):
            print(f"\n  [SKIP] {name}: {log_path} not found")
            continue

        with open(log_path) as f:
            log = json.load(f)

        comfort = analyze_comfort(log)
        results[name.lower().replace("-", "_")] = comfort
        print_comfort_report(name, comfort)

    if len(results) == 2:
        b = results["baseline"]
        a = results["ai_controlled"]
        print(f"\n  === Comfort Comparison ===")
        print(f"    Baseline comfort: {b['comfort_pct']}%")
        print(f"    AI comfort:       {a['comfort_pct']}%")
        delta = a['comfort_pct'] - b['comfort_pct']
        print(f"    Delta:            {delta:+.1f}%")
        print(f"\n  [PASS] Comfort analysis complete!")


if __name__ == "__main__":
    main()
