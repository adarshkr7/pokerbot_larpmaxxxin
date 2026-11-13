"""The discard (strategies/03_discard.md: D1, D3, D5).

Public:
  flop_score(pair, flop) -> float                     the static flop score S (D3), one fixed scale
  draw_potential(pair, flop) -> float                 flush + straight draw part of S (D1 tie-break)
  opp_discard_policy(triple3, flop) -> int            simulated opponent: keeps its max-S pair, returns the discard
  choose_discard(hole3, flop, opp_model, dead, budget_ms, rng, *, betting_possible=True, max_samples=None) -> int
  keep_equities(hole3, flop, dead, budget_ms, rng, *, triple_weight=None, s_weight=None, s_call=None,
                max_samples=None, min_samples=None) -> dict | None   per-keep equities on shared samples (05 flop)
  posterior_after_discard(d_v, flop, prior=None, beta=None, *, dead=None, flop_action=None, toss_lowest=False,
                          eta=None) -> numpy array (1326,) indexed by cards.pair_index

Card ids 0..51 (rank * 4 + suit, suits s h d c). Pure apart from the module rng used when rng is None, the
evaluator's memo tables and the `last_info` diagnostic. `_now` is a module attribute so tests can fake the clock.
"""
import math
import numbers
import random
import time

import numpy as np

import params
from cards import PAIRS, pair_index
from equity import _CANON, _excluded, canon3
from evaluator import eval7
from log import log

_now = time.perf_counter
_RNG = random.Random()
_FRAC = 1.0 / (1 << 20)
_OUTS = {}              # 13-bit rank mask -> number of ranks that would complete a straight
last_info = {}          # diagnostic of the last choose_discard: path, n, eq, discard


# ----------------------------------------------------------------------------------------------- flop score S
def _straight(mask):
    """True iff the 13-bit rank mask holds a straight (wheel included)."""
    return bool(mask & (mask >> 1) & (mask >> 2) & (mask >> 3) & (mask >> 4)) or mask & 0x100F == 0x100F


def _outs(mask):
    n = _OUTS.get(mask)
    if n is None:
        n = 0
        for r in range(13):
            if not mask >> r & 1 and _straight(mask | (1 << r)):
                n += 1
        _OUTS[mask] = n
    return n


def _draw_parts(cards):
    """(flush+straight draw bonus) of 5 cards whose made hand is below a straight."""
    sc = [0, 0, 0, 0]
    mask = 0
    for c in cards:
        sc[c & 3] += 1
        mask |= 1 << (c >> 2)
    d = params.S_FLUSH_DRAW if max(sc) == 4 else 0.0
    n = _outs(mask)
    if n >= 2:
        d += params.S_OPEN_ENDED          # open-ended (or double gutshot): two completing ranks
    elif n == 1:
        d += params.S_GUTSHOT
    return d


def flop_score(pair, flop):
    """S = category + kicker_fraction + draw bonus (03/D3), v = eval7(pair + flop).

    Draw bonus only when the made hand is below a straight: flush draw (4 to a suit), open-ended straight draw
    (>= 2 ranks complete a straight; a double gutshot counts), gutshot (1 rank), and S_OVERCARD per hole card
    ranked above the top flop card."""
    a, b = pair
    f0, f1, f2 = flop
    cards = (a, b, f0, f1, f2)
    v = eval7(cards)
    cat = v >> 20
    s = cat + (v & 0xFFFFF) * _FRAC
    if cat >= 4:
        return s
    top = max(f0 >> 2, f1 >> 2, f2 >> 2)
    return s + _draw_parts(cards) + params.S_OVERCARD * ((a >> 2 > top) + (b >> 2 > top))


def draw_potential(pair, flop):
    """The flush/straight-draw part of S (0 when the made hand is a straight or better)."""
    cards = (pair[0], pair[1], flop[0], flop[1], flop[2])
    if eval7(cards) >> 20 >= 4:
        return 0.0
    return _draw_parts(cards)


def _keep_order(triple3):
    """[(discard, keep_pair)] for a triple, ordered by discard id ascending (the tie order everywhere)."""
    t0, t1, t2 = sorted(triple3)
    return [(t0, (t1, t2)), (t1, (t0, t2)), (t2, (t0, t1))]


def opp_discard_policy(triple3, flop):
    """The simulated opponent's discard: keep the max-S pair; ties discard the lowest card id
    (lowest rank, then s < h < d < c). Uses only its own three cards and the flop."""
    best_d, best_s = None, -1.0
    for d, keep in _keep_order(triple3):
        s = flop_score(keep, flop)
        if s > best_s:
            best_d, best_s = d, s
    return best_d


