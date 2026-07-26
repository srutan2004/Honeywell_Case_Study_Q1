"""
Eco-Loop Building Agents - AI Runner (MCP Agentic Closed-Loop Control)

Runs the EnergyPlus simulation with the MCP-powered LLM agent controlling
the cooling setpoint at each timestep. Uses agentic tool calling:

   EnergyPlus sensors -> MCP Server -> LLM Agent (tool calling) -> MCP tools
                                                                       |
   EnergyPlus actuator <-- set_cooling_setpoint <-----------------------+

The agent uses MCP tools to: read sensors, calculate PMV, check carbon
intensity, check peak demand, and set the optimal cooling setpoint.

Usage:
    python -m src.ai_runner
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.ep_bridge import EnergyPlusBridge
from src.mcp_server import MCPToolServer
from src.mcp_agent import MCPAgent


def run_ai_controlled():
    """Run the AI-controlled simulation with MCP agentic tools."""
    print("=" * 60)
    print("  AI-Controlled Runner (MCP Agentic Mode)")
    print("  (LLM uses MCP tools to decide cooling setpoint)")
    print("=" * 60)

    # Ensure AI IDF exists
    if not os.path.isfile(config.AI_IDF):
        print(f"  [ERROR] AI IDF not found: {config.AI_IDF}")
        print("  Run 'python -m src.idf_patcher' first.")
        sys.exit(1)

    # Create MCP server and agent
    print(f"\n  Initializing MCP Tool Server...")
    mcp_server = MCPToolServer(output_dir=config.AI_OUTPUT)
    print(f"  Tools registered: {list(mcp_server._tools.keys())}")

    print(f"  Initializing MCP Agent (model: {config.OLLAMA_MODEL})...")
    agent = MCPAgent(model=config.OLLAMA_MODEL, verbose=True)

    # Create a callback that passes both sensor_data and mcp_server
    def mcp_callback(sensor_data):
        return agent.decide(sensor_data, mcp_server)

    # Create bridge in AI mode with the MCP callback
    bridge = EnergyPlusBridge(
        idf_path=config.AI_IDF,
        epw_path=config.WEATHER_FILE,
        output_dir=config.AI_OUTPUT,
        on_timestep=mcp_callback,
        enable_actuator=True,
    )

    # Run simulation
    ret = bridge.run()

    if ret != 0:
        print(f"\n  [FAIL] AI simulation failed (exit code {ret})")
        sys.exit(1)

    # Save timestep log
    log_path = os.path.join(config.AI_OUTPUT, "timestep_log.json")
    bridge.save_log(log_path)

    # Save MCP agent decisions
    decisions_path = os.path.join(config.AI_OUTPUT, "llm_decisions.json")
    agent.save_decisions(decisions_path)

    # Print simulation summary
    summary = bridge.get_summary()
    print(f"\n  === AI-Controlled Summary (MCP Mode) ===")
    for k, v in summary.items():
        print(f"    {k}: {v}")

    # Print agent stats
    agent_stats = agent.get_stats()
    print(f"\n  === MCP Agent Stats ===")
    for k, v in agent_stats.items():
        print(f"    {k}: {v}")

    # Save combined summary
    combined = {"simulation": summary, "agent": agent_stats, "mode": "MCP_agentic"}
    summary_path = os.path.join(config.AI_OUTPUT, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(combined, f, indent=2)
    print(f"\n  Summary saved: {summary_path}")

    # Data validation
    log = bridge.get_log()
    temps = [e["zone_temp"] for e in log]
    setpoints = [e["ai_setpoint"] for e in log if e["ai_setpoint"] is not None]

    print(f"\n  === Data Validation ===")
    print(f"    Timesteps: {len(log)}")
    print(f"    AI decisions made: {len(setpoints)}")
    print(f"    Temp range: {min(temps):.1f} - {max(temps):.1f} C")
    print(f"    Setpoint range: {min(setpoints):.1f} - {max(setpoints):.1f} C"
          if setpoints else "    No setpoints recorded")
    print(f"    All temps plausible (15-40C): "
          f"{'PASS' if all(15 < t < 40 for t in temps) else 'FAIL'}")
    print(f"    Setpoints vary: "
          f"{'PASS' if len(set(round(s,1) for s in setpoints)) > 1 else 'FAIL'}"
          if setpoints else "    N/A")
    print(f"    Setpoints in bounds [{config.COOLING_SETPOINT_MIN},{config.COOLING_SETPOINT_MAX}]: "
          f"{'PASS' if all(config.COOLING_SETPOINT_MIN <= s <= config.COOLING_SETPOINT_MAX for s in setpoints) else 'FAIL'}"
          if setpoints else "    N/A")

    print(f"\n  [PASS] AI-controlled (MCP agentic) run complete!")
    return bridge, agent


if __name__ == "__main__":
    run_ai_controlled()
