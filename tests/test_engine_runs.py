"""Whole matches through the organisers' engine (F01 plan 6A2, 6C, and 3.5 on real sequences)."""
import os
import re
from concurrent.futures import ThreadPoolExecutor

import pytest

from engine_util import (RANDOM_BOT, STARTER, TESTS, V0_BOT, assert_clean, run_match)

OPPONENTS = {"random": RANDOM_BOT, "starter": STARTER}


def parallel(fn, items):
    with ThreadPoolExecutor(max(1, min(4, (os.cpu_count() or 2) // 2))) as ex:
        return list(ex.map(fn, items))


@pytest.mark.parametrize("opp", sorted(OPPONENTS))
@pytest.mark.parametrize("chaos_seed", [1, 2])
def test_chaos_bot_is_never_corrected(tmp_path, opp, chaos_seed):
    """Garbage intents through our legality layer: the engine must never send a notice."""
    env = dict(os.environ, CHAOS_SEED=str(chaos_seed))
    out, res = run_match(TESTS / "chaos_bot.py", OPPONENTS[opp], seed=chaos_seed, log_dir=tmp_path,
                         hands=400, env=env)
    assert_clean(out, res)
    errors = "".join((tmp_path / f"A_leg{k}_stderr.txt").read_text(errors="replace") for k in (1, 2))
    assert "chaos" in errors, "the chaos bot never raised: the test is not exercising the firewall"


@pytest.mark.parametrize("opp", sorted(OPPONENTS))
def test_state_invariants_on_real_engine_sequences(tmp_path, opp):
    out, res = run_match(TESTS / "state_check_bot.py", OPPONENTS[opp], seed=11, log_dir=tmp_path, hands=400)
    assert_clean(out, res)
    for k in (1, 2):
        text = (tmp_path / f"A_leg{k}_stderr.txt").read_text(errors="replace")
        assert "STATE_FAIL" not in text, text[:3000]
        m = re.search(r"STATE_CHECKS (\d+)", text)
        assert m and int(m.group(1)) >= 400, text[:3000]


V0_DISCARD_ENV = dict(os.environ, PATCH_MODE="v0_discard,v0_preflop,v0_postflop")


def test_c1_head_to_head_vs_v0_is_exactly_zero(tmp_path):
    """Identical deterministic strategies cancel exactly under duplicate deals. Our discard (F05/W3), preflop
    play (W4) and postflop betting (W5) are the intended differences from v0, so all three are swapped back to v0's
    here (tests/patched_bot.py, modes v0_discard,v0_preflop,v0_postflop)."""
    def one(seed):
        return seed, run_match(TESTS / "patched_bot.py", V0_BOT, seed=seed, log_dir=tmp_path / f"s{seed}",
                               hands=400, env=V0_DISCARD_ENV)
    for seed, (out, res) in parallel(one, range(301, 311)):
        assert_clean(out, res)
        assert res["A"]["net"] == 0 and res["B"]["net"] == 0, (seed, out)


def deterministic_view(log_text):
    """match.log without the fields that legitimately vary: time used, log paths and bot labels."""
    keep = []
    for line in log_text.splitlines():
        if re.match(r"L\d+ #", line):
            keep.append(line)                                     # per-hand records
        elif "hands played" in line or line.startswith(("Result:", "Capped delta")):
            keep.append(line)
        else:
            m = re.match(r"^\s+([AB])\s+.*?net\s+([+-]?\d+)\s+time used.*notices (\d+)", line)
            if m:
                keep.append(f"{m.group(1)} net {m.group(2)} notices {m.group(3)}")
    return keep


def test_c2_play_identical_to_v0_against_starter(tmp_path):
    """Everything but the discard, preflop and postflop play (swapped back to v0's, as in C1) plays exactly like
    v0."""
    def one(job):
        bot, seed = job
        d = tmp_path / f"{bot.parent.parent.name}_{bot.parent.name}_{seed}"
        env = V0_DISCARD_ENV if bot.name == "patched_bot.py" else None
        out, res = run_match(bot, STARTER, seed=seed, log_dir=d, hands=400, env=env)
        assert_clean(out, res)
        return deterministic_view((d / "match.log").read_text(encoding="utf-8"))
    seeds = range(401, 406)
    ours = parallel(one, [(TESTS / "patched_bot.py", s) for s in seeds])
    v0 = parallel(one, [(V0_BOT, s) for s in seeds])
    for seed, a, b in zip(seeds, ours, v0):
        assert len(a) == 400 + 5, (seed, len(a))
        assert a == b, f"seed {seed}: play differs from v0"
