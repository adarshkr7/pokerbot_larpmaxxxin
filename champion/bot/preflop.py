"""Preflop play (strategies/04_preflop.md: P1 tiers, P2 ranges, P3 sizing, P4 exploit hooks).

Public:
  strength(hole3) -> float            equity vs a random 3-card hand (table; P1 heuristic if the table is missing)
  percentile(hole3) -> float          share of the 22,100 physical hands ranked weaker (0 worst .. ~1 best)
  equity_vs_top(hole3, width) -> float  equity vs the opponent's top-`width` share of all hands (width in (0, 1])
  heuristic(hole3) -> float           the P1 score on the same 0-1 (equity-like) scale; pure
  decide(req, hand_state, opp, rng=None) -> dict   action intent {"action": ..., "amount": ...} for a preflop request

Card ids 0..51 (rank * 4 + suit) or strings like "As". "Top X%" always means percentile >= 1 - X, with the
percentile weighted by physical combinations (4 per trips class, 12 or 24 otherwise; 22,100 in all).

The data file bot/data/preflop.json is read once at import (path relative to this file). Anything wrong with it
falls back to the heuristic for every class; nothing here raises at import or from the public functions.
"""
import json
import math
import os
import random

import params
from cards import parse
from equity import _CANON, canon3
from log import log_exc, warn

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "preflop.json")
N_CLASSES = 1755
N_HANDS = 22100
_RNG = random.Random()

KEY = [None] * N_CLASSES                 # KEY[class] = the equity._canon_key tuple of that class
for _k, _i in _CANON.items():
    KEY[_i] = _k


def _mult(key):
    if key[0] == 2:
        return 4
    if key[0] == 1:
        return 12
    return 4 if key[4] == 0 else (24 if key[4] == 4 else 12)


MULT = [_mult(k) for k in KEY]           # physical triples per class (sum 22,100)


# ----------------------------------------------------------------------------------------------- P1 heuristic
# A linear score per hand shape, on the scale of the equity vs a random hand: coefficients fitted once by least
# squares (weighted by combinations) to the offline table, RMSE about 0.008 (no pair), 0.007 (pairs), 0.003
# (trips). The data overrules two P1 guesses: the pair's third card barely matters once suits are counted, and a
# kicker within 2 ranks of the pair scores slightly lower, not higher.
# Ranks r are 0..12 (2..A) and enter as r / 12.
_H_TRIPS = (0.315, 0.451)                # base, rank: 222 ~ 0.32, AAA ~ 0.77 (one own set out is dead)
_H_PAIR = (0.394, 0.370, 0.046, 0.002, -0.010)   # base, pair rank, kicker rank, kicker suited to the pair, connected
_H_HIGH = (0.245, 0.179, 0.140, 0.039,   # base, r1, r2, r3 (r1 > r2 > r3): a low third card is a dangler
           0.022, 0.016, 0.013,          # two suited: hi-mid, hi-lo, mid-lo
           0.016,                        # monotone (three suited: below the best two-suited version)
           0.005, 0.004, 0.002)          # all three in a 5-rank window, hi-mid within 2, mid-lo within 2


def _heuristic_key(key):
    if key[0] == 2:
        b, w = _H_TRIPS
        return b + w * key[1] / 12.0
    if key[0] == 1:
        _, p, k, s = key
        b, wp, wk, ws, wc = _H_PAIR
        return b + wp * p / 12.0 + wk * k / 12.0 + ws * s + wc * (abs(p - k) <= 2)
    _, r1, r2, r3, pat = key
    (b, w1, w2, w3, s12, s13, s23, mono, win5, c12, c23) = _H_HIGH
    v = b + w1 * r1 / 12.0 + w2 * r2 / 12.0 + w3 * r3 / 12.0
    if pat == 0:
        v += mono
    elif pat == 1:
        v += s12
    elif pat == 2:
        v += s13
    elif pat == 3:
        v += s23
    wheel = r1 == 12 and r2 <= 3                       # A with two wheel cards
    if r1 - r3 <= 4 or (wheel and r2 - (-1) <= 4):
        v += win5
    if r1 - r2 <= 2:
        v += c12
    if r2 - r3 <= 2:
        v += c23
    return v


def heuristic(hole3):
    """P1: a pure score of 3 distinct cards on the equity-vs-random scale (about 0.3 .. 0.8). 0.5 on bad input."""
    try:
        return min(0.99, max(0.01, _heuristic_key(KEY[_cls(hole3)])))
    except Exception:
        return 0.5


