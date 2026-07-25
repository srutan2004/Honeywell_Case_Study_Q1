"""
Eco-Loop Building Agents — IDF Patcher

Copies the source 5ZoneAirCooled.idf and creates two patched versions:
  1. Baseline IDF — run period shortened to Jul 1-2, extra output variables added
  2. AI IDF      — baseline patches + Schedule:Constant actuator for AI setpoint control

Usage:
    python -m src.idf_patcher           # Create both IDF files
    python -m src.idf_patcher --verify  # Create + verify they parse correctly
"""

import os
import sys
import shutil

# Add project root to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def read_idf(path: str) -> str:
    """Read an IDF file and return its content as a string."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def write_idf(path: str, content: str) -> None:
    """Write content to an IDF file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  [OK] Written: {path}")


def patch_run_period(content: str) -> str:
    """
    Patch RunPeriod from Jan 1 - Dec 31 -> Jul 1 - Jul 2.
    This shortens the simulation to a 2-day summer period for fast iteration.
    """
    old_run_period = (
        "  RunPeriod,\n"
        "    Run Period 1,            !- Name\n"
        "    1,                       !- Begin Month\n"
        "    1,                       !- Begin Day of Month\n"
        "    ,                        !- Begin Year\n"
        "    12,                      !- End Month\n"
        "    31,                      !- End Day of Month\n"
        "    ,                        !- End Year\n"
        "    Tuesday,                 !- Day of Week for Start Day\n"
        "    Yes,                     !- Use Weather File Holidays and Special Days\n"
        "    Yes,                     !- Use Weather File Daylight Saving Period\n"
        "    No,                      !- Apply Weekend Holiday Rule\n"
        "    Yes,                     !- Use Weather File Rain Indicators\n"
        "    Yes;                     !- Use Weather File Snow Indicators"
    )

    new_run_period = (
        "  RunPeriod,\n"
        f"    Run Period 1,            !- Name\n"
        f"    {config.RUN_PERIOD_BEGIN_MONTH},                       !- Begin Month\n"
        f"    {config.RUN_PERIOD_BEGIN_DAY},                       !- Begin Day of Month\n"
        f"    ,                        !- Begin Year\n"
        f"    {config.RUN_PERIOD_END_MONTH},                       !- End Month\n"
        f"    {config.RUN_PERIOD_END_DAY},                       !- End Day of Month\n"
        f"    ,                        !- End Year\n"
        f"    Tuesday,                 !- Day of Week for Start Day\n"
        f"    Yes,                     !- Use Weather File Holidays and Special Days\n"
        f"    Yes,                     !- Use Weather File Daylight Saving Period\n"
        f"    No,                      !- Apply Weekend Holiday Rule\n"
        f"    Yes,                     !- Use Weather File Rain Indicators\n"
        f"    Yes;                     !- Use Weather File Snow Indicators"
    )

    if old_run_period not in content:
        # Try with \r\n line endings
        old_run_period_crlf = old_run_period.replace("\n", "\r\n")
        if old_run_period_crlf in content:
            content = content.replace(old_run_period_crlf, new_run_period.replace("\n", "\r\n"))
            print("  [OK] RunPeriod patched (Jul 1 - Jul 2) [CRLF]")
            return content
        raise ValueError("Could not find RunPeriod block to patch!")

    content = content.replace(old_run_period, new_run_period)
    print("  [OK] RunPeriod patched (Jul 1 - Jul 2)")
    return content


def add_output_variables(content: str) -> str:
    """
    Add extra Output:Variable objects needed for our analysis.
    Inserted right after the existing Output:Variable block.
    """
    extra_outputs = (
        "\n"
        "  Output:Variable,*,Facility Total Electricity Demand Rate,hourly;\n"
        "\n"
        "  Output:Variable,*,Facility Total HVAC Electricity Demand Rate,hourly;\n"
        "\n"
        "  Output:Variable,*,Zone Thermostat Cooling Setpoint Temperature,hourly;\n"
        "\n"
        "  Output:Variable,*,Zone Thermostat Heating Setpoint Temperature,hourly;\n"
    )

    # Find the marker: the last existing Output:Variable line
    marker = "Output:Variable,*,Cooling Coil Sensible Cooling Rate,hourly;"
    if marker not in content:
        raise ValueError(f"Could not find output variable marker: {marker}")

    content = content.replace(
        marker,
        marker + extra_outputs
    )
    print("  [OK] Added output variables (Facility Total Electric Demand Power, Zone Thermostat Cooling/Heating Setpoint)")
    return content


