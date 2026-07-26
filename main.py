"""
Eco-Loop Building Agents - Main Orchestrator

End-to-end pipeline that runs all steps in sequence:
  1. Patch IDF files (baseline + AI)
  2. Run baseline simulation
  3. Run AI-controlled simulation (LLM in the loop)
  4. Analyze and compare results
  5. Launch dashboard

Usage:
    python main.py              # Full pipeline
    python main.py --skip-sim   # Skip simulations (use existing logs)
    python main.py --no-dashboard  # Don't launch the dashboard
"""

import os
import sys
import argparse
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def banner(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Eco-Loop Building Agents Pipeline")
    parser.add_argument("--skip-sim", action="store_true",
                        help="Skip simulations (use existing output logs)")
    parser.add_argument("--no-dashboard", action="store_true",
                        help="Don't launch the dashboard after analysis")
    parser.add_argument("--port", type=int, default=8080,
                        help="Dashboard port (default: 8080)")
    args = parser.parse_args()

    total_start = time.time()

    # ── Step 1: Patch IDF Files ──────────────────────────
    banner("Step 1/5: IDF File Preparation")

    from src.idf_patcher import create_baseline_idf, create_ai_idf
    if (os.path.isfile(config.BASELINE_IDF) and os.path.isfile(config.AI_IDF)):
        print("  IDF files already exist. Skipping patching.")
        print("  (Delete idf_files/ to force re-patching)")
    else:
        baseline_content = create_baseline_idf()
        create_ai_idf(baseline_content)

    print("  IDF files ready.")

    # ── Step 2: Baseline Simulation ──────────────────────
    if args.skip_sim:
        banner("Step 2/5: Baseline Simulation (SKIPPED)")
        baseline_log_path = os.path.join(config.BASELINE_OUTPUT, "timestep_log.json")
        if not os.path.isfile(baseline_log_path):
            print(f"  [ERROR] No existing baseline log: {baseline_log_path}")
            print("  Run without --skip-sim to generate it.")
            sys.exit(1)
        print(f"  Using existing log: {baseline_log_path}")
    else:
        banner("Step 2/5: Baseline Simulation")
        from src.baseline_runner import run_baseline
        run_baseline()

    # ── Step 3: AI-Controlled Simulation ─────────────────
    if args.skip_sim:
        banner("Step 3/5: AI-Controlled Simulation (SKIPPED)")
        ai_log_path = os.path.join(config.AI_OUTPUT, "timestep_log.json")
        if not os.path.isfile(ai_log_path):
            print(f"  [ERROR] No existing AI log: {ai_log_path}")
            print("  Run without --skip-sim to generate it.")
            sys.exit(1)
        print(f"  Using existing log: {ai_log_path}")
    else:
        banner("Step 3/5: AI-Controlled Simulation")
        from src.ai_runner import run_ai_controlled
        run_ai_controlled()

    # ── Step 3b: Heuristic Simulation ────────────────────
    if args.skip_sim:
        banner("Step 3b/5: Heuristic Simulation (SKIPPED)")
        heuristic_log_path = os.path.join(config.HEURISTIC_OUTPUT, "timestep_log.json")
        if not os.path.isfile(heuristic_log_path):
            print(f"  [ERROR] No existing heuristic log: {heuristic_log_path}")
            print("  Run without --skip-sim to generate it.")
            sys.exit(1)
        print(f"  Using existing log: {heuristic_log_path}")
    else:
        banner("Step 3b/5: Heuristic Simulation")
        from src.heuristic_runner import run_heuristic_controlled
        run_heuristic_controlled()

    # ── Step 4: Analysis & Comparison ────────────────────
    banner("Step 4/5: Analysis & Comparison")
    from src.analysis import main as run_analysis
    run_analysis()

    # ── Step 5: Dashboard ────────────────────────────────
    total_time = time.time() - total_start

    banner("Pipeline Complete!")
    print(f"  Total time: {total_time:.1f}s")
    print(f"  Results: {config.RESULTS_DIR}")
    print(f"  Report:  {config.SUMMARY_REPORT}")

    if not args.no_dashboard:
        banner("Step 5/5: Launching Dashboard")
        import webbrowser
        import http.server
        import socketserver
        import threading

        os.chdir(config.PROJECT_ROOT)
        handler = http.server.SimpleHTTPRequestHandler
        handler.log_message = lambda self, fmt, *a: None

        try:
            httpd = socketserver.TCPServer(("", args.port), handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            url = f"http://localhost:{args.port}/dashboard/index.html"
            print(f"  Dashboard: {url}")
            print(f"  Press Ctrl+C to stop.\n")
            webbrowser.open(url)
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Server stopped.")
        except OSError:
            print(f"  [WARN] Port {args.port} in use. Run manually:")
            print(f"  python run_dashboard.py --port {args.port + 1}")
    else:
        print("\n  To view the dashboard, run:")
        print("  python run_dashboard.py\n")


if __name__ == "__main__":
    main()
