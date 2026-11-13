"""Opponent model (strategies/06_opponent_modelling.md: M1 statistics with priors, M2 archetypes, M4 safety rails).

Fed once per hand from `hand_result` (its history is complete even when we folded); never from action requests,
so nothing is counted twice. Every count (numerator and denominator alike) is multiplied by
lam = 0.5 ** (1 / OPP_HALF_LIFE) before a hand is added, so an opponent that changes style is tracked.

stat(name) serves (shrunk, bounded estimates; unknown names -> 0.0):
  hands          hands observed (raw count, not forgotten)
  vpip           hands with a preflop call or raise / hands where they had a preflop decision
                 (the big blind checking its option does not count)                              prior 0.65, N0 12
  pfr            hands with a preflop raise / the same opportunities                              prior 0.35, N0 12
  three_bet      re-raised our first preflop raise (the first voluntary raise of the hand) /
                 times they answered it with a raise legal                                       prior 0.12, N0 10
  shove          raised to max_raise preflop / hands where they had a legal preflop raise          prior 0.12, N0 4
  fold_to_steal  folded directly facing our first button raise / times they answered it         prior 0.40, N0 10
  fold_to_bet    postflop folds directly facing our bet or raise / times they faced one           prior 0.42, N0 12
  fold_to_bet_flop / _turn / _river   the same per street, shrunk (N0 8) towards fold_to_bet
  agg_freq       postflop (bets + raises) / (bets + raises + calls + checks)                      prior 0.30, N0 12
  aggression     postflop aggression factor (bets + raises + 1.5 k) / (calls + k), k = 15
  allin          hands with an all-in raise (any street) / hands they acted in                     prior 0.08, N0 10
  size_corr      Pearson r over showdowns of log(1 + their largest postflop bet / pot) vs their final hand
                 strength (category + kicker), shrunk n r / (n + 8); 0 with < 2 showdowns or zero variance
  discard_tau    showdowns where their kept pair was the max-S pair of kept + discard / showdowns  prior 0.90, N0 6
  toss_rate      showdowns where they discarded their lowest card (engine default rule)          prior 0.60, N0 6
  toss_lowest    the raw toss rate once >= OPP_TOSS_MIN_N showdowns are counted, else 0
  showdowns      showdowns counted (forgotten)
  mdf_tilt       07/G2 multiplier (BET_MDF_MULT_LO .. 1) on how strongly their bets narrow their range

archetype_weights() -> {station, nit, random, maniac, neutral} >= 0, summing to 1, computed only through
self.stat(...) (so a test double that overrides stat() gets consistent weights). Everything starts neutral.
Nothing here raises out of a public method.
"""
import math

import params
from cards import is_valid, parse
from discard import flop_score
from evaluator import eval7
from log import log, log_exc
from replay import walk

_ST = ("flop", "turn", "river")


def ramp(x, a, b):
    """clip((x - a) / (b - a), 0, 1); with a > b the ramp falls from 1 (x <= b) to 0 (x >= a)."""
    if a == b:
        return 1.0 if x >= a else 0.0
    t = (x - a) / (b - a)
    return 0.0 if t <= 0.0 else (1.0 if t >= 1.0 else t)


def shrink(k, n, prior, n0):
    """Beta-prior shrinkage of a binomial frequency: (k + n0 * prior) / (n + n0)."""
    return (k + n0 * prior) / (n + n0)


def aggression_factor(agg, calls, prior=None, k=None):
    """(agg + prior k) / (calls + k): never divides by zero; prior at no data."""
    prior = params.OPP_AF_PRIOR if prior is None else prior
    k = params.OPP_AF_K if k is None else k
    return (agg + prior * k) / (calls + k)


