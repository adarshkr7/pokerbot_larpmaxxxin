"""Shared helpers for tests that use the organisers' engine (imported by file path, never modified)."""
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
ENGINE_PATH = ROOT / "starter_kit" / "engine.py"
BOT = ROOT / "bot" / "bot.py"
CHAMPION = ROOT / "champion" / "bot" / "bot.py"
RANDOM_BOT = ROOT / "starter_kit" / "example_bots" / "random_bot.py"
STARTER = ROOT / "starter_kit" / "bot.py"
PY = sys.executable

_spec = importlib.util.spec_from_file_location("pokerbots_engine", ENGINE_PATH)
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)

SIDE = re.compile(r"^\s+([AB])\s+.*?net\s+([+-]?\d+)\s+time used\s+([\d.]+) s.*notices (\d+)", re.M)


def run_match(bot_a, bot_b, seed, log_dir, hands=None, stage=None, env=None, timeout=300):
    """Run one engine match; return (stdout+stderr, {"A": {...}, "B": {...}, "played": n, "hands": m})."""
    cmd = [PY, str(ENGINE_PATH), str(bot_a), str(bot_b), "--seed", str(seed),
           "--python", PY, "--log-dir", str(log_dir)]
    if hands:
        cmd += ["--hands", str(hands)]
    if stage:
        cmd += ["--stage", str(stage)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT, env=env)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    res = {}
    m = re.search(r"(\d+) of (\d+) hands played", out)
    assert m, out
    res["played"], res["hands"] = int(m.group(1)), int(m.group(2))
    for side, net, used, notices in SIDE.findall(out):
        res[side] = {"net": int(net), "time": float(used), "notices": int(notices)}
    res["forfeit"] = "forfeited" in out
    return out, res


def assert_clean(out, res):
    """Every hand played, no forfeit, no notices for our bot (A)."""
    assert not res["forfeit"], out
    assert res["played"] == res["hands"], out
    assert res["A"]["notices"] == 0, f"our bot was corrected by the engine:\n{out}"