# ----------------------------------------------------------------------------------------------- D1 / D5
def _norm_budget(b):
    if isinstance(b, bool) or not isinstance(b, numbers.Real):
        return 0.0
    b = float(b)
    if b != b or b <= 0.0:
        return 0.0
    return b


def _valid_cards(xs, n):
    try:
        out = tuple(int(c.__index__()) for c in xs)
    except Exception:
        return None
    if len(out) != n or len(set(out)) != n or any(c < 0 or c > 51 for c in out):
        return None
    return out


def _model_fns(opp_model):
    """(weight_fn, discard_fn) from opp_model: None, a dict or an object with optional `triple_weight(triple, flop)
    -> float` (D2 importance weight) and `discard_policy(triple, flop) -> card id` (their discard rule)."""
    if opp_model is None:
        return None, None
    get = opp_model.get if isinstance(opp_model, dict) else (lambda k: getattr(opp_model, k, None))
    w, d = get("triple_weight"), get("discard_policy")
    return (w if callable(w) else None), (d if callable(d) else None)


def _simulate(keeps, flop, rest, deadline, cap, rng, weight_fn, discard_fn):
    """Mean showdown value of each keep over shared samples (opponent triple + runout), to the deadline or cap.
    Returns (eqs, n). The opponent's triple is uniform (times weight_fn if given) over `rest`; it keeps the
    pair its policy picks; the runout is 2 more cards from `rest`."""
    eqs, _, n = _simulate_core(keeps, flop, rest, deadline, cap, rng, weight_fn, discard_fn)
    return eqs, n


def _simulate_core(keeps, flop, rest, deadline, cap, rng, weight_fn, discard_fn, s_weight=None, s_call=None):
    """The one sampling loop behind _simulate and keep_equities. Returns (eqs, eqs_call, n).

    s_weight(S_best) multiplies the sample weight and s_call(S_best) is a second (calling) weight, where S_best is
    the max flop score S over the opponent triple's three pairs (their hand during flop betting). eqs_call is the
    mean over the samples weighted by w * s_call (None when s_call is None or its weights sum to 0). With neither
    given, the random draws and results are exactly those of the plain loop."""
    ev = eval7
    now = _now
    f0, f1, f2 = flop
    k0, k1, k2 = (tuple(k) + flop for k in keeps)
    scache = {}
    fs = flop_score
    sample = rng.sample
    chk = max(1, params.DISCARD_CHECK_EVERY)
    need_s = s_weight is not None or s_call is not None
    a0 = a1 = a2 = 0.0
    c0 = c1 = c2 = 0.0
    wsum = csum = 0.0
    n = 0
    while n < cap:
        for _ in range(min(chk, cap - n)):
            t0, t1, t2, r1, r2 = sample(rest, 5)
            run = (r1, r2)
            w = 1.0
            if weight_fn is not None:
                w = _weight(weight_fn, (t0, t1, t2), flop)
            if discard_fn is not None:
                x, y = _opp_keep(discard_fn, (t0, t1, t2), flop)
            if discard_fn is None or need_s:
                if t0 > t1:
                    t0, t1 = t1, t0
                if t1 > t2:
                    t1, t2 = t2, t1
                    if t0 > t1:
                        t0, t1 = t1, t0
                s12 = scache.get(t1 * 64 + t2)
                if s12 is None:
                    s12 = scache[t1 * 64 + t2] = fs((t1, t2), flop)
                s02 = scache.get(t0 * 64 + t2)
                if s02 is None:
                    s02 = scache[t0 * 64 + t2] = fs((t0, t2), flop)
                s01 = scache.get(t0 * 64 + t1)
                if s01 is None:
                    s01 = scache[t0 * 64 + t1] = fs((t0, t1), flop)
                if discard_fn is None:
                    if s12 >= s02 and s12 >= s01:
                        x, y = t1, t2
                    elif s02 >= s01:
                        x, y = t0, t2
                    else:
                        x, y = t0, t1
            c = 1.0
            if need_s:
                sb = s12 if s12 >= s02 and s12 >= s01 else (s02 if s02 >= s01 else s01)
                if s_weight is not None:
                    w *= _sval(s_weight, sb)
                if s_call is not None:
                    c = _sval(s_call, sb)
            ov = ev((x, y, f0, f1, f2, r1, r2))
            if w:
                h = ev(k0 + run)
                v0 = 1.0 if h > ov else (0.5 if h == ov else 0.0)
                h = ev(k1 + run)
                v1 = 1.0 if h > ov else (0.5 if h == ov else 0.0)
                h = ev(k2 + run)
                v2 = 1.0 if h > ov else (0.5 if h == ov else 0.0)
                a0 += w * v0
                a1 += w * v1
                a2 += w * v2
                wsum += w
                if s_call is not None:
                    wc = w * c
                    c0 += wc * v0
                    c1 += wc * v1
                    c2 += wc * v2
                    csum += wc
            n += 1
        if now() >= deadline:
            break
    if wsum <= 0.0:
        return None, None, n
    calls = (c0 / csum, c1 / csum, c2 / csum) if csum > 0.0 else None
    return (a0 / wsum, a1 / wsum, a2 / wsum), calls, n


