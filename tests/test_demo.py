"""The public demo must keep working: good passes, broken fails, reports reproducible."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_demo_runs_and_reports_are_reproducible():
    proc = subprocess.run([sys.executable, str(REPO / "examples" / "run_demo.py"), "--verify"],
                          capture_output=True, text=True, cwd=REPO)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DEMO OK" in proc.stdout
