"""Test-only opponent: a nit. Plays only strong preflop hands (a pair of 8s or better, or two cards Q+), folds to
any bet without top pair or better, raises only with two pair or better; keeps the pair of cards that makes its
best hand with the flop. Deterministic."""
import json
import sys
from itertools import combinations

RANKS = "23456789TJQKA"


def r(c):
    return RANKS.index(c[0])


def rank5(cards):
    """A comparable tuple for 5 cards: (category, ranks...). Categories 0 high .. 8 straight flush."""
    rs = sorted((r(c) for c in cards), reverse=True)
    counts = sorted(((rs.count(x), x) for x in set(rs)), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    uniq = sorted(set(rs), reverse=True)
    straight = None
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            straight = uniq[0]
        elif uniq == [12, 3, 2, 1, 0]:
            straight = 3
    if straight is not None:
        return (8 if flush else 4, straight)
    if counts[0][0] == 4:
        return (7, counts[0][1], counts[1][1])
    if counts[0][0] == 3 and counts[1][0] == 2:
        return (6, counts[0][1], counts[1][1])
    if flush:
        return (5, *rs)
    if counts[0][0] == 3:
        return (3, counts[0][1], *[x for x in rs if x != counts[0][1]])
    if counts[0][0] == 2 and counts[1][0] == 2:
        return (2, counts[0][1], counts[1][1], counts[2][1])
    if counts[0][0] == 2:
        return (1, counts[0][1], *[x for x in rs if x != counts[0][1]])
    return (0, *rs)


def best(hole2, board):
    cards = list(hole2) + list(board)
    if len(cards) < 5:
        return (0,)
    return max(rank5(c) for c in combinations(cards, 5))


def strong_made(hole, board):
    """Top pair or better using a hole card (any 2 of the hole cards on the flop)."""
    top = max(r(c) for c in board)
    if monster(hole, board):
        return True
    for h2 in combinations(hole, 2):
        v = best(h2, board)
        if v[0] == 1 and v[1] >= top and any(r(c) == v[1] for c in h2):
            return True
    return False


def monster(hole, board):
    """Two pair or better that uses a hole card (trips and up counted whenever the board alone is weaker)."""
    for h2 in combinations(hole, 2):
        v = best(h2, board)
        if v[0] >= 3 and (len(board) < 5 or v > rank5(board)):
            return True
        if v[0] == 2 and any(r(c) in v[1:3] for c in h2):
            return True
    return False


def strong_preflop(hole):
    rs = sorted((r(c) for c in hole), reverse=True)
    pair = [x for x in rs if rs.count(x) >= 2]
    return (pair and max(pair) >= 6) or rs[1] >= 10


def act(req, hole):
    legal = req["legal_actions"]
    street = req["street"]
    board = req.get("board", [])

    def reply(a, amt=None):
        m = {"type": "action", "action": a}
        if amt is not None:
            m["amount"] = int(max(req["min_raise"], min(req["max_raise"], amt)))
        return m

    if street == "preflop":
        good = strong_preflop(hole)
    else:
        good = strong_made(hole, board)
    if good and street != "preflop" and monster(hole, board) and "raise" in legal:
        return reply("raise", req["opp_bet"] + (req["pot"] + req["to_call"]) // 2)
    if good and street == "preflop" and "raise" in legal and req.get("raises_left", 0) >= 2:
        return reply("raise", 3 * max(req["opp_bet"], 2))
    if "check" in legal:
        return reply("check")
    if good:
        return reply("call")
    return reply("fold")


def discard(hole, board):
    keep = max(combinations(hole, 2), key=lambda h2: (best(h2, board) if len(board) >= 3 else (0,),
                                                      sorted((r(c) for c in h2), reverse=True)))
    return next(c for c in hole if c not in keep)


def main():
    hole = []
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
            continue
        if t == "discard_result":
            hole = list(msg.get("hole_cards", hole))
            continue
        if t == "action_request":
            reply = act(msg, hole)
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
