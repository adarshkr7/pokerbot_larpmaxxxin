"""Test-only opponent: shoves all-in at its first preflop decision (raise to max_raise), else calls/checks;
discards its lowest card. Against our check/call bot every unfolded hand reaches the discard all-in (03/D5)."""
import json
import sys

RANKS = "23456789TJQKA"


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
            if "raise" in legal:
                reply = {"type": "action", "action": "raise", "amount": msg["max_raise"]}
            elif "call" in legal:
                reply = {"type": "action", "action": "call"}
            else:
                reply = {"type": "action", "action": "check"}
        elif t == "discard_request":
            reply = {"type": "discard", "card": min(msg["hole_cards"], key=lambda c: RANKS.index(c[0]))}
        elif t == "match_end":
            break
        else:
            continue
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
