"""
Eco-Loop Building Agents - EnergyPlus Bridge

Wraps the EnergyPlus Python API (library mode) to:
  1. Register a timestep callback
  2. Read sensor values (zone temp, outdoor temp, power, setpoint)
  3. Optionally write actuator values (cooling setpoint override)
  4. Log all timestep data for post-run analysis

Design: accepts an on_timestep(sensor_data) -> Optional[float] callback.
  - For baseline mode: pass on_timestep=None (no override, native schedule runs)
  - For AI mode: pass the LLM agent's decide() method

Usage:
    python -m src.ep_bridge          # Quick test with baseline IDF
"""

import os
import sys
import json
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

from pyenergyplus.api import EnergyPlusAPI


class EnergyPlusBridge:
    """
    EnergyPlus simulation wrapper that reads sensors and writes actuators
    at each timestep via the Python API callback mechanism.
    """

    def __init__(self, idf_path, epw_path, output_dir, on_timestep=None,
                 enable_actuator=False):
        """
        Args:
            idf_path: Path to the IDF file
            epw_path: Path to the EPW weather file
            output_dir: Directory for EnergyPlus output files
            on_timestep: Optional callback function.
                         Signature: on_timestep(sensor_data: dict) -> Optional[float]
                         If it returns a float, that value is written as the
                         cooling setpoint via the actuator.
                         If None, no actuator override (baseline mode).
            enable_actuator: Whether to initialize the actuator handle
                             (only needed for AI-controlled IDF)
        """
        self.idf_path = idf_path
        self.epw_path = epw_path
        self.output_dir = output_dir
        self.on_timestep = on_timestep
        self.enable_actuator = enable_actuator

        # EnergyPlus API
        self.api = EnergyPlusAPI()
        self.state = None

        # Sensor handles (initialized on first callback after data is ready)
        self._handles_initialized = False
        self._h_zone_temp = None
        self._h_outdoor_temp = None
        self._h_chiller_power = None
        self._h_hvac_power = None
        self._h_total_power = None
        self._h_cooling_setpoint = None
        self._h_cooling_rate = None
        self._h_humidity = None

        # Actuator handle (for AI mode)
        self._h_actuator = None

        # Data log: list of dicts, one per actual simulation timestep
        self._log = []

        # Tracking
        self._timestep_count = 0
        self._warmup_count = 0

    def _init_handles(self, state):
        """Initialize sensor and actuator handles. Called once after data is ready."""
        ex = self.api.exchange

        # --- Sensor handles ---
        self._h_zone_temp = ex.get_variable_handle(
            state, "Zone Air Temperature", config.TARGET_ZONE
        )
        self._h_outdoor_temp = ex.get_variable_handle(
            state, "Site Outdoor Air Drybulb Temperature", "Environment"
        )
        self._h_cooling_setpoint = ex.get_variable_handle(
            state, "Zone Thermostat Cooling Setpoint Temperature", config.TARGET_ZONE
        )
        self._h_cooling_rate = ex.get_variable_handle(
            state, "Zone Air System Sensible Cooling Rate", config.TARGET_ZONE
        )
        self._h_humidity = ex.get_variable_handle(
            state, "Zone Relative Humidity", config.TARGET_ZONE
        )
        self._h_chiller_power = ex.get_variable_handle(
            state, "Chiller Electricity Rate", "CENTRAL CHILLER"
        )
        self._h_hvac_power = ex.get_variable_handle(
            state, "Facility Total HVAC Electricity Demand Rate", "Whole Building"
        )
        self._h_total_power = ex.get_variable_handle(
            state, "Facility Total Electricity Demand Rate", "Whole Building"
        )

        # --- Actuator handle (AI mode only) ---
        if self.enable_actuator:
            self._h_actuator = ex.get_actuator_handle(
                state,
                "Schedule:Constant",
                "Schedule Value",
                config.AI_SCHEDULE_NAME
            )
            if self._h_actuator == -1:
                print("[WARNING] Could not get actuator handle for "
                      f"{config.AI_SCHEDULE_NAME}. AI control will not work.")

        # Validate critical handles
        handle_names = {
            "Zone Air Temperature": self._h_zone_temp,
            "Outdoor Temperature": self._h_outdoor_temp,
            "Cooling Setpoint": self._h_cooling_setpoint,
        }
        for name, h in handle_names.items():
            if h == -1:
                print(f"[WARNING] Could not get handle for '{name}' (handle=-1)")

        self._handles_initialized = True

    def _callback(self, state):
        """
        Called at each zone timestep after init heat balance.
        This is where we read sensors, call the on_timestep callback,
        and optionally write the actuator.
        """
        ex = self.api.exchange

        # Skip warmup periods
        if ex.warmup_flag(state):
            self._warmup_count += 1
            return

        # Initialize handles on first real timestep
        if not self._handles_initialized:
            if not ex.api_data_fully_ready(state):
                return
            self._init_handles(state)

        # --- Read time info ---
        month = ex.month(state)
        day = ex.day_of_month(state)
        hour = ex.hour(state)
        ts_num = ex.zone_time_step_number(state)
        sim_time = ex.current_sim_time(state)

        # --- Read sensor values ---
        zone_temp = ex.get_variable_value(state, self._h_zone_temp)
        outdoor_temp = ex.get_variable_value(state, self._h_outdoor_temp)
        cooling_setpoint = ex.get_variable_value(state, self._h_cooling_setpoint)
        cooling_rate = ex.get_variable_value(state, self._h_cooling_rate)

        # These may return 0 if not yet available or key doesn't match
        chiller_power = 0.0
        if self._h_chiller_power and self._h_chiller_power != -1:
            chiller_power = ex.get_variable_value(state, self._h_chiller_power)

        hvac_power = 0.0
        if self._h_hvac_power and self._h_hvac_power != -1:
            hvac_power = ex.get_variable_value(state, self._h_hvac_power)

        total_power = 0.0
        if self._h_total_power and self._h_total_power != -1:
            total_power = ex.get_variable_value(state, self._h_total_power)

        humidity = 50.0  # default
        if self._h_humidity and self._h_humidity != -1:
            humidity = ex.get_variable_value(state, self._h_humidity)

        # --- Build sensor data dict ---
        sensor_data = {
            "month": month,
            "day": day,
            "hour": hour,
            "timestep_num": ts_num,
            "sim_time": sim_time,
            "zone_temp": round(zone_temp, 2),
            "outdoor_temp": round(outdoor_temp, 2),
            "cooling_setpoint": round(cooling_setpoint, 2),
            "cooling_rate_w": round(cooling_rate, 1),
            "chiller_power_w": round(chiller_power, 1),
            "hvac_power_w": round(hvac_power, 1),
            "total_power_w": round(total_power, 1),
            "humidity": round(humidity, 1),
        }

        # --- Call the on_timestep callback (AI or None) ---
        new_setpoint = None
        callback_latency_ms = 0.0

        if self.on_timestep is not None:
            t_start = time.time()
            try:
                new_setpoint = self.on_timestep(sensor_data)
            except Exception as e:
                print(f"[ERROR] on_timestep callback failed at hour {hour}: {e}")
                new_setpoint = None
            callback_latency_ms = (time.time() - t_start) * 1000.0

        # --- Write actuator (AI mode) ---
        if (new_setpoint is not None and self.enable_actuator
                and self._h_actuator is not None and self._h_actuator != -1):
            ex.set_actuator_value(state, self._h_actuator, new_setpoint)

        # --- Log this timestep ---
        log_entry = {
            **sensor_data,
            "ai_setpoint": round(new_setpoint, 2) if new_setpoint is not None else None,
            "callback_latency_ms": round(callback_latency_ms, 1),
        }
        self._log.append(log_entry)
        self._timestep_count += 1

        # --- Console progress ---
        if self._timestep_count % 6 == 1:  # Print every ~6 timesteps
            mode = "AI" if self.on_timestep else "Baseline"
            sp_info = f" -> AI setpoint: {new_setpoint:.1f}C" if new_setpoint else ""
            print(f"  [{mode}] {month:02d}/{day:02d} {hour:02d}:00 | "
                  f"Zone: {zone_temp:.1f}C | Out: {outdoor_temp:.1f}C | "
                  f"SP: {cooling_setpoint:.1f}C | "
                  f"HVAC: {hvac_power:.0f}W{sp_info}")

    def run(self):
        """Run the EnergyPlus simulation with the registered callback."""
        os.makedirs(self.output_dir, exist_ok=True)

        self.state = self.api.state_manager.new_state()

        # Register the callback at the right calling point
        # callback_begin_zone_timestep_after_init_heat_balance runs after
        # zone heat balance is initialized but before HVAC calculations,
        # which is the ideal time to inject setpoint overrides
        self.api.runtime.callback_begin_zone_timestep_after_init_heat_balance(
            self.state, self._callback
        )

        print(f"\n{'='*60}")
        print(f"  EnergyPlus Simulation Starting")
        print(f"  IDF: {os.path.basename(self.idf_path)}")
        print(f"  Mode: {'AI-Controlled' if self.on_timestep else 'Baseline'}")
        print(f"{'='*60}\n")

        # Run EnergyPlus
        ret = self.api.runtime.run_energyplus(self.state, [
            '-d', self.output_dir,
            '-w', self.epw_path,
            self.idf_path
        ])

        # Cleanup
        self.api.state_manager.delete_state(self.state)
        self.state = None

        print(f"\n  Simulation complete. Return code: {ret}")
        print(f"  Timesteps logged: {self._timestep_count}")
        print(f"  Warmup steps skipped: {self._warmup_count}")

        if ret != 0:
            print(f"  [ERROR] EnergyPlus returned non-zero exit code: {ret}")
            # Check error file
            err_path = os.path.join(self.output_dir, "eplusout.err")
            if os.path.isfile(err_path):
                with open(err_path, "r") as f:
                    lines = f.readlines()
                severe = [l.strip() for l in lines if "** Severe  **" in l]
                if severe:
                    print("  Severe errors:")
                    for s in severe[:5]:
                        print(f"    {s}")

        return ret

    def get_log(self):
        """Return the collected timestep data as a list of dicts."""
        return self._log

    def save_log(self, filepath):
        """Save the timestep log to a JSON file."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(self._log, f, indent=2)
        print(f"  Log saved: {filepath} ({len(self._log)} entries)")

    def get_summary(self):
        """Return summary statistics from the logged data."""
        if not self._log:
            return {"error": "No data logged"}

        temps = [e["zone_temp"] for e in self._log]
        powers = [e["total_power_w"] for e in self._log]
        hvac_powers = [e["hvac_power_w"] for e in self._log]

        # Energy calculation: each timestep is 1 hour (hourly timesteps)
        # Total energy in kWh = sum(power_W) * timestep_hours / 1000
        timestep_hours = 1.0  # hourly
        total_kwh = sum(powers) * timestep_hours / 1000.0
        hvac_kwh = sum(hvac_powers) * timestep_hours / 1000.0

        summary = {
            "timesteps": len(self._log),
            "total_kwh": round(total_kwh, 2),
            "hvac_kwh": round(hvac_kwh, 2),
            "avg_zone_temp": round(sum(temps) / len(temps), 2),
            "min_zone_temp": round(min(temps), 2),
            "max_zone_temp": round(max(temps), 2),
            "peak_total_power_w": round(max(powers), 1),
            "peak_hvac_power_w": round(max(hvac_powers), 1),
        }

        if any(e["ai_setpoint"] is not None for e in self._log):
            setpoints = [e["ai_setpoint"] for e in self._log if e["ai_setpoint"] is not None]
            latencies = [e["callback_latency_ms"] for e in self._log if e["callback_latency_ms"] > 0]
            summary["avg_ai_setpoint"] = round(sum(setpoints) / len(setpoints), 2)
            summary["min_ai_setpoint"] = round(min(setpoints), 2)
            summary["max_ai_setpoint"] = round(max(setpoints), 2)
            if latencies:
                summary["avg_llm_latency_ms"] = round(sum(latencies) / len(latencies), 1)
                summary["max_llm_latency_ms"] = round(max(latencies), 1)

        return summary


def main():
    """Quick test: run baseline simulation and print summary."""
    print("=" * 60)
    print("  EnergyPlus Bridge Test (Baseline Mode)")
    print("=" * 60)

    bridge = EnergyPlusBridge(
        idf_path=config.BASELINE_IDF,
        epw_path=config.WEATHER_FILE,
        output_dir=os.path.join(config.BASELINE_OUTPUT, "bridge_test"),
        on_timestep=None,  # Baseline: no override
        enable_actuator=False,
    )

    ret = bridge.run()

    if ret == 0:
        log = bridge.get_log()
        summary = bridge.get_summary()
        print(f"\n  === Summary ===")
        for k, v in summary.items():
            print(f"    {k}: {v}")

        # Show first few log entries
        print(f"\n  === First 3 timestep entries ===")
        for entry in log[:3]:
            print(f"    {entry}")

        print(f"\n  [PASS] Bridge test successful!")
    else:
        print(f"\n  [FAIL] Simulation failed with exit code {ret}")
        sys.exit(1)


if __name__ == "__main__":
    main()