def corr(sw, sx, sy, sxx, syy, sxy, n0=None):
    """Weighted Pearson r from sums, shrunk as n r / (n + n0); 0 with n < 2 or zero variance in x or y."""
    n0 = params.OPP_CORR_N0 if n0 is None else n0
    if sw < 2.0 - 1e-9:
        return 0.0
    vx = sxx / sw - (sx / sw) ** 2
    vy = syy / sw - (sy / sw) ** 2
    if vx <= 1e-12 or vy <= 1e-12:
        return 0.0
    r = (sxy / sw - (sx / sw) * (sy / sw)) / math.sqrt(vx * vy)
    r = max(-1.0, min(1.0, r))
    return sw * r / (sw + n0)


def _strength(cards7):
    v = eval7(cards7)
    return (v >> 20) + (v & 0xFFFFF) / float(1 << 20)


def hand_observations(msg):
    """The per-hand increments of one hand_result: ({name: (k, n)}, extras) or None if the history is unusable.
    extras: af (agg, calls), mdf [(folded, mdf)], show (tau_hit, toss_hit, x, y) or None. Pure."""
    got = walk(msg.get("history"))
    if got is None:
        return None
    ev, me_btn = got
    obs = {}

    def add(name, k, n=1.0):
        a = obs.get(name)
        obs[name] = (float(k), float(n)) if a is None else (a[0] + k, a[1] + n)

    pre = [e for e in ev if e["street"] == "preflop"]
    opp_pre = [e for e in pre if e["actor"] == "opp"]
    if opp_pre:
        add("vpip", any(e["action"] in ("call", "raise") for e in opp_pre))
        add("pfr", any(e["action"] == "raise" for e in opp_pre))
        if any(e["raise_legal"] for e in opp_pre):
            add("shove", any(e["action"] == "raise" and e["allin"] for e in opp_pre))
    # our first preflop raise, if it was the first voluntary raise of the hand: their direct answer
    for i, e in enumerate(pre):
        if e["action"] == "raise":
            if e["actor"] == "me" and i + 1 < len(pre) and pre[i + 1]["actor"] == "opp":
                ans = pre[i + 1]
                if ans["raise_legal"]:
                    add("three_bet", ans["action"] == "raise")
                if me_btn and i == 0:                       # the button's first action was this raise: a steal
                    add("fold_to_steal", ans["action"] == "fold")
            break
    agg = calls = checks = 0
    for e in ev:
        if e["actor"] != "opp" or e["street"] == "preflop":
            continue
        if e["to_call"] > 0 and e["aggr"] == "me":
            f = e["action"] == "fold"
            add("fold_to_bet", f)
            add("fold_to_bet_" + e["street"], f)
        if e["action"] == "raise":
            agg += 1
        elif e["action"] == "call":
            calls += 1
        elif e["action"] == "check":
            checks += 1
    if agg + calls + checks:
        add("agg_freq", agg, agg + calls + checks)
    if any(e["actor"] == "opp" for e in ev):
        add("allin", any(e["actor"] == "opp" and e["action"] == "raise" and e["allin"] for e in ev))
    # 07/G2: our answer to their opening bet of each postflop street
    mdf = []
    for i, e in enumerate(ev):
        if (e["street"] != "preflop" and e["actor"] == "opp" and e["action"] == "raise" and e["aggr"] is None
                and i + 1 < len(ev) and ev[i + 1]["actor"] == "me" and ev[i + 1]["street"] == e["street"]):
            b = e["amount"] - e["bet_a"]
            p = e["pot"]
            if b > 0 and p > 0:
                mdf.append((ev[i + 1]["action"] == "fold", p / (p + b)))
    # biggest postflop bet / raise by them, as a share of the pot if it were called
    x = 0.0
    for e in ev:
        if e["actor"] == "opp" and e["action"] == "raise" and e["street"] != "preflop":
            b = e["amount"] - e["bet_o"]
            p = e["pot"] + e["to_call"]
            if p > 0 and b > 0:
                x = max(x, b / p)
    show = _showdown(msg, math.log1p(x))
    return obs, {"af": (agg, calls), "mdf": mdf, "show": show}