# ----------------------------------------------------------------------------------------------- tables
def _valid_vec(v):
    if not isinstance(v, list) or len(v) != N_CLASSES:
        return None
    out = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return None
        x = float(x)
        if not (0.0 < x < 1.0):
            return None
        out.append(x)
    return out


def _load(path):
    """(eq, widths, vs_top, source). eq: 1755 floats; vs_top: list of 1755-float lists per width, or None."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        eq = _valid_vec(data.get("equity"))
        if eq is None:
            raise ValueError("bad 'equity' vector")
        widths, vs = None, None
        try:
            w = data.get("header", {}).get("range_widths")
            v = data.get("vs_top")
            if (isinstance(w, list) and isinstance(v, list) and len(w) == len(v) and w
                    and all(isinstance(x, (int, float)) and not isinstance(x, bool) and 0 < x < 1 for x in w)
                    and all(a < b for a, b in zip(w, w[1:]))):
                vv = [_valid_vec(x) for x in v]
                if all(x is not None for x in vv):
                    widths, vs = [float(x) for x in w], vv
        except Exception:
            widths, vs = None, None
        return eq, widths, vs, "table"
    except Exception as e:
        warn(f"preflop: table unavailable ({type(e).__name__}: {str(e)[:80]}); using the P1 heuristic")
        return [min(0.99, max(0.01, _heuristic_key(k))) for k in KEY], None, None, "heuristic"


def _percentiles(eq):
    """pct[k] = combination share of the classes ranked below k by (eq, class index): equal equities are ordered by
    class index, so every "top X%" cut is exact to within one class (<= 24 of 22,100 hands)."""
    pct = [0.0] * N_CLASSES
    below = 0
    for k in sorted(range(N_CLASSES), key=lambda k: (eq[k], k)):
        pct[k] = below / N_HANDS
        below += MULT[k]
    return pct


def _install(path):
    global EQ, PCT, WIDTHS, VS_TOP, SOURCE
    eq, widths, vs, src = _load(path)
    EQ, WIDTHS, VS_TOP, SOURCE = eq, widths, vs, src
    PCT = _percentiles(eq)


EQ = PCT = WIDTHS = VS_TOP = SOURCE = None
try:
    _install(DATA_PATH)
except Exception:                         # never raise at import: heuristic everything
    log_exc("preflop import")
    EQ = [0.5] * N_CLASSES
    PCT = [0.5] * N_CLASSES
    WIDTHS = VS_TOP = None
    SOURCE = "neutral"


def _cls(hole3):
    """canon3 class of 3 distinct valid cards (ids or strings); raises on anything else (callers catch)."""
    cards = [parse(c) if isinstance(c, str) else c.__index__() for c in hole3]
    if len(cards) != 3 or len(set(cards)) != 3 or not all(0 <= c < 52 for c in cards):
        raise ValueError("need 3 distinct cards")
    return canon3(cards)


def strength(hole3):
    """Equity of the 3-card hand vs a uniformly random 3-card hand (both discarding by the static flop score)."""
    try:
        return EQ[_cls(hole3)]
    except Exception:
        return 0.5


def percentile(hole3):
    """Share of all 22,100 physical hands ranked below this one by `strength` (ties broken by class index)."""
    try:
        return PCT[_cls(hole3)]
    except Exception:
        return 0.5


def _eq_vs_cls(k, width):
    """Equity of class k vs the top-`width` range. width >= 1 -> vs random. Interpolated linearly in the width
    between the table's grid points; below the narrowest width the narrowest column is used. Without the range
    columns: an approximation that shrinks the vs-random edge and subtracts the range's strength."""
    eqr = EQ[k]
    if not (width < 1.0):
        return eqr
    width = max(0.0, float(width))
    if VS_TOP is not None:
        xs = WIDTHS + [1.0]
        ys = [col[k] for col in VS_TOP] + [eqr]
        if width <= xs[0]:
            return ys[0]
        for i in range(1, len(xs)):
            if width <= xs[i]:
                t = (width - xs[i - 1]) / (xs[i] - xs[i - 1])
                return ys[i - 1] + t * (ys[i] - ys[i - 1])
        return eqr
    # fallback: vs a top-w range our equity drops roughly linearly in (1 - w), more for weaker hands
    w = max(0.05, width)
    return max(0.05, min(0.95, eqr - (1.0 - w) * (params.PF_FALLBACK_RANGE_DROP + 0.25 * (0.6 - eqr))))


def equity_vs_top(hole3, width):
    try:
        return _eq_vs_cls(_cls(hole3), width)
    except Exception:
        return 0.5


