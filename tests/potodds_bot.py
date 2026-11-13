"""Test-only opponent: a pot-odds equity bot. Estimates its equity against a random hand by a small Monte Carlo
(flop: the best of its three keeps); bets 2/3 pot with strong hands, raises very strong ones, calls a bet when its
equity beats the price plus a margin and folds otherwise. Preflop: a simple strength score (raise the top, call
cheap prices with the middle, fold the rest). Keeps the pair of cards that makes its best hand with the flop.
Stdlib only, seeded from the hand id (deterministic per deal)."""
import json
import random
import sys
from itertools import combinations

RANKS = "23456789TJQKA"
SUITS = "shdc"
DECK = [r + s for r in RANKS for s in SUITS]
SAMPLES = 80
CALL_MARGIN = 0.05
BET_EQ = 0.66
RAISE_EQ = 0.82


def card(c):
    return RANKS.index(c[0]), SUITS.index(c[1])


def straight_top(mask):
    """Highest straight top rank in a 13-bit rank mask (A also low), or -1."""
    bits = (mask << 1) | ((mask >> 12) & 1)          # bit 0 = ace-low, bit r+1 = rank r
    for top in range(13, 3, -1):
        if (bits >> (top - 4)) & 0b11111 == 0b11111:
            return top - 1
    return -1


def value(cards):
    """Comparable tuple for the best 5-card hand of 5..7 (rank, suit) cards."""
    counts = [0] * 13
    suits = [[] for _ in range(4)]
    mask = 0
    for r, s in cards:
        counts[r] += 1
        suits[s].append(r)
        mask |= 1 << r
    for s in range(4):
        if len(suits[s]) >= 5:
            fm = 0
            for r in suits[s]:
                fm |= 1 << r
            st = straight_top(fm)
            if st >= 0:
                return (8, st)
            return (5, *sorted(suits[s], reverse=True)[:5])
    groups = sorted(((counts[r], r) for r in range(13) if counts[r]), reverse=True)
    if groups[0][0] == 4:
        kick = max(r for r in range(13) if counts[r] and r != groups[0][1])
        return (7, groups[0][1], kick)
    if groups[0][0] == 3 and len(groups) > 1 and groups[1][0] >= 2:
        return (6, groups[0][1], groups[1][1])
    st = straight_top(mask)
    if st >= 0:
        return (4, st)
    singles = sorted((r for r in range(13) if counts[r] == 1), reverse=True)
    if groups[0][0] == 3:
        return (3, groups[0][1], *singles[:2])
    if groups[0][0] == 2 and len(groups) > 1 and groups[1][0] == 2:
        rest = sorted((r for r in range(13) if counts[r] and r not in (groups[0][1], groups[1][1])), reverse=True)
        return (2, groups[0][1], groups[1][1], *rest[:1])
    if groups[0][0] == 2:
        return (1, groups[0][1], *singles[:3])
    return (0, *singles[:5])


def equity(hole2, board, dead, rng, n=SAMPLES):
    """Equity of hole2 vs a random 2-card hand, the board completed at random."""
    h = [card(c) for c in hole2]
    b = [card(c) for c in board]
    rest = [card(c) for c in DECK if c not in dead]
    need = 5 - len(b)
    acc = 0.0
    for _ in range(n):
        draw = rng.sample(rest, 2 + need)
        full = b + draw[2:]
        mine, theirs = value(h + full), value(draw[:2] + full)
        acc += 1.0 if mine > theirs else (0.5 if mine == theirs else 0.0)
    return acc / n


def preflop_score(hole):
    """About 0 (worst) .. 1 (trips aces): pairs and trips, high cards, two suited."""
    rs = sorted((RANKS.index(c[0]) for c in hole), reverse=True)
    ss = [c[1] for c in hole]
    if rs[0] == rs[2]:
        return 0.8 + rs[0] / 60.0
    pair = rs[0] if rs[0] == rs[1] else (rs[1] if rs[1] == rs[2] else None)
    hi = (rs[0] + rs[1]) / 24.0
    s = 0.35 * hi + (0.1 if len(set(ss)) < 3 else 0.0) + (0.05 if rs[0] - rs[1] <= 2 else 0.0)
    if pair is not None:
        s = max(s, 0.45 + pair / 30.0)
    return s


def act(req, hole, rng):
    legal = req["legal_actions"]
    street = req["street"]
    board = req.get("board", [])
    to_call = req.get("to_call", 0)
    pot = req.get("pot", 0)
    price = to_call / (pot + to_call) if to_call > 0 else 0.0

    def reply(a, amt=None):
        m = {"type": "action", "action": a}
        if amt is not None:
            m["amount"] = int(max(req["min_raise"], min(req["max_raise"], amt)))
        return m

    if street == "preflop":
        s = preflop_score(hole)
        if s >= 0.52 and "raise" in legal and req.get("raises_left", 0) >= 2:
            return reply("raise", 3 * max(req["opp_bet"], 2))
        if "check" in legal:
            return reply("check")
        if s >= 0.12 + 0.5 * price:
            return reply("call")
        return reply("fold")
    dead = set(hole) | set(board) | ({req["my_discard"]} if req.get("my_discard") else set())
    if req.get("opp_discard"):
        dead.add(req["opp_discard"])
    keeps = list(combinations(hole, 2)) if len(hole) == 3 else [tuple(hole)]
    eq = max(equity(k, board, dead, rng) for k in keeps)
    if "raise" in legal and eq >= (RAISE_EQ if to_call > 0 else BET_EQ):
        return reply("raise", req["opp_bet"] + 2 * (pot + to_call) // 3)
    if "check" in legal:
        return reply("check")
    if eq >= price + CALL_MARGIN:
        return reply("call")
    return reply("fold")


def discard(hole, board):
    def key(h2):
        return value([card(c) for c in h2 + tuple(board)]), sorted((RANKS.index(c[0]) for c in h2), reverse=True)
    keep = max(combinations(hole, 2), key=key)
    return next(c for c in hole if c not in keep)


def main():
    hole = []
    extra = {}
    rng = random.Random(0)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        t = msg.get("type")
        if t == "new_hand":
            hole = list(msg.get("hole_cards", []))
            extra = {}
            rng = random.Random(msg.get("hand_id", 0))
            continue
        if t == "discard_result":
            hole = list(msg.get("hole_cards", hole))
            extra = {"my_discard": msg.get("my_discard"), "opp_discard": msg.get("opp_discard")}
            continue
        if t == "action_request":
            reply = act(dict(msg, **extra), hole, rng)
        elif t == "discard_request":
            hole = list(msg["hole_cards"])
            reply = {"type": "discard", "card": discard(hole, msg.get("board", []))}
        elif t == "match_end":
            break
        else:
            continue
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