def _sval(fn, s):
    try:
        v = float(fn(s))
    except Exception:
        return 0.0
    return v if (v == v and 0.0 <= v < math.inf) else 0.0


def _weight(fn, triple, flop):
    try:
        w = float(fn(triple, flop))
    except Exception:
        return 0.0
    return w if (w == w and 0.0 < w < math.inf) else 0.0


def _opp_keep(fn, triple, flop):
    """The pair kept when the opponent discards fn(triple, flop); an invalid answer -> the default policy."""
    try:
        d = fn(triple, flop).__index__()
        if d in triple:
            x, y = [c for c in triple if c != d]
            return x, y
    except Exception:
        pass
    d = opp_discard_policy(triple, flop)
    x, y = [c for c in triple if c != d]
    return x, y


def _static_choice(hole, flop):
    """Discard of the max-S keep (ties discard the lowest id)."""
    best_d, best_s = None, -1.0
    for d, keep in _keep_order(hole):
        s = flop_score(keep, flop)
        if s > best_s:
            best_d, best_s = d, s
    return best_d


def choose_discard(hole3, flop, opp_model, dead, budget_ms, rng, *, betting_possible=True, max_samples=None):
    """The card id (one of hole3) to discard, by equity-max over the three keeps (03/D1, D5).

    hole3: our 3 card ids; flop: the 3 flop ids; dead: HandState.dead (flags) or ids or None (hole3 and flop
    are always excluded); opp_model: None, or a dict / object with optional `triple_weight(triple, flop)` and
    `discard_policy(triple, flop)` (D2 plug-ins; None -> uniform triples, opp_discard_policy). rng: a
    random.Random or None (module rng). All three keeps are scored on the same samples (common random
    numbers); averages first, max after. betting_possible: when True and the best two keeps are within
    DISCARD_TIE_MARGIN, prefer the one with more draw potential; when False (all-in) the plain max and the
    larger sample cap. Budget <= 0 (panic), fewer than DISCARD_MIN_SAMPLES samples in the budget, or any internal
    failure -> the discard of the max-S keep. Never raises."""
    global last_info
    t_start = _now()
    hole = flop_t = None
    static = None
    try:
        hole = _valid_cards(hole3, 3)
        flop_t = _valid_cards(flop, 3)
        if hole is None or flop_t is None or set(hole) & set(flop_t):
            last_info = {"path": "invalid", "n": 0}
            return _last_resort(hole3)
        static = _static_choice(hole, flop_t)
        b = _norm_budget(budget_ms)
        if b == 0.0:
            last_info = {"path": "static", "n": 0, "discard": static}
            return static
        deadline = t_start + b / 1000.0
        if max_samples is None:
            cap = params.DISCARD_MAX_SAMPLES if betting_possible else params.DISCARD_ALLIN_MAX_SAMPLES
        else:
            cap = max(1, int(max_samples))
        if rng is None:
            rng = _RNG
        order = _keep_order(hole)
        keeps = [k for _, k in order]
        x = _excluded(dead, hole + flop_t)
        rest = [c for c in range(52) if not x[c]]
        if len(rest) < 5:
            last_info = {"path": "static", "n": 0, "discard": static}
            return static
        weight_fn, discard_fn = _model_fns(opp_model)
        eqs, n = _simulate(keeps, flop_t, rest, deadline, cap, rng, weight_fn, discard_fn)
        if eqs is None or n < min(cap, params.DISCARD_MIN_SAMPLES):
            last_info = {"path": "static", "n": n, "discard": static}
            return static
        ranked = sorted(range(3), key=lambda i: (-eqs[i], i))
        best = ranked[0]
        if betting_possible and eqs[best] - eqs[ranked[1]] <= params.DISCARD_TIE_MARGIN:
            alt = ranked[1]
            if draw_potential(keeps[alt], flop_t) > draw_potential(keeps[best], flop_t):
                best = alt
        d = order[best][0]
        last_info = {"path": "mc", "n": n, "eq": tuple(eqs[i] for i in range(3)), "discards": tuple(o[0] for o in order),
                     "discard": d, "ms": (_now() - t_start) * 1000.0}
        log("discard", n, round(last_info["ms"], 1), [round(e, 3) for e in eqs], d)
        return d
    except Exception:
        last_info = {"path": "error", "n": 0}
        if static is not None:
            return static
        try:
            if hole is not None and flop_t is not None:
                return _static_choice(hole, flop_t)
        except Exception:
            pass
        return _last_resort(hole3)