# ----------------------------------------------------------------------------------------------- decide helpers
def _num(x, default):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return default
    x = float(x)
    return x if math.isfinite(x) else default


def _stat(opp, name, default):
    """opp.stat(name) as a finite float, else default (a missing model or a raising stat never breaks play)."""
    try:
        v = opp.stat(name)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return default
        v = float(v)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def _arch_w(opp):
    """opp.archetype_weights() normalised; unknown or malformed -> {"neutral": 1}."""
    try:
        out = {}
        for k, v in dict(opp.archetype_weights()).items():
            v = _num(v, 0.0)
            if v > 0:
                out[str(k)] = v
        tot = sum(out.values())
        if tot > 0:
            return {k: v / tot for k, v in out.items()}
    except Exception:
        pass
    return {"neutral": 1.0}


def _ramp(x, a, b):
    t = (x - a) / (b - a)
    return 0.0 if t <= 0.0 else (1.0 if t >= 1.0 else t)


class _Reads:
    """The opponent stats the preflop exploits read (04/P4, 06/M1 names). Frequency stats are trusted only once the
    model reports at least PF_EXPLOIT_MIN_HANDS observed hands (the defaults below apply before). Two exceptions
    (06/M4: the model's estimates are shrunk and bounded, so they scale with evidence on their own):
      shove      read from the first hand: the Beta estimate starts at its prior and needs several shoves to move;
      archetype  weights (maniac / station) are soft and start neutral; every override is blended by its weight.
    """

    def __init__(self, opp):
        self.hands = _stat(opp, "hands", 0.0)
        on = self.hands >= params.PF_EXPLOIT_MIN_HANDS
        self.on = on
        self.vpip = _stat(opp, "vpip", 0.65) if on else 0.65
        self.pfr = _stat(opp, "pfr", 0.35) if on else 0.35
        self.three_bet = _stat(opp, "three_bet", 0.12) if on else 0.12
        self.shove = min(1.0, max(0.0, _stat(opp, "shove", 0.12)))
        self.fold_to_steal = _stat(opp, "fold_to_steal", 0.40) if on else 0.40
        self.fold_to_bet = _stat(opp, "fold_to_bet", 0.42) if on else 0.42
        aw = _arch_w(opp)
        self.w_maniac = aw.get("maniac", 0.0)
        self.w_station = aw.get("station", 0.0)
        self.w_steal = _ramp(self.fold_to_steal, *params.PF_STEAL_FOLD_RAMP) if on else 0.0
        self.w_wide3 = _ramp(self.three_bet, *params.PF_WIDE_3BET_RAMP) if on else 0.0

    def shove_range(self):
        """Estimated width of their shoving range. Unknown opponent: a strong range (PF_SHOVE_RANGE); widened to
        their estimated shove frequency (a bot that shoves a share s of its chances shoves about its top s)."""
        return min(1.0, max(params.PF_SHOVE_RANGE, self.shove * params.PF_SHOVE_WIDEN))

    def fourbet_range(self):
        """Their 4-bet range: PF_FOURBET_RANGE, widened only by shove evidence above the shove prior (so the
        baseline is unchanged until they have shoved more than an average player)."""
        p0 = params.OPP_FREQ["shove"][0]
        excess = max(0.0, self.shove - p0) / (1.0 - p0)
        return min(1.0, max(params.PF_FOURBET_RANGE, excess * params.PF_SHOVE_WIDEN))


