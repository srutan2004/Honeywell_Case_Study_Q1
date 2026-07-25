"""
Eco-Loop Building Agents — Dashboard HTTP Server

Serves the dashboard and results data on localhost.

Usage:
    python run_dashboard.py             # Serve on port 8080
    python run_dashboard.py --port 3000 # Custom port
"""

import http.server
import socketserver
import os
import sys
import webbrowser
import argparse


def main():
    parser = argparse.ArgumentParser(description="Serve the Eco-Loop dashboard")
    parser.add_argument("--port", type=int, default=8080, help="Port number (default: 8080)")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")
    args = parser.parse_args()

    # Serve from project root so both /dashboard/ and /results/ are accessible
    project_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_root)

    # Verify required files exist
    required = [
        os.path.join("dashboard", "index.html"),
        os.path.join("results", "comparison_data.json"),
    ]
    for f in required:
        if not os.path.isfile(f):
            print(f"  [ERROR] Missing: {f}")
            print("  Run 'python -m src.analysis' first to generate results.")
            sys.exit(1)

    handler = http.server.SimpleHTTPRequestHandler

    # Suppress log noise
    handler.log_message = lambda self, fmt, *a: None

    try:
        with socketserver.TCPServer(("", args.port), handler) as httpd:
            url = f"http://localhost:{args.port}/dashboard/index.html"
            print(f"\n  {'='*50}")
            print(f"  Eco-Loop Dashboard Server")
            print(f"  {'='*50}")
            print(f"  URL:  {url}")
            print(f"  Stop: Ctrl+C")
            print(f"  {'='*50}\n")

            if not args.no_browser:
                webbrowser.open(url)

            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
    except OSError as e:
        if "Address already in use" in str(e) or "10048" in str(e):
            print(f"  [ERROR] Port {args.port} is in use. Try: python run_dashboard.py --port {args.port + 1}")
        else:
            raise


if __name__ == "__main__":
    main()