def keep_equities(hole3, flop, dead, budget_ms, rng, *, triple_weight=None, s_weight=None, s_call=None,
                  max_samples=None, min_samples=None):
    """Equity of each of our three keeps on the flop, before the discard (05: flop betting uses the best keep).

    The D1 sampler of choose_discard, shared samples for all three keeps: the opponent is dealt a triple from the
    unseen cards (weighted by triple_weight(triple, flop) and s_weight(S_best)) and keeps its max-S pair; the
    runout is 2 more cards. s_call(S_best) optionally weights a second average (their calling range).
    Returns None on invalid input, a budget <= 0 or fewer than min(cap, min_samples) samples; else a dict
      {"eq": (e0, e1, e2), "eq_call": (c0, c1, c2) or None, "keeps": [(a, b), ...], "discards": [d, ...], "n": n,
       "best": max(eq), "best_call": max(eq_call) or None}
    in discard-id order (as choose_discard's last_info). The best keep's equity is the max of the per-keep
    averages, never a per-sample max. Never raises."""
    try:
        hole = _valid_cards(hole3, 3)
        flop_t = _valid_cards(flop, 3)
        if hole is None or flop_t is None or set(hole) & set(flop_t):
            return None
        b = _norm_budget(budget_ms)
        if b == 0.0:
            return None
        t_start = _now()
        cap = params.DISCARD_MAX_SAMPLES if max_samples is None else max(1, int(max_samples))
        lo = params.DISCARD_MIN_SAMPLES if min_samples is None else max(1, int(min_samples))
        if rng is None:
            rng = _RNG
        order = _keep_order(hole)
        keeps = [k for _, k in order]
        x = _excluded(dead, hole + flop_t)
        rest = [c for c in range(52) if not x[c]]
        if len(rest) < 5:
            return None
        eqs, calls, n = _simulate_core(keeps, flop_t, rest, t_start + b / 1000.0, cap, rng, triple_weight, None,
                                       s_weight, s_call)
        if eqs is None or n < min(cap, lo):
            return None
        return {"eq": tuple(eqs), "eq_call": tuple(calls) if calls is not None else None, "keeps": keeps,
                "discards": [o[0] for o in order], "n": n, "best": max(eqs),
                "best_call": max(calls) if calls is not None else None}
    except Exception:
        return None


def _last_resort(hole3):
    """Lowest valid id among hole3 (= the engine's default discard), else hole3[0], else 0. Never raises."""
    try:
        ids = [int(c.__index__()) for c in hole3]
        valid = [c for c in ids if 0 <= c < 52]
        if valid:
            return min(valid)
        return ids[0] if ids else 0
    except Exception:
        return 0


# ----------------------------------------------------------------------------------------------- D3 posterior
def _mult_of_key(key):
    if key[0] == 2:
        return 4.0                       # trips: C(4, 3)
    if key[0] == 1:
        return 12.0                      # pair + kicker: 6 pair suits x 2 kicker suits (matching or not)
    pat = key[4]
    return 4.0 if pat == 0 else (24.0 if pat == 4 else 12.0)


MULT = [0.0] * len(_CANON)               # MULT[canon3 class] = number of physical triples (4, 12 or 24)
for _k, _i in _CANON.items():
    MULT[_i] = _mult_of_key(_k)


def _finite_beta(beta):
    if beta is None:
        return float(params.POSTERIOR_BETA)
    try:
        b = float(beta)
    except Exception:
        return float(params.POSTERIOR_BETA)
    if b != b:
        return float(params.POSTERIOR_BETA)
    return max(-1e6, min(1e6, b))


def _nonneg(x):
    try:
        f = float(x)
    except Exception:
        return 0.0
    return f if (f == f and 0.0 < f < math.inf) else 0.0