def add_ai_schedule(content: str) -> str:
    """
    Add a Schedule:Constant object that the AI will control via EMS actuator.
    Inserted before the existing Clg-SetP-Sch schedule.
    """
    ai_schedule = (
        "\n"
        "! ===== AI-Controlled Cooling Setpoint Schedule =====\n"
        "! This Schedule:Constant is overridden at each timestep by the Python API\n"
        "! via an EMS actuator (Schedule:Constant / Schedule Value).\n"
        "\n"
        "  Schedule:Constant,\n"
        f"    {config.AI_SCHEDULE_NAME},   !- Name\n"
        "    Temperature,             !- Schedule Type Limits Name\n"
        f"    {config.BASELINE_COOLING_SETPOINT_OCCUPIED};  !- Hourly Value (Initial = baseline occupied setpoint)\n"
        "\n"
    )

    # Insert before the Clg-SetP-Sch definition
    marker = "  Schedule:Compact,\n    Clg-SetP-Sch,"
    marker_crlf = marker.replace("\n", "\r\n")

    if marker in content:
        content = content.replace(marker, ai_schedule + marker)
    elif marker_crlf in content:
        content = content.replace(marker_crlf, ai_schedule.replace("\n", "\r\n") + marker_crlf)
    else:
        raise ValueError("Could not find Clg-SetP-Sch schedule to insert AI schedule before!")

    print(f"  [OK] Added Schedule:Constant '{config.AI_SCHEDULE_NAME}' (initial: {config.BASELINE_COOLING_SETPOINT_OCCUPIED} C)")
    return content


def patch_thermostat_for_ai(content: str) -> str:
    """
    Update ThermostatSetpoint:SingleCooling and DualSetpoint to reference
    the AI-controlled schedule instead of the original Clg-SetP-Sch.
    
    Only patches the zone thermostats (CoolingSetpoint and DualSetPoint),
    NOT the plenum ones (PlenumCoolingSetpoint).
    """
    # 1. Patch ThermostatSetpoint:SingleCooling -> CoolingSetpoint
    old_single_cooling = (
        "  ThermostatSetpoint:SingleCooling,\n"
        "    CoolingSetpoint,         !- Name\n"
        "    Clg-SetP-Sch;            !- Setpoint Temperature Schedule Name"
    )
    new_single_cooling = (
        "  ThermostatSetpoint:SingleCooling,\n"
        "    CoolingSetpoint,         !- Name\n"
        f"    {config.AI_SCHEDULE_NAME};  !- Setpoint Temperature Schedule Name (AI-controlled)"
    )

    if old_single_cooling in content:
        content = content.replace(old_single_cooling, new_single_cooling)
    else:
        old_crlf = old_single_cooling.replace("\n", "\r\n")
        if old_crlf in content:
            content = content.replace(old_crlf, new_single_cooling.replace("\n", "\r\n"))
        else:
            raise ValueError("Could not find ThermostatSetpoint:SingleCooling to patch!")
    print(f"  [OK] Patched ThermostatSetpoint:SingleCooling -> {config.AI_SCHEDULE_NAME}")

    # 2. Patch ThermostatSetpoint:DualSetpoint -> DualSetPoint (cooling schedule only)
    old_dual = (
        "  ThermostatSetpoint:DualSetpoint,\n"
        "    DualSetPoint,            !- Name\n"
        "    Htg-SetP-Sch,            !- Heating Setpoint Temperature Schedule Name\n"
        "    Clg-SetP-Sch;            !- Cooling Setpoint Temperature Schedule Name"
    )
    new_dual = (
        "  ThermostatSetpoint:DualSetpoint,\n"
        "    DualSetPoint,            !- Name\n"
        "    Htg-SetP-Sch,            !- Heating Setpoint Temperature Schedule Name\n"
        f"    {config.AI_SCHEDULE_NAME};  !- Cooling Setpoint Temperature Schedule Name (AI-controlled)"
    )

    if old_dual in content:
        content = content.replace(old_dual, new_dual)
    else:
        old_crlf = old_dual.replace("\n", "\r\n")
        if old_crlf in content:
            content = content.replace(old_crlf, new_dual.replace("\n", "\r\n"))
        else:
            raise ValueError("Could not find ThermostatSetpoint:DualSetpoint to patch!")
    print(f"  [OK] Patched ThermostatSetpoint:DualSetpoint cooling -> {config.AI_SCHEDULE_NAME}")

    return content


