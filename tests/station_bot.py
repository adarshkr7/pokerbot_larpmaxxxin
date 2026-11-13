"""Test-only opponent: a calling station. Never folds, never raises: check if legal, else call. Discards the card
that does not make a pair with its other cards or the flop (else its lowest card). Deterministic."""
import json
import sys

RANKS = "23456789TJQKA"


def discard(hole, board):
    ranks = [c[0] for c in hole]
    board_ranks = {c[0] for c in board}
    paired = [c for c in hole if ranks.count(c[0]) >= 2 or c[0] in board_ranks]
    unpaired = [c for c in hole if c not in paired]
    pool = unpaired if unpaired and len(paired) >= 2 else hole
    return min(pool, key=lambda c: RANKS.index(c[0]))


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        t = msg.get("type")
        if t == "action_request":
            legal = msg["legal_actions"]
            reply = {"type": "action", "action": "check" if "check" in legal else "call"}
        elif t == "discard_request":
            reply = {"type": "discard", "card": discard(msg["hole_cards"], msg.get("board", []))}
        elif t == "match_end":
            break
        else:
            continue
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
