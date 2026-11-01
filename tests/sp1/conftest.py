import sys
from pathlib import Path

# tests/sp1/conftest.py -> repo root is two levels up
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