def posterior_after_discard(d_v, flop, prior=None, beta=None, *, dead=None, flop_action=None, toss_lowest=False,
                            eta=None):
    """Weights over the opponent's kept pairs {c1, c2} after they exposed the discard d_v (03/D3).

    Returns a numpy float64 array of length 1326 indexed by cards.pair_index (the format equity.equity accepts as
    opp_weights): 0 on every pair touching dead | board | d_v, and on the M valid pairs W = 0.98 q + 0.02 / M
    (POSTERIOR_SMOOTH), where q is the normalised product (uniform if its sum is 0 or not finite) of
      prior:       None (uniform); a length-1755 sequence of class masses P_preflop(C | action) indexed by
                   equity.canon3, divided by MULT[C] for one physical triple; or a callable(triple) -> weight of
                   that physical triple (e.g. play(C));
      flop_action: None (1) or a callable(S_best) -> P(their flop action | S_best(T)), S_best = max S of T's pairs;
      L_discard:   softmax exp(beta S(c1,c2)) / sum over T's three pairs (beta None -> POSTERIOR_BETA; 0 -> 1/3);
                   or, with toss_lowest=True, (1 - eta) [d_v is T's lowest id] + eta / 3 (eta None -> POSTERIOR_ETA).
    flop: the board; S uses its first 3 cards and every board card is excluded. dead: HandState.dead (flags) or
    ids or None. Never raises: on failure, uniform over the pairs not in dead | board | d_v."""
    out = np.zeros(1326)
    try:
        bd = [int(c) for c in flop]
        fl = tuple(bd[:3])
        x = _excluded(dead, bd)
        dv = d_v.__index__() if not isinstance(d_v, bool) and hasattr(d_v, "__index__") else -1
        if 0 <= dv < 52:
            x[dv] = 1
        live = [c for c in range(52) if not x[c]]
        idx, c1s, c2s = [], [], []
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                idx.append(pair_index(a, b))
                c1s.append(a)
                c2s.append(b)
        M = len(idx)
        if M == 0:
            return out
        idx = np.array(idx)
        if not (0 <= dv < 52) or len(fl) != 3:
            out[idx] = 1.0 / M
            return out
        s_pair = np.array([flop_score((a, b), fl) for a, b in zip(c1s, c2s)])
        s_with = {c: flop_score((c, dv), fl) for c in live}
        s1 = np.array([s_with[a] for a in c1s])
        s2 = np.array([s_with[b] for b in c2s])
        raw = np.ones(M)
        if prior is not None:
            if callable(prior):
                pw = [_nonneg(prior((a, b, dv))) for a, b in zip(c1s, c2s)]
            else:
                seq = prior.tolist() if hasattr(prior, "tolist") else list(prior)
                if len(seq) == len(MULT):
                    pw = [_nonneg(seq[k]) / MULT[k] for k in (canon3((a, b, dv)) for a, b in zip(c1s, c2s))]
                else:
                    pw = [1.0] * M          # malformed prior: ignored (uniform), the discard is still read
            raw *= np.array(pw)
        if flop_action is not None:
            s_best = np.maximum(s_pair, np.maximum(s1, s2))
            raw *= np.array([_nonneg(flop_action(float(s))) for s in s_best])
        if toss_lowest:
            e = params.POSTERIOR_ETA if eta is None else _nonneg(eta)
            e = min(1.0, e)
            consistent = (np.array(c1s) > dv) & (np.array(c2s) > dv)
            raw *= np.where(consistent, 1.0 - e + e / 3.0, e / 3.0)
        else:
            bt = _finite_beta(beta)
            z0, z1, z2 = bt * s_pair, bt * s1, bt * s2
            m = np.maximum(z0, np.maximum(z1, z2))
            with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                e0, e1, e2 = np.exp(z0 - m), np.exp(z1 - m), np.exp(z2 - m)
                raw *= e0 / (e0 + e1 + e2)
        raw = np.where(np.isfinite(raw) & (raw > 0.0), raw, 0.0)
        tot = float(raw.sum())
        q = raw / tot if (tot > 0.0 and math.isfinite(tot)) else np.full(M, 1.0 / M)
        eps = params.POSTERIOR_SMOOTH
        out[idx] = (1.0 - eps) * q + eps / M
        return out
    except Exception:
        try:
            out[:] = 0.0
            x = _excluded(dead, [int(c) for c in flop])
            dv = d_v if isinstance(d_v, int) and 0 <= d_v < 52 else None
            if dv is not None:
                x[dv] = 1
            ids = [i for i, (a, b) in enumerate(PAIRS) if not x[a] and not x[b]]
            if ids:
                out[ids] = 1.0 / len(ids)
        except Exception:
            pass
        return out
