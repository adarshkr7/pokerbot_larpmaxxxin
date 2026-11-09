"""Integration test: a short seeded match through the organisers' engine.

Must finish with no forfeit and zero notices (engine corrections) for our bot.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "starter_kit" / "engine.py"
BOT = ROOT / "bot" / "bot.py"
OPPONENT = ROOT / "starter_kit" / "example_bots" / "random_bot.py"


def test_short_match_vs_random_bot(tmp_path):
    cmd = [sys.executable, str(ENGINE), str(BOT), str(OPPONENT),
           "--hands", "40", "--seed", "1", "--python", sys.executable,
           "--log-dir", str(tmp_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=ROOT)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "40 of 40 hands played" in out, out
    line_a = next(l for l in out.splitlines() if l.strip().startswith("A "))
    assert re.search(r"notices\s+0\b", line_a), f"our bot was corrected by the engine:\n{out}"
    assert "forfeit" not in out.lower(), out
