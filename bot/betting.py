"""Postflop betting: flop (3 hole cards, before the discard), turn and river (strategies/05_postflop_betting.md).

Public:
  decide(req, hand_state, opp, clock, rng) -> dict      action intent {"action": ..., "amount": ...}; never raises
                                                        (None if our hole cards are unknown -> caller's fallback)
  bet_amount(spot, f, spr_shove=None) -> int            B3 raise-to arithmetic: menu fraction f, clamp, shove-snap
  calls(eq, to_call, pot, street, ip, no_future) -> bool   B1 calling rule
  bluff_prob(bet, pot, ftb, known, mult=1.0) -> float   B6 per-hand river bluff probability
  semi_prob(ftb, known, mult=1.0) -> float              B5 semi-bluff probability
  preflop_play(history, reads, info=1.0) -> list[float] B7 prior: P(their preflop line | class), 1755 classes
  opp_range(req, hand_state, opp) -> np.ndarray(1326)   B7 turn/river range (pair_index), as decide uses it
  stats                                                 per-street decision times, tiers and paths (diagnostic)

Equity semantics (02/E3, 03/D1): on the flop, the max over our three keeps of each keep's average over shared
samples (discard.keep_equities; the opponent is dealt a triple weighted by its preflop line and flop actions and
keeps its max-S pair); on the turn, weighted Monte Carlo vs the posterior after their discard; on the river, exact
enumeration of that posterior. Each also gives eq_call, the equity vs their *calling* range (B2).
All thresholds live in params.py (# --- W5 ---). Card ids 0..51 (rank * 4 + suit).
"""
import math
import random
import time

import numpy as np

import discard as discard_mod
import equity as equity_mod
import params
import preflop as preflop_mod
import replay
from cards import PAIRS, is_valid, parse
from evaluator import eval7
from log import log, log_exc

_now = time.perf_counter
_RNG = random.Random()
STREETS = ("flop", "turn", "river")
N_PAIRS = 1326

_CARD_PAIRS = [[] for _ in range(52)]          # pair indices that contain card c
for _i, (_a, _b) in enumerate(PAIRS):
    _CARD_PAIRS[_a].append(_i)
    _CARD_PAIRS[_b].append(_i)
_CARD_PAIRS = [np.array(x, dtype=np.int64) for x in _CARD_PAIRS]
_PA = np.array([a for a, _ in PAIRS], dtype=np.int64)
_PB = np.array([b for _, b in PAIRS], dtype=np.int64)
_PCT = np.array(preflop_mod.PCT, dtype=float)
_MULT = np.array(discard_mod.MULT, dtype=float)

stats = {"n": {}, "ms": {}, "tier": {}, "path": {}}
_STATS_CAP = 4000
_HC = {"key": None}                           # per-hand cache (reset when the hand changes)