def _showdown(msg, x):
    """(tau_hit, toss_hit, x, y) for a showdown with their kept pair, discard and a full board; else None."""
    if msg.get("result") != "showdown":
        return None
    kept, disc, board = msg.get("opp_hole_cards"), msg.get("opp_discard"), msg.get("board")
    if not (isinstance(kept, list) and len(kept) == 2 and isinstance(board, list) and len(board) == 5
            and is_valid(disc) and all(is_valid(c) for c in kept) and all(is_valid(c) for c in board)):
        return None
    k = [parse(c) for c in kept]
    d = parse(disc)
    b = [parse(c) for c in board]
    if len(set(k + [d] + b)) != 8:
        return None
    flop = tuple(b[:3])
    s_keep = flop_score(tuple(k), flop)
    s_max = max(s_keep, flop_score((k[0], d), flop), flop_score((k[1], d), flop))
    tau_hit = s_keep >= s_max - 1e-12
    toss_hit = d < k[0] and d < k[1]              # card id order = rank, then s < h < d < c (engine default)
    return tau_hit, toss_hit, x, _strength(tuple(k + b))


class OppModel:
    """The live opponent model (06). A fresh instance is neutral: hands 0, every stat at its prior."""

    def __init__(self, half_life=None):
        h = params.OPP_HALF_LIFE if half_life is None else float(half_life)
        self._lam = 0.5 ** (1.0 / h) if h > 0 else 1.0
        self._k = {}
        self._n = {}
        self._af = [0.0, 0.0]
        self._cs = [0.0] * 6                       # w, sx, sy, sxx, syy, sxy
        self._mdf = [0.0, 0.0, 0.0]                # bets, our folds, sum of MDF
        self._hands = 0
        self._aw = None

    # ------------------------------------------------------------------ observation
    def observe_hand(self, msg, seat=None):
        """Update from one hand_result. Malformed input is skipped (nothing counted); never raises."""
        try:
            if not isinstance(msg, dict):
                return
            got = hand_observations(msg)
            if got is None:
                return
            obs, ex = got
            lam = self._lam
            for d in (self._k, self._n):
                for key in d:
                    d[key] *= lam
            self._af = [v * lam for v in self._af]
            self._cs = [v * lam for v in self._cs]
            self._mdf = [v * lam for v in self._mdf]
            for name, (k, n) in obs.items():
                self._k[name] = self._k.get(name, 0.0) + k
                self._n[name] = self._n.get(name, 0.0) + n
            self._af[0] += ex["af"][0]
            self._af[1] += ex["af"][1]
            for folded, m in ex["mdf"]:
                self._mdf[0] += 1.0
                self._mdf[1] += 1.0 if folded else 0.0
                self._mdf[2] += m
            sh = ex["show"]
            if sh is not None:
                tau_hit, toss_hit, x, y = sh
                for name, hit in (("discard_tau", tau_hit), ("toss_rate", toss_hit)):
                    self._k[name] = self._k.get(name, 0.0) + (1.0 if hit else 0.0)
                    self._n[name] = self._n.get(name, 0.0) + 1.0
                c = self._cs
                c[0] += 1.0
                c[1] += x
                c[2] += y
                c[3] += x * x
                c[4] += y * y
                c[5] += x * y
            self._hands += 1
            self._aw = None
            if params.OPP_LOG_EVERY and self._hands % params.OPP_LOG_EVERY == 0:
                self._log()
        except Exception:
            log_exc("opponent.observe_hand")

    def observe_showdown(self, msg, seat=None):
        self.observe_hand(msg, seat)

    def observe_action(self, *args, **kwargs):
        """Kept for the interface: actions are read once per hand from hand_result (no double counting)."""
        return None

    # ------------------------------------------------------------------ queries
    def stat(self, name):
        try:
            v = self._stat(name)
            return v if isinstance(v, float) and math.isfinite(v) else 0.0
        except Exception:
            return 0.0

    def _stat(self, name):
        k = getattr(self, "_k", None)
        n = getattr(self, "_n", None)
        if k is None or n is None:                  # a subclass that skipped __init__: the priors
            k, n = {}, {}
        if name == "hands":
            return float(getattr(self, "_hands", 0))
        if name in params.OPP_FREQ:
            prior, n0 = params.OPP_FREQ[name]
            return shrink(k.get(name, 0.0), n.get(name, 0.0), prior, n0)
        if name.startswith("fold_to_bet_") and name[12:] in _ST:
            overall = self._stat("fold_to_bet")
            return shrink(k.get(name, 0.0), n.get(name, 0.0), overall, params.OPP_STREET_N0)
        if name == "aggression":
            af = getattr(self, "_af", None) or [0.0, 0.0]
            return aggression_factor(af[0], af[1])
        if name == "size_corr":
            cs = getattr(self, "_cs", None) or [0.0] * 6
            return corr(*cs)
        if name == "showdowns":
            return float(n.get("discard_tau", 0.0))
        if name == "toss_lowest":
            nn = n.get("toss_rate", 0.0)
            return k.get("toss_rate", 0.0) / nn if nn >= params.OPP_TOSS_MIN_N - 1e-9 else 0.0
        if name == "mdf_tilt":
            return self._mdf_tilt()
        return 0.0

    def _mdf_tilt(self):
        """07/G2: if we fold to their opening bets clearly more than 1 - MDF and they are aggressive, their bets
        should narrow their range less. Bounded: BET_MDF_MULT_LO .. 1; 1 without evidence."""
        m = getattr(self, "_mdf", None)
        if not m or m[0] <= 0:
            return 1.0
        bets, folds, msum = m
        excess = folds / bets - (1.0 - msum / bets)
        conf = ramp(bets, *params.OPP_MDF_MIN_BETS)
        aw = self.archetype_weights()
        aggro = max(aw.get("maniac", 0.0), ramp(self.stat("aggression"), *params.OPP_AGGRO_AF))
        cut = (1.0 - params.BET_MDF_MULT_LO) * ramp(excess, *params.OPP_MDF_EXCESS) * conf * aggro
        return 1.0 - cut

    def archetype_weights(self):
        try:
            cached = getattr(self, "_aw", None)
            if cached is not None:
                return dict(cached)
            aw = self._weights()
            if hasattr(self, "_aw"):
                self._aw = aw
            return dict(aw)
        except Exception:
            return {"neutral": 1.0}

    def _weights(self):
        st = self.stat
        p = params
        ftb = st("fold_to_bet")
        sc = {
            "maniac": max(ramp(st("pfr"), *p.OPP_MANIAC_PFR), ramp(st("shove"), *p.OPP_MANIAC_SHOVE)),
            "station": min(ramp(ftb, *p.OPP_STATION_FTB), ramp(st("aggression"), *p.OPP_STATION_AF)),
            "nit": ramp(st("vpip"), *p.OPP_NIT_VPIP) * (0.5 + 0.5 * ramp(ftb, *p.OPP_NIT_FTB)),
            "random": (ramp(st("discard_tau"), *p.OPP_RANDOM_TAU) * ramp(st("toss_rate"), *p.OPP_RANDOM_TOSS)
                       * ramp(st("size_corr"), *p.OPP_RANDOM_CORR) * ramp(st("showdowns"), *p.OPP_RANDOM_SHOWDOWNS)),
        }
        tot = sum(sc.values())
        if tot > 1.0:
            out = {a: v / tot for a, v in sc.items()}
            out["neutral"] = 0.0
        else:
            out = dict(sc)
            out["neutral"] = 1.0 - tot
        return out

    def range_weights(self, *args, **kwargs):
        return None

    def _log(self):
        try:
            aw = self.archetype_weights()
            names = ("vpip", "pfr", "three_bet", "shove", "fold_to_steal", "fold_to_bet", "aggression", "discard_tau",
                     "toss_lowest", "size_corr", "mdf_tilt")
            log(f"opp h={self._hands} " + " ".join(f"{a[:3]}={w:.2f}" for a, w in aw.items() if w > 0.005) + " | "
                + " ".join(f"{s}={self.stat(s):.2f}" for s in names))
        except Exception:
            pass
