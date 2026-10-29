"""Entry point to launch the Academic Campus Decision Assistant Web Server.

Run:
    python run_server.py
Then open http://localhost:8000 in your browser.
"""

import sys
from pathlib import Path

# Add src to python path
src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import uvicorn

if __name__ == "__main__":
    print("=" * 70)
    print("  HCMUS Academic Campus Decision Assistant (SP1 -> SP2)")
    print("  Frontend & API Server starting on http://localhost:8000")
    print("=" * 70)
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True, reload_dirs=[str(src_dir)])
