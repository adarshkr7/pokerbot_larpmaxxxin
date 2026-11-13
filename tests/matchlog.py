"""Test helper: rebuild the hand_result messages a bot received from the engine's match.log (the per-hand lines
written by starter_kit/engine.py Match.log_hand). Independent of bot/: only string handling."""
import re

LINE = re.compile(r"^L(\d+) #(\d+)\s+button (\S+) \| (\S+): (\S+ \S+ \S+)  (\S+): (\S+ \S+ \S+) \| board ([^|]*?)"
                  r"(?: \| discards (\S+):(\S+) (\S+):(\S+))? \| (.*?) \| (fold|showdown)\b(.*)$")
TOK = re.compile(r"^(.+?)([fxcr])(\d*)$")
NAMES = {"f": "fold", "x": "check", "c": "call", "r": "raise"}


def parse_line(line, me):
    """(leg, hand_result as `me` saw it, my seat) for one match.log hand line, or None."""
    m = LINE.match(line.rstrip("\n"))
    if not m:
        return None
    leg, hid, btn, n0, c0, n1, c1, board, da, xa, db, xb, acts, result, rest = m.groups()
    dealt = {n0: c0.split(), n1: c1.split()}
    if me not in dealt:
        return None
    opp = n1 if me == n0 else n0
    disc = {}
    if da:
        disc[da], disc[db] = xa, xb
    hist = []
    street = None
    for tok in acts.split():
        if tok.endswith(":"):
            street = tok[:-1]
            continue
        t = TOK.match(tok)
        if not t:
            return None
        who, a, amt = t.groups()
        e = {"street": street, "actor": "me" if who == me else "opp", "action": NAMES[a]}
        if amt:
            e["amount"] = int(amt)
        hist.append(e)
    net = re.search(re.escape(me) + r" ([+-]\d+)", rest)
    board = board.split() if board.strip() != "-" else []
    kept = lambda n: [c for c in dealt[n] if c != disc.get(n)] if n in disc else list(dealt[n])
    msg = {"type": "hand_result", "hand_id": int(hid), "result": result, "net": int(net.group(1)) if net else 0,
           "board": board, "my_hole_cards": kept(me),
           "opp_hole_cards": kept(opp) if result == "showdown" else None,
           "opp_discard": disc.get(opp), "history": hist}
    return int(leg), msg, ("button" if btn == me else "big_blind")


def read(path, me="A"):
    """{leg: [(hand_result, seat), ...]} from a match.log."""
    legs = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            got = parse_line(line, me)
            if got:
                legs.setdefault(got[0], []).append(got[1:])
    return legs