def _interp(curve, x):
    """Piecewise-linear interpolation through ((x0, y0), (x1, y1), ...) (x ascending), clamped at both ends."""
    if x <= curve[0][0]:
        return curve[0][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x <= x1:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return curve[-1][1]


def _top(p, share, rng):
    """True if a hand at percentile p is in the top `share` of hands. Within PF_MIX_BAND of the cut the answer is
    randomised, with a probability rising linearly across the band (light, bounded mixing)."""
    cut = 1.0 - share
    band = params.PF_MIX_BAND
    if share <= 0.0:
        return False
    if share >= 1.0:
        return True
    if band <= 0.0 or p >= cut + band:
        return p >= cut
    if p < cut - band:
        return False
    return rng.random() < (p - (cut - band)) / (2.0 * band)


def _is_button(req, hand_state):
    seat = getattr(hand_state, "seat", None)
    if seat in ("button", "big_blind"):
        return seat == "button"
    hist = req.get("history")
    if isinstance(hist, list):
        for h in hist:
            if isinstance(h, dict) and h.get("street") == "preflop" and h.get("actor") in ("me", "opp"):
                return h["actor"] == "me"          # the button acts first preflop
        if not hist:
            return True                              # nobody has acted: the asked player is the button
    return _num(req.get("my_bet"), 0) < _num(req.get("opp_bet"), 0) and _num(req.get("my_bet"), 0) <= 1


def _raises_made(req):
    """Voluntary preflop raises so far (the big blind is not one): 3 - raises_left, else counted in history."""
    rl = req.get("raises_left")
    if isinstance(rl, int) and not isinstance(rl, bool) and 0 <= rl <= 3:
        return 3 - rl
    hist = req.get("history")
    n = 0
    if isinstance(hist, list):
        for h in hist:
            if isinstance(h, dict) and h.get("street", "preflop") == "preflop" and h.get("action") == "raise":
                n += 1
    return min(3, n)


def _low_trips(k):
    key = KEY[k]
    return key[0] == 2 and key[1] <= params.PF_LOW_TRIPS_MAX_RANK


class _Spot:
    """The request's numbers, read leniently (a partial or odd request still yields something usable)."""

    def __init__(self, req):
        legal = req.get("legal_actions")
        self.legal = [a for a in legal if isinstance(a, str)] if isinstance(legal, list) else []
        self.my_bet = _num(req.get("my_bet"), 0.0)
        self.opp_bet = _num(req.get("opp_bet"), 0.0)
        self.to_call = _num(req.get("to_call"), max(0.0, self.opp_bet - self.my_bet))
        self.my_stack = _num(req.get("my_stack"), 200.0)
        self.opp_stack = _num(req.get("opp_stack"), 200.0)
        self.pot = _num(req.get("pot"), self.my_bet + self.opp_bet)
        self.lo = req.get("min_raise")
        self.hi = req.get("max_raise")
        ok = (isinstance(self.lo, int) and isinstance(self.hi, int) and not isinstance(self.lo, bool)
              and not isinstance(self.hi, bool) and self.lo <= self.hi)
        self.can_raise = "raise" in self.legal and ok
        self.start_stack = self.my_bet + self.my_stack          # our chips at the start of this street (preflop: 200)


def _act(a):
    return {"action": a}


def _call_or_check(s):
    return _act("call" if "call" in s.legal else "check")


def _fold_or_check(s):
    return _act("check" if "check" in s.legal else "fold")


def _raise(s, target):
    """Raise to `target` (int, clamped to [min_raise, max_raise]); all-in when the raise would commit more than
    PF_SHOVE_COMMIT_FRAC of our stack (P3). Not legal -> call/check."""
    if not s.can_raise:
        return _call_or_check(s)
    t = int(round(target))
    if t > params.PF_SHOVE_COMMIT_FRAC * s.start_stack:
        t = s.hi
    return {"action": "raise", "amount": int(min(max(t, s.lo), s.hi))}


def _shove(s):
    if not s.can_raise:
        return _call_or_check(s)
    return {"action": "raise", "amount": int(s.hi)}


# ----------------------------------------------------------------------------------------------- decide
def decide(req, hand_state=None, opp=None, rng=None):
    """Preflop action intent for an action_request. Never raises: on any internal error the reply is check if
    legal, else call when the price is at most a big blind, else fold. The caller passes it through make_legal."""
    try:
        return _decide(req, hand_state, opp, rng if rng is not None else _RNG)
    except Exception:
        log_exc("preflop.decide")
        return _safe(req)


def _safe(req):
    try:
        s = _Spot(req)
        if "check" in s.legal or not s.legal:
            return _act("check")
        if s.to_call <= params.PF_BB and "call" in s.legal:
            return _act("call")
        return _act("fold")
    except Exception:
        return _act("check")


def _decide(req, hand_state, opp, rng):
    hole = list(getattr(hand_state, "hole3", None) or [])
    if len(hole) != 3:
        return _safe(req)
    k = _cls(hole)
    p = PCT[k]
    s = _Spot(req)
    reads = _Reads(opp)
    button = _is_button(req, hand_state)
    made = _raises_made(req)

    if s.to_call <= 0:                                   # big blind after a limp (or any free option)
        return _vs_limp(s, p, reads, rng)
    big = (s.to_call >= s.my_stack or s.opp_stack <= 0
           or s.to_call >= params.PF_BIG_CALL_FRAC * s.my_stack)
    if made == 0 and not big:                            # the button's first decision: complete 1 or raise
        return _open(s, p, reads, rng)
    if big:
        width = reads.fourbet_range() if made >= 3 else reads.shove_range()
        return _all_in(s, k, p, width, reads, rng)
    price = s.to_call / (s.pot + s.to_call)
    if made == 1:
        return _vs_open(s, k, p, price, reads, rng)
    if made == 2:
        return _vs_3bet(s, k, p, price, reads, rng)
    # facing the 4-bet: the cap is reached, call or fold by realised equity vs their 4-bet range (P2)
    e = _eq_vs_cls(k, reads.fourbet_range())
    r = params.PF_R_IP if button else params.PF_R_OOP
    if r * e >= price + params.PF_CALL_MARGIN:
        return _call_or_check(s)
    return _fold_or_check(s)


def _open(s, p, reads, rng):
    """P2 open / limp / fold, with the P4 overrides blended by weight: vs a station value-raise the top 45% (4 BB)
    and complete the rest; vs a maniac open the top 45%, no limps; vs a big blind that over-folds (fold-to-steal
    ramp) open everything as a min-raise."""
    bb = params.PF_BB
    wm, ws = reads.w_maniac, reads.w_station
    wb = max(0.0, 1.0 - wm - ws)
    raise_pct = (wb * params.PF_OPEN_PCT + ws * params.PF_STATION_VALUE_PCT + wm * params.PF_OPEN_PCT_VS_MANIAC)
    limp_pct = wb * params.PF_LIMP_PCT + ws * (1.0 - params.PF_STATION_VALUE_PCT)
    size = (1.0 - ws) * params.PF_OPEN_BB + ws * params.PF_OPEN_BB_VS_STATION
    st = reads.w_steal
    if st > 0.0:
        raise_pct += st * (1.0 - raise_pct)
        size += st * (params.PF_STEAL_TO_BB - size)
    if _top(p, raise_pct, rng):
        return _raise(s, size * bb)
    if _top(p, raise_pct + limp_pct, rng):
        return _call_or_check(s)
    return _fold_or_check(s)


def _vs_limp(s, p, reads, rng):
    pct = params.PF_ISO_PCT + reads.w_station * (params.PF_ISO_PCT_VS_STATION - params.PF_ISO_PCT)
    if _top(p, pct, rng):
        return _raise(s, params.PF_ISO_BB * params.PF_BB)
    return _act("check" if "check" in s.legal else "call")


def _vs_open(s, k, p, price, reads, rng):
    defend = _interp(params.PF_DEFEND_CURVE, price)
    three = params.PF_THREEBET_PCT
    defend += reads.w_maniac * params.PF_MANIAC_DEFEND_BONUS
    three += reads.w_maniac * params.PF_MANIAC_DEFEND_BONUS
    three = min(three, defend)
    if _top(p, three, rng):
        target = params.PF_THREEBET_MULT * s.opp_bet
        if not (_low_trips(k) and target > params.PF_SHOVE_COMMIT_FRAC * s.start_stack):
            return _raise(s, target)
    if _top(p, defend, rng):
        return _call_or_check(s)
    return _fold_or_check(s)


def _vs_3bet(s, k, p, price, reads, rng):
    cont = _interp(params.PF_CONT3_CURVE, price)
    cont += reads.w_wide3 * params.PF_WIDE_3BET_CONT_BONUS
    four = min(params.PF_FOURBET_PCT, cont)
    if _top(p, four, rng) and not _low_trips(k):        # never 4-bet (shove) 222-999 (P1 traps)
        return _raise(s, params.PF_FOURBET_MULT * s.opp_bet)
    if _top(p, cont, rng):
        return _call_or_check(s)
    return _fold_or_check(s)


def allin_price(s):
    """Break-even equity when all the effective stack goes in: (eff - my_bet) / (2 * eff) (P4: 49.5% for the big
    blind facing an open shove, 48.5% for the button after opening to 6)."""
    eff = min(s.my_bet + s.my_stack, s.opp_bet + s.opp_stack)
    if eff <= 0:
        return 0.5
    return max(0.0, (eff - s.my_bet) / (2.0 * eff))


def _all_in(s, k, p, width, reads, rng):
    """A call that commits the stack (or most of it): equity vs their estimated shoving / 4-bet range against the
    all-in price. A top-of-range hand re-shoves when a raise is still legal and they are not all-in already."""
    e = _eq_vs_cls(k, width)
    if (s.can_raise and s.opp_stack > 0 and p >= 1.0 - params.PF_VALUE_SHOVE_PCT and not _low_trips(k)):
        return _shove(s)
    if e >= allin_price(s) + params.PF_CALL_MARGIN:
        return _call_or_check(s)
    return _fold_or_check(s)