# ----------------------------------------------------------------------------------------------- small helpers
def _sig(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _finite(x, default):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return default
    x = float(x)
    return x if math.isfinite(x) else default


def _rnd(x):
    return int(math.floor(x + 0.5))


def _record(street, ms, tier, path):
    try:
        st = stats
        st["n"][street] = st["n"].get(street, 0) + 1
        lst = st["ms"].setdefault(street, [])
        if len(lst) < _STATS_CAP:
            lst.append(ms)
        st["tier"][tier] = st["tier"].get(tier, 0) + 1
        st["path"][path] = st["path"].get(path, 0) + 1
    except Exception:
        pass


# ----------------------------------------------------------------------------------------------- B1 / B3 / B5 / B6
def calls(eq, to_call, pot, street, ip, no_future):
    """B1: call iff R_pos * eq > to_call / (pot + to_call) + margin. `pot` already holds the bet we face.
    No future betting (river, or the call puts a player all-in): R = 1 and margin 0."""
    if to_call <= 0:
        return True
    price = to_call / (pot + to_call)
    if no_future or street == "river":
        r, m = 1.0, 0.0
    else:
        r = params.BET_R_IP if ip else params.BET_R_OOP
        m = params.BET_MARGIN.get(street, 0.0)
    return r * eq > price + m


def bet_amount(s, f, spr_shove=None):
    """B3: raise-to total for a pot fraction f. Opening bet (to_call == 0): my_bet + round(f * pot); raise over a
    bet: opp_bet + round(f * (pot + to_call)). Clamped to [min_raise, max_raise]. Shove-snap: max_raise when what
    would be left behind (max_raise - amount) is below BET_SNAP_FRAC x the pot after the call, or (spr_shove) at
    most spr_shove x that pot. Requires s.can_raise. Returns an int."""
    if s.to_call <= 0:
        amt = s.my_bet + _rnd(f * s.pot)
    else:
        amt = s.opp_bet + _rnd(f * (s.pot + s.to_call))
    amt = int(min(max(amt, s.lo), s.hi))
    new_pot = s.pot + (amt - s.my_bet) + (amt - s.opp_bet)
    behind = s.hi - amt
    if behind < params.BET_SNAP_FRAC * new_pot or (spr_shove is not None and behind <= spr_shove * new_pot):
        amt = s.hi
    return int(amt)


def bluff_prob(bet, pot, ftb, known, mult=1.0):
    """B6: probability of bluffing one air hand with a bet of `bet` chips into `pot` (before the bet).
    Baseline min(1, (v / a) * B / (P + B)). Exploit test (their fold-to-bet trusted): ftb >= B / (P + B) -> 1;
    ftb < BET_BLUFF_MIN_FTB -> 0. Times mult (0 vs stations / random bots)."""
    if bet <= 0 or pot <= 0 or mult <= 0:
        return 0.0
    bar = bet / (pot + bet)
    p = min(1.0, params.BET_BLUFF_V / params.BET_BLUFF_A * bar)
    if known:
        if ftb >= bar:
            p = 1.0
        elif ftb < params.BET_BLUFF_MIN_FTB:
            p = 0.0
    return max(0.0, min(1.0, p * mult))


def semi_prob(ftb, known, mult=1.0):
    """B5: semi-bluff probability. Trusted stats: BET_SEMI_P_HIGH when they fold more than BET_SEMI_FTB, else 0;
    unknown: BET_SEMI_P_BASE. Times mult (0 vs stations, random bots, maniacs)."""
    if known:
        p = params.BET_SEMI_P_HIGH if ftb > params.BET_SEMI_FTB else 0.0
    else:
        p = params.BET_SEMI_P_BASE
    return max(0.0, min(1.0, p * mult))


# ----------------------------------------------------------------------------------------------- opponent reads
def _tilted_mean(k):
    """Mean of u under the density exp(k u) on [0, 1] (0.5 at k = 0; increasing in k)."""
    if abs(k) < 1e-6:
        return 0.5
    return 1.0 / (1.0 - math.exp(-k)) - 1.0 / k


def pit_k(m):
    """The tilt k with _tilted_mean(k) = m, clipped to [BET_PIT_K_LO, BET_PIT_K_HI] (bisection; 0 for m = 0.5)."""
    lo, hi = float(params.BET_PIT_K_LO), float(params.BET_PIT_K_HI)
    m = _finite(m, 0.5)
    if abs(m - 0.5) < 1e-9:
        return 0.0
    if m <= _tilted_mean(lo):
        return lo
    if m >= _tilted_mean(hi):
        return hi
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if _tilted_mean(mid) < m:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _arch(opp):
    """B8b: archetype weights, normalised; unknown or malformed -> {"neutral": 1}."""
    try:
        aw = opp.archetype_weights()
        out = {}
        for k, v in dict(aw).items():
            v = _finite(v, 0.0)
            if v > 0:
                out[str(k)] = v
        tot = sum(out.values())
        if tot > 0:
            return {k: v / tot for k, v in out.items()}
    except Exception:
        pass
    return {"neutral": 1.0}


def _blend(aw, key, base):
    """Archetype blend of one setting: sum_a w_a * BET_ARCH[a][key] (missing -> base)."""
    tot = 0.0
    for a, w in aw.items():
        tot += w * params.BET_ARCH.get(a, {}).get(key, base)
    return tot


class _Opp:
    """What the betting reads from the opponent model. Stats follow preflop._Reads: trusted only once the model
    reports >= PF_EXPLOIT_MIN_HANDS hands (the neutral stub reports 0, so the defaults apply)."""

    def __init__(self, opp):
        self.reads = preflop_mod._Reads(opp)
        self.known = self.reads.on
        self.ftb = self.reads.fold_to_bet
        # per-street fold-to-bet (the model shrinks each towards the aggregate, so thin street data falls back to
        # it on its own); untrusted stats -> the aggregate default for every street
        self.ftb_st = {st: (preflop_mod._stat(opp, "fold_to_bet_" + st, self.ftb) if self.known else self.ftb)
                       for st in STREETS}
        self.aw = _arch(opp)
        self.info = max(0.0, min(1.0, _blend(self.aw, "range_info", 1.0)))
        agg_mult = 1.0
        beta = float(params.POSTERIOR_BETA)
        toss = False
        mdf = 1.0
        if self.known:
            agg = preflop_mod._stat(opp, "aggression", params.BET_AGG_REF)
            agg_mult = (params.BET_AGG_REF / max(agg, 0.05)) ** 0.5
            agg_mult = min(params.BET_AGG_MULT_HI, max(params.BET_AGG_MULT_LO, agg_mult))
            tau = preflop_mod._stat(opp, "discard_tau", 0.9)        # share of max-S keeps (1/3 = random)
            lo, hi = params.BET_TAU_RAMP
            beta *= min(1.0, max(0.0, (tau - lo) / (hi - lo)))
            toss = preflop_mod._stat(opp, "toss_lowest", 0.0) >= params.BET_TOSS_LOWEST_ON
            mdf = min(1.0, max(params.BET_MDF_MULT_LO, preflop_mod._stat(opp, "mdf_tilt", 1.0)))
        self.beta = beta * self.info
        self.toss = toss and self.info > 0.5
        self.tilt_mult = agg_mult * max(0.0, _blend(self.aw, "tilt", 1.0)) * self.info * mdf
        # B7: an opponent who goes all-in often makes big bets with weaker hands -> damp the size amplification
        # (read from the first hand: a shrunk estimate that starts at its prior, where the damping is 0)
        lo, hi = params.BET_SIZE_DAMP_ALLIN
        allin = preflop_mod._stat(opp, "allin", params.OPP_FREQ["allin"][0])
        self.size_damp = 1.0 - min(1.0, max(0.0, (allin - lo) / (hi - lo)))
        self.call_station = max(0.0, min(1.0, _blend(self.aw, "call_station", 0.0)))
        self.bluff_mult = max(0.0, _blend(self.aw, "bluff", 1.0))
        self.semi_mult = max(0.0, _blend(self.aw, "semi", 1.0))
        self.size_mult = max(0.5, _blend(self.aw, "size_mult", 1.0))
        self.cbet = max(0.0, min(1.0, _blend(self.aw, "cbet", 0.0)))
        # river-bet calibration from their shown hands (shrunk to 0.5 = none; read from the first hand)
        self.river_k = pit_k(preflop_mod._stat(opp, "river_pit", 0.5))

    def value_th(self, street):
        return _blend(self.aw, "value_th", params.BET_VALUE_TH[street])

    def raise_th(self, street):
        return _blend(self.aw, "raise_th", params.BET_RAISE_TH[street])


def _actions(history):
    """{street: [their actions]}, the preflop sequence [(actor, action)], and whether we raised preflop."""
    by = {"preflop": [], "flop": [], "turn": [], "river": []}
    pre = []
    if isinstance(history, list):
        for h in history:
            if not isinstance(h, dict):
                continue
            st, actor, a = h.get("street"), h.get("actor"), h.get("action")
            if st == "preflop":
                pre.append((actor, a))
            if actor == "opp" and st in by:
                by[st].append(a)
    return by, pre


def _street_tilt(acts):
    g = 0.0
    for a in acts:
        if a == "raise":
            g += params.BET_TILT_RAISE
        elif a == "call":
            g += params.BET_TILT_CALL
        elif a == "check":
            g += params.BET_TILT_CHECK
    return max(-params.BET_TILT_MAX, min(params.BET_TILT_MAX, g))


def size_mult(x, allin=False, damp=1.0):
    """B7: how much more (or less) than a 2/3-pot bet one bet / raise of relative size x narrows their range.
    x = the chips we must call / the pot if we called. Bounded: [BET_SIZE_LO, BET_SIZE_HI] x BET_SIZE_ALLIN.
    damp in [0, 1] scales the amplification above 1 (an opponent who goes all-in often: big bets say less)."""
    x = max(0.0, x)
    m = (x / params.BET_SIZE_REF) ** params.BET_SIZE_EXP
    m = min(params.BET_SIZE_HI, max(params.BET_SIZE_LO, m))
    if allin:
        m *= params.BET_SIZE_ALLIN
    if m > 1.0:
        m = 1.0 + max(0.0, min(1.0, damp)) * (m - 1.0)
    return m


def _tilts(history, damp=1.0):
    """{street: gamma}: the size-aware tilt of their actions on each postflop street (B7), clipped at
    +-BET_TILT_MAX. Falls back to the size-blind _street_tilt when the history cannot be replayed."""
    got = replay.walk(history)
    if got is None:
        by, _ = _actions(history)
        return {st: _street_tilt(by[st]) for st in STREETS}
    g = {st: 0.0 for st in STREETS}
    for e in got[0]:
        st = e["street"]
        if e["actor"] != "opp" or st not in g:
            continue
        a = e["action"]
        if a == "raise":
            b = e["amount"] - e["bet_o"]
            pot = e["pot"] + e["to_call"]
            g[st] += params.BET_TILT_RAISE * size_mult(b / pot if pot > 0 else 1.0, e["allin"], damp)
        elif a == "call":
            g[st] += params.BET_TILT_CALL
        elif a == "check":
            g[st] += params.BET_TILT_CHECK
    return {st: max(-params.BET_TILT_MAX, min(params.BET_TILT_MAX, v)) for st, v in g.items()}


def _preflop_line(pre, reads):
    """(width, top): their preflop range = top `width` of all hands, minus (partly) the top `top` they would
    have raised. Raised first -> pfr; re-raised ours -> three_bet; raised twice -> 4-bet range; raised then called
    our re-raise -> pfr x BET_PRIOR_CALL3_FRAC; limped / called -> vpip minus the top; checked -> any hand."""
    opp_raises = 0
    we_raised_first = False
    we_raised = False
    called = False
    last_opp = None
    for actor, a in pre:
        if actor == "me" and a == "raise":
            we_raised = True
        elif actor == "opp":
            last_opp = a
            if a == "raise":
                if opp_raises == 0 and we_raised:
                    we_raised_first = True
                opp_raises += 1
            elif a == "call":
                called = True
    if opp_raises == 0:
        if called:
            return reads.vpip, (reads.three_bet if we_raised else reads.pfr)
        return 1.0, 0.0
    width = reads.three_bet if we_raised_first else reads.pfr
    if opp_raises >= 2:
        width = min(width, reads.fourbet_range())
    elif last_opp == "call":
        width *= params.BET_PRIOR_CALL3_FRAC
    return width, 0.0


def preflop_play(history, reads, info=1.0):
    """B7 prior: for each of the 1755 canon3 classes, the probability that a hand of that class took their
    preflop line (soft top-X% cut on the combination-weighted percentile). info in [0, 1] blends towards 1
    (uninformative; 0 for a random bot). Returns a list (all ones when the line says "any hand")."""
    _, pre = _actions(history)
    width, top = _preflop_line(pre, reads)
    if width >= 0.999 and top <= 0.0 or info <= 0.0:
        return [1.0] * len(_PCT)
    soft = params.BET_PRIOR_SOFT
    fl = params.BET_PRIOR_FLOOR
    with np.errstate(over="ignore"):
        w = fl + (1.0 - fl) / (1.0 + np.exp(-(_PCT - (1.0 - min(1.0, width))) / soft))
        if top > 0.0:
            w *= 1.0 - (1.0 - params.BET_PRIOR_TOP_KEEP) / (1.0 + np.exp(-(_PCT - (1.0 - top)) / soft))
    w = info * w + (1.0 - info)
    return [float(x) for x in w]


# ----------------------------------------------------------------------------------------------- range model
def _hand_cache(hand_state):
    key = (getattr(hand_state, "hand_id", None), tuple(getattr(hand_state, "hole3", ()) or ()))
    if _HC.get("key") != key:
        _HC.clear()
        _HC["key"] = key
    return _HC


def _flop_tilt(gamma):
    if gamma == 0.0:
        return None
    cap = params.BET_S_CAP
    return lambda s: math.exp(gamma * (s if s < cap else cap))


def _call_s(cs):
    mid, soft, fl = params.BET_CALL_S_MID, params.BET_CALL_S_SOFT, params.BET_CALL_FLOOR
    return lambda s: cs + (1.0 - cs) * (fl + (1.0 - fl) * _sig((s - mid) / soft))


def _call_u(u, cs):
    fl = params.BET_CALL_FLOOR
    with np.errstate(over="ignore"):
        c = fl + (1.0 - fl) / (1.0 + np.exp(-(u - params.BET_CALL_U_MID) / params.BET_CALL_U_SOFT))
    return cs + (1.0 - cs) * c


def _prior(hc, history, o):
    key = ("prior", tuple((h.get("actor"), h.get("action")) for h in history
                          if isinstance(h, dict) and h.get("street") == "preflop") if isinstance(history, list)
           else (), o.info)
    got = hc.get(key)
    if got is None:
        got = hc[key] = preflop_play(history, o.reads, o.info)
    return got


def _live(dead, board):
    """Bool array (1326): pairs with no card in dead | board."""
    ok = np.ones(N_PAIRS, dtype=bool)
    x = equity_mod._excluded(dead, [int(c) for c in board])
    for c in range(52):
        if x[c]:
            ok[_CARD_PAIRS[c]] = False
    return ok


def _strengths(w, board, ok, street):
    """(idx, v, u): live pair indices, eval7(pair + board) and the strength percentile within the range w
    (ties share their midpoint). On the turn, flush draws / open-enders below a straight are lifted to at least
    BET_U_FLUSH_DRAW / BET_U_OESD."""
    idx = np.nonzero(ok)[0]
    bd = tuple(int(c) for c in board)
    ev = eval7
    v = np.array([ev(PAIRS[i] + bd) for i in idx], dtype=np.int64)
    ww = w[idx]
    order = np.argsort(v, kind="stable")
    vs = v[order]
    cw = np.cumsum(ww[order])
    tot = cw[-1] if len(cw) else 0.0
    if tot <= 0:
        return idx, v, np.full(len(idx), 0.5)
    lo = np.searchsorted(vs, v, "left")
    hi = np.searchsorted(vs, v, "right")
    below = np.where(lo > 0, cw[np.maximum(lo - 1, 0)], 0.0)
    upto = cw[hi - 1]
    u = (below + upto) / (2.0 * tot)
    if street == "turn":
        u = np.maximum(u, _draw_lift(idx, v, bd))
    return idx, v, u


def _draw_lift(idx, v, bd):
    """Turn: BET_U_FLUSH_DRAW for a flush draw (4 to a suit), else BET_U_OESD for >= 2 straight-completing ranks,
    on pairs whose made hand is below a straight; 0 otherwise. Vectorised (the same draws as discard._draw_parts)."""
    a, b = _PA[idx], _PB[idx]
    sa, sb = a & 3, b & 3
    bs = np.zeros(4, dtype=np.int64)
    mask = 0
    for c in bd:
        bs[c & 3] += 1
        mask |= 1 << (c >> 2)
    same = (sa == sb).astype(np.int64)
    flush = np.maximum(bs[sa] + 1 + same, bs[sb] + 1 + same) == 4
    outs_tab = np.zeros((13, 13), dtype=np.int64)
    for r1 in range(13):
        for r2 in range(r1, 13):
            outs_tab[r1, r2] = outs_tab[r2, r1] = discard_mod._outs(mask | (1 << r1) | (1 << r2))
    oesd = outs_tab[a >> 2, b >> 2] >= 2
    below = (v >> 20) < 4
    return np.where(below & flush, params.BET_U_FLUSH_DRAW, np.where(below & oesd, params.BET_U_OESD, 0.0))


def _posterior(hc, req, hand_state, o, by):
    """Posterior over their kept pairs after the discard (03/D3) with the preflop prior and the flop tilt.
    Cached per hand on its inputs. Pairs touching a later board card are zeroed by the caller."""
    history = req.get("history") if isinstance(req.get("history"), list) else []
    board = list(getattr(hand_state, "board", []))
    flop = tuple(board[:3])
    od = getattr(hand_state, "opp_discard", None)
    dv = -1
    if is_valid(od):
        dv = parse(od)
    gamma = _tilts(history, o.size_damp)["flop"] * o.tilt_mult
    play = _prior(hc, history, o)
    key = ("post", flop, dv, gamma, o.beta, o.toss, id(play))
    w = hc.get(key)
    if w is None:
        prior = None if min(play) == 1.0 else np.array(play) * _MULT    # class masses (posterior divides by MULT)
        dead = bytearray(52)
        for c in getattr(hand_state, "hole3", []):
            dead[c] = 1
        w = discard_mod.posterior_after_discard(dv, flop, prior, o.beta, dead=dead, flop_action=_flop_tilt(gamma),
                                                toss_lowest=o.toss)
        hc[key] = w
    return w


def _range_for(req, hand_state, o, street):
    """(w, idx, v, u) on the current board: the posterior times the turn tilt (river: also the river tilt), live
    pairs only. Cached per hand and board / action signature."""
    hc = _hand_cache(hand_state)
    by, _ = _actions(req.get("history"))
    board = list(getattr(hand_state, "board", []))
    facing_river_bet = street == "river" and bool(by["river"]) and by["river"][-1] == "raise"
    k_pit = o.river_k if facing_river_bet else 0.0
    key = ("range", tuple(board), tuple(by["flop"]), tuple(by["turn"]), tuple(by["river"]), o.tilt_mult,
           o.call_station, o.size_damp, k_pit)
    got = hc.get(key)
    if got is not None:
        return got
    w = _posterior(hc, req, hand_state, o, by).copy()
    tl = _tilts(req.get("history"), o.size_damp)
    dead = getattr(hand_state, "dead", None)
    if street == "river" and len(board) >= 5:
        g = tl["turn"] * o.tilt_mult
        if g != 0.0:
            ok4 = _live(dead, board[:4])
            k4 = ("str", tuple(board[:4]), tuple(by["flop"]))
            s4 = hc.get(k4)
            if s4 is None:
                s4 = hc[k4] = _strengths(w, board[:4], ok4, "turn")
            idx4, _, u4 = s4
            w[idx4] *= np.exp(g * params.BET_U_SCALE * u4)
    ok = _live(dead, board)
    w[~ok] = 0.0
    idx, v, u = _strengths(w, board, ok, street)
    g = tl[street] * o.tilt_mult
    if g != 0.0:
        w[idx] *= np.exp(g * params.BET_U_SCALE * u)
        idx, v, u = _strengths(w, board, ok, street)
    if facing_river_bet:
        hc["pit_base"] = (idx, u)                 # the uncorrected model's percentiles (river_pit is measured here)
        if k_pit != 0.0:
            w[idx] *= np.exp(k_pit * u)
            idx, v, u = _strengths(w, board, ok, street)
    got = hc[key] = (w, idx, v, u)
    return got


def opp_range(req, hand_state, opp):
    """B7: their range on the turn / river as decide uses it: numpy (1326,) by pair_index, 0 on dead / board."""
    o = _Opp(opp)
    street = req.get("street") if req.get("street") in ("turn", "river") else "turn"
    return _range_for(req, hand_state, o, street)[0]


# ----------------------------------------------------------------------------------------------- equity
def _flop_equity(hc, req, hand_state, o, by, budget, cap, rng):
    history = req.get("history") if isinstance(req.get("history"), list) else []
    play = _prior(hc, history, o)
    uniform = min(play) == 1.0
    canon3 = equity_mod.canon3
    tw = None if uniform else (lambda t, f: play[canon3(t)])
    sw = _flop_tilt(_tilts(history, o.size_damp)["flop"] * o.tilt_mult)
    res = discard_mod.keep_equities(hand_state.hole3, hand_state.board[:3], hand_state.dead, budget, rng,
                                    triple_weight=tw, s_weight=sw, s_call=_call_s(o.call_station),
                                    max_samples=cap, min_samples=params.BET_FLOP_MIN_SAMPLES)
    if res is None:
        return None
    ec = res["best_call"] if res["best_call"] is not None else res["best"]
    return res["best"], ec, res["n"], "mc"


def _turn_river_equity(req, hand_state, o, street, budget, cap, rng, t_start):
    hero = tuple(hand_state.hole)
    board = tuple(hand_state.board)
    w, idx, v, u = _range_for(req, hand_state, o, street)
    if len(idx) == 0 or float(w[idx].sum()) <= 0.0:
        return None
    c = _call_u(u, o.call_station)
    ww = w[idx]
    hv = eval7(hero + board)
    if street == "river" or len(board) >= 5:
        res = np.where(v < hv, 1.0, np.where(v == hv, 0.5, 0.0))
        e = float((ww * res).sum() / ww.sum())
        wc = ww * c
        ec = float((wc * res).sum() / wc.sum()) if wc.sum() > 0 else e
        return e, ec, len(idx), "exact"
    # turn: current-hand equity is the fallback if no time is left for sampling
    left = budget - (_now() - t_start) * 1000.0
    if left < params.BET_MIN_EXTRA_MS:
        res = np.where(v < hv, 1.0, np.where(v == hv, 0.5, 0.0))
        e = float((ww * res).sum() / ww.sum())
        wc = ww * c
        return e, float((wc * res).sum() / wc.sum()), 0, "now"
    deadline = _now() + left / 1000.0
    dead = getattr(hand_state, "dead", None)
    x = equity_mod._excluded(dead, hero + board)
    full = np.zeros(N_PAIRS)
    full[idx] = ww
    pairs, _, cum, total = equity_mod._range(full, x)
    cmap = {PAIRS[i]: float(ci) for i, ci in zip(idx, c)}
    rest = [cc for cc in range(52) if not x[cc]]
    draw = equity_mod._drawer(pairs, cum, total, rest, 1, rng)
    ev = eval7
    now = _now
    hb = hero + board
    hcache = {}
    chk = max(1, params.BET_CHECK_EVERY)
    n = 0
    acc = accc = csum = 0.0
    while n < cap:
        for _ in range(min(chk, cap - n)):
            p, run = draw()
            h = hcache.get(run)
            if h is None:
                h = hcache[run] = ev(hb + run)
            ov = ev(p + board + run)
            r = 1.0 if h > ov else (0.5 if h == ov else 0.0)
            ci = cmap.get(p, 1.0)
            acc += r
            accc += ci * r
            csum += ci
            n += 1
        if now() >= deadline:
            break
    if n < params.BET_TURN_MIN_SAMPLES:
        res = np.where(v < hv, 1.0, np.where(v == hv, 0.5, 0.0))
        e = float((ww * res).sum() / ww.sum())
        wc = ww * c
        return e, float((wc * res).sum() / wc.sum()), 0, "now"
    return acc / n, (accc / csum if csum > 0 else acc / n), n, "mc"


def _static_equity(hand_state, street, o, by):
    """Panic tier / no samples: equity from a flop-score-like S of our hand (no sampling, no range work)."""
    board = tuple(hand_state.board)
    if street == "flop":
        hole = tuple(hand_state.hole3)
        s = max(discard_mod.flop_score((a, b), board[:3]) for a, b in ((hole[0], hole[1]), (hole[0], hole[2]),
                                                                        (hole[1], hole[2])))
    else:
        hole = tuple(hand_state.hole[:2])
        cards = hole + board
        v = eval7(cards)
        cat = v >> 20
        s = cat + (v & 0xFFFFF) / float(1 << 20)
        if street == "turn" and cat < 4:
            s += discard_mod._draw_parts(cards)
        if street == "river" and len(board) == 5 and (eval7(board) >> 20) >= cat:
            s -= params.BET_STATIC_BOARD_DROP
    e = float(np.interp(s, params.BET_STATIC_S, params.BET_STATIC_E))
    n_agg = sum(1 for a in by.get(street, []) if a == "raise")
    e -= 0.05 * n_agg * min(1.0, o.tilt_mult)
    e = max(0.0, min(1.0, e))
    ec = e - params.BET_STATIC_CALL_DROP * (1.0 - o.call_station)
    return e, max(0.0, ec), 0, "static"


# ----------------------------------------------------------------------------------------------- board / draws
def _wet(board):
    suits = [0, 0, 0, 0]
    ranks = set()
    for c in board:
        suits[c & 3] += 1
        ranks.add(c >> 2)
    if max(suits) >= (3 if len(board) >= 5 else 2):
        return True
    rs = ranks | ({-1} if 12 in ranks else set())
    for lo in range(-1, 9):
        if sum(1 for r in rs if lo <= r <= lo + 4) >= 3:
            return True
    return False


def _has_draw(hand_state, street):
    """A flush draw or an open-ender (made hand below a straight): flop over any keep, turn on our two cards."""
    try:
        board = tuple(hand_state.board)
        if street == "flop":
            h = tuple(hand_state.hole3)
            keeps = ((h[0], h[1]), (h[0], h[2]), (h[1], h[2]))
            return max(discard_mod.draw_potential(k, board[:3]) for k in keeps) >= params.S_OPEN_ENDED
        if street == "turn":
            cards = tuple(hand_state.hole[:2]) + board
            if eval7(cards) >> 20 >= 4:
                return False
            return discard_mod._draw_parts(cards) >= params.S_OPEN_ENDED
    except Exception:
        pass
    return False


# ----------------------------------------------------------------------------------------------- decide
def _act(a):
    return {"action": a}


def _safe(req):
    """Exception path: check if legal, else call a price of at most 1/4, else fold."""
    try:
        legal = req.get("legal_actions") or []
        if "check" in legal or not legal:
            return _act("check")
        to_call = _finite(req.get("to_call"), 0.0)
        pot = _finite(req.get("pot"), 0.0)
        if "call" in legal and pot + to_call > 0 and to_call / (pot + to_call) <= 0.25:
            return _act("call")
        return _act("fold")
    except Exception:
        return _act("check")


def decide(req, hand_state, opp, clock, rng=None):
    """Postflop action intent for a flop / turn / river action_request. Never raises; the caller passes the
    intent through legal.make_legal. Returns None when our hole cards are unknown (e.g. new_hand was missed), so
    the caller applies its own fallback."""
    t0 = _now()
    try:
        return _decide(req, hand_state, opp, clock, rng if rng is not None else _RNG, t0)
    except Exception:
        log_exc("betting.decide")
        _record(str(req.get("street")), (_now() - t0) * 1000.0, "error", "error")
        return _safe(req)


def _decide(req, hand_state, opp, clock, rng, t0):
    street = req.get("street")
    if street not in STREETS:
        return _safe(req)
    s = preflop_mod._Spot(req)
    if not s.legal:
        return _act("check")
    hole = getattr(hand_state, "hole3" if street == "flop" else "hole", None) or []
    if len(hole) != (3 if street == "flop" else 2) or len(getattr(hand_state, "board", [])) < 3:
        return None                     # our cards are unknown (state lost): the caller's v0 fallback decides
    o = _Opp(opp)
    by, pre = _actions(req.get("history"))
    ip = preflop_mod._is_button(req, hand_state)
    tier = "normal"
    budget = 0.0
    if clock is not None:
        try:
            tier = clock.tier()
            budget = max(0.0, float(clock.budget_ms(street)))
        except Exception:
            tier, budget = "panic", 0.0
    hc = _hand_cache(hand_state)
    sig = (street, tuple(hand_state.board), tuple(hand_state.hole), tuple(by[street]), len(by["flop"]),
           len(by["turn"]), o.tilt_mult, o.call_station, o.info)
    res = None
    path = "static"
    if budget > 0.0:
        cached = hc.get(("eq", sig))
        if cached is not None:
            res = cached
            path = "cache"
        else:
            again = hc.get(("street_done", street))
            frac = params.BET_RECALC_FRAC if again else 1.0
            b = budget * frac
            if street == "flop":
                if len(hand_state.hole3) == 3 and len(hand_state.board) >= 3:
                    res = _flop_equity(hc, req, hand_state, o, by, b,
                                       max(1, int(params.BET_FLOP_MAX_SAMPLES * frac)), rng)
            elif len(hand_state.hole) == 2 and len(hand_state.board) >= 4:
                res = _turn_river_equity(req, hand_state, o, street, b,
                                         max(1, int(params.BET_TURN_MAX_SAMPLES * frac)), rng, t0)
            if res is not None:
                hc[("eq", sig)] = res
                hc[("street_done", street)] = True
                path = res[3]
    if res is None:
        res = _static_equity(hand_state, street, o, by)
    e, ec, n, _ = res
    intent, why = _choose(s, street, e, ec, o, ip, req, hand_state, rng, pre)
    if street == "river" and s.to_call > 0 and intent.get("action") == "call" and path in ("exact", "cache"):
        try:                                   # river-bet calibration: their shown hand is scored at hand_result
            hand_state.river_pit = hc.get("pit_base")
        except Exception:
            pass
    ms = (_now() - t0) * 1000.0
    _record(street, ms, tier, path)
    px = s.to_call / (s.pot + s.to_call) if s.to_call > 0 else 0.0
    log(f"bet {street[0]} E={e:.3f} Ec={ec:.3f} px={px:.2f} {path} n={n} {ms:.1f}ms {why} "
        f"-> {intent.get('action')} {intent.get('amount', '')}")
    return intent


def _value_size(ec, e, street, s, o, wet):
    f_mult = o.size_mult
    if ec >= params.BET_BIG_TH:
        f = (params.BET_F_BIG if wet else params.BET_F_STD) * f_mult
    elif ec >= params.BET_THIN_TH:
        f = params.BET_F_STD
    else:
        f = params.BET_F_THIN if f_mult <= 1.0 else params.BET_F_STD
    if f_mult > 1.0 and e >= params.BET_NUTS_TH:
        return s.hi
    spr = params.BET_SHOVE_SPR if ec >= params.BET_SHOVE_SPR_TH else None
    return bet_amount(s, f, spr)


def _raise_size(ec, s, o, raises_left):
    f = params.BET_F_BIG if ec >= params.BET_BIG_TH else params.BET_F_STD
    spr = params.BET_SHOVE_SPR if ec >= params.BET_SHOVE_SPR_TH else None
    if ec >= params.BET_BIG_TH:
        f *= o.size_mult
    if raises_left == 1:                     # B4: the last raise of the street cannot be re-raised: size it big
        f = max(f, params.BET_LAST_RAISE_F)
        spr = params.BET_LAST_RAISE_SPR
    return bet_amount(s, f, spr)


def _choose(s, street, e, ec, o, ip, req, hand_state, rng, pre):
    """(intent, reason) from the equities and the spot (B1-B6, B8b hooks)."""
    rl = req.get("raises_left")
    raises_left = rl if isinstance(rl, int) and not isinstance(rl, bool) else 4
    can_raise = s.can_raise and s.opp_stack > 0
    board = list(getattr(hand_state, "board", []))
    ftb = o.ftb_st.get(street, o.ftb)               # their fold-to-bet on this street (aggregate if untrusted)
    if s.to_call <= 0:
        if can_raise and ec >= o.value_th(street):
            return {"action": "raise", "amount": _value_size(ec, e, street, s, o, _wet(board))}, "value"
        if can_raise and street != "river" and e >= params.BET_SEMI_EQ_LO and _has_draw(hand_state, street):
            if rng.random() < semi_prob(ftb, o.known, o.semi_mult):
                return {"action": "raise", "amount": bet_amount(s, params.BET_F_STD)}, "semi"
        if can_raise and street == "river" and e < params.BET_AIR_TH:
            amt = bet_amount(s, params.BET_F_STD)
            if rng.random() < bluff_prob(amt - s.my_bet, s.pot, ftb, o.known, o.bluff_mult):
                return {"action": "raise", "amount": amt}, "bluff"
        if can_raise and street == "flop" and o.cbet > 0 and any(a == "me" and x == "raise" for a, x in pre):
            if rng.random() < o.cbet:
                return {"action": "raise", "amount": bet_amount(s, params.BET_NIT_CBET_F)}, "cbet"
        return _act("check" if "check" in s.legal else "call"), "check"
    no_future = street == "river" or s.to_call >= s.my_stack or s.opp_stack <= 0
    if can_raise and raises_left > 0 and ec >= o.raise_th(street):
        return {"action": "raise", "amount": _raise_size(ec, s, o, raises_left)}, "raise"
    price = s.to_call / (s.pot + s.to_call)
    if (can_raise and raises_left > 1 and street != "river" and e >= params.BET_SEMI_EQ_LO
            and price <= params.BET_SEMI_MAX_PRICE and _has_draw(hand_state, street)):
        if rng.random() < semi_prob(ftb, o.known, o.semi_mult) * params.BET_SEMI_RAISE_MULT:
            return {"action": "raise", "amount": bet_amount(s, params.BET_F_STD)}, "semi-raise"
    if "call" in s.legal and calls(e, s.to_call, s.pot, street, ip, no_future):
        return _act("call"), "call"
    return _act("fold" if "fold" in s.legal else "check"), "fold"