def create_baseline_idf() -> str:
    """Create the baseline IDF with shortened run period and extra output variables."""
    print("\n=== Creating Baseline IDF ===")
    content = read_idf(config.IDF_SOURCE)
    content = patch_run_period(content)
    content = add_output_variables(content)
    write_idf(config.BASELINE_IDF, content)
    return content


def create_ai_idf(baseline_content: str) -> None:
    """Create the AI-controlled IDF by adding schedule actuator to the baseline."""
    print("\n=== Creating AI-Controlled IDF ===")
    content = baseline_content
    content = add_ai_schedule(content)
    content = patch_thermostat_for_ai(content)
    write_idf(config.AI_IDF, content)


def verify_idf_syntax(idf_path: str) -> bool:
    """
    Quick verification: check that the IDF file contains expected key objects.
    This is NOT a full EnergyPlus parse — just a sanity check.
    """
    content = read_idf(idf_path)
    checks = [
        ("RunPeriod", "RunPeriod," in content),
        ("SimulationControl", "SimulationControl," in content),
        ("Zone (SPACE1-1)", "SPACE1-1" in content),
        ("ZoneControl:Thermostat", "ZoneControl:Thermostat," in content),
        ("Output:Variable", "Output:Variable," in content),
        (f"Run period month = {config.RUN_PERIOD_BEGIN_MONTH}",
         f"    {config.RUN_PERIOD_BEGIN_MONTH},                       !- Begin Month" in content),
    ]

    basename = os.path.basename(idf_path)
    print(f"\n  Verifying {basename}:")
    all_ok = True
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"    [{status}] {name}")
    return all_ok


def verify_ai_idf_extras(idf_path: str) -> bool:
    """Verify AI-specific patches are present."""
    content = read_idf(idf_path)
    checks = [
        (f"Schedule:Constant ({config.AI_SCHEDULE_NAME})",
         config.AI_SCHEDULE_NAME in content),
        ("SingleCooling -> AI schedule",
         f"{config.AI_SCHEDULE_NAME};  !- Setpoint Temperature Schedule Name (AI-controlled)" in content),
        ("DualSetpoint -> AI schedule",
         f"{config.AI_SCHEDULE_NAME};  !- Cooling Setpoint Temperature Schedule Name (AI-controlled)" in content),
    ]

    print(f"\n  Verifying AI-specific patches:")
    all_ok = True
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"    [{status}] {name}")
    return all_ok


def main():
    """Main entry point for IDF patching."""
    print("=" * 60)
    print("  Eco-Loop IDF Patcher")
    print("=" * 60)
    print(f"\n  Source IDF: {config.IDF_SOURCE}")
    print(f"  Baseline -> {config.BASELINE_IDF}")
    print(f"  AI       -> {config.AI_IDF}")

    # Step 1: Create baseline IDF
    baseline_content = create_baseline_idf()

    # Step 2: Create AI IDF (builds on baseline)
    create_ai_idf(baseline_content)

    # Step 3: Verify (if --verify flag)
    verify = "--verify" in sys.argv
    if verify:
        print("\n" + "=" * 60)
        print("  Verification")
        print("=" * 60)
        baseline_ok = verify_idf_syntax(config.BASELINE_IDF)
        ai_ok = verify_idf_syntax(config.AI_IDF)
        ai_extras_ok = verify_ai_idf_extras(config.AI_IDF)

        if baseline_ok and ai_ok and ai_extras_ok:
            print("\n  [PASS] All verifications PASSED!")
        else:
            print("\n  [FAIL] Some verifications FAILED!")
            sys.exit(1)

    print("\n  Done! IDF files ready for simulation.\n")


if __name__ == "__main__":
    main()
