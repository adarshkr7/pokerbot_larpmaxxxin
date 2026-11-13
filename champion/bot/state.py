"""Per-hand and per-leg state. Nothing here survives the process (no file writes)."""
from cards import is_valid, parse, parse_valid
from params import RESULTS_MAX

STREETS = ("preflop", "flop", "turn", "river")


def _num(x, default):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else default


class HandState:
    def __init__(self, hand_id=None, seat=None, hole_cards=None):
        self.hand_id = hand_id
        self.seat = seat if seat in ("button", "big_blind") else None
        self.hole_strs = []        # as received (may contain malformed entries)
        self.hole3 = []            # our 3 pre-discard cards (ints), from the latest authoritative source
        self.hole = []             # current hole cards (ints): 3, then 2 after the discard
        self.board = []
        self.street = "preflop"
        self.pot = 0
        self.my_bet = 0
        self.opp_bet = 0
        self.to_call = 0
        self.my_stack = 200
        self.opp_stack = 200
        self.history = []
        self.my_discard = None
        self.opp_discard = None
        self.dead = bytearray(52)
        if isinstance(hole_cards, list):
            self._set_hole3(hole_cards)
        self.rebuild_dead()

    def _set_hole3(self, cards):
        self.hole_strs = list(cards)
        self.hole3 = parse_valid(cards)
        self.hole = list(self.hole3)

    def rebuild_dead(self):
        """dead = hole3 + board + the opponent's discard, rebuilt from scratch after every update."""
        dead = bytearray(52)
        for c in self.hole3:
            dead[c] = 1
        for c in self.board:
            dead[c] = 1
        if is_valid(self.opp_discard):
            dead[parse(self.opp_discard)] = 1
        self.dead = dead

    def _copy_numbers(self, req, names):
        for name in names:
            setattr(self, name, _num(req.get(name), getattr(self, name)))

    def update_from_request(self, req):
        """Sync from an action_request (which carries no hole cards)."""
        if req.get("street") in STREETS:
            self.street = req["street"]
        self._copy_numbers(req, ("pot", "my_bet", "opp_bet", "to_call", "my_stack", "opp_stack"))
        if isinstance(req.get("history"), list):
            self.history = req["history"]
        if isinstance(req.get("board"), list):
            self.board = parse_valid(req["board"])
        self.rebuild_dead()

    def update_from_discard_request(self, req):
        """Sync everything a discard_request carries, before the discard policy runs.

        After a preflop all-in the engine skips flop betting, so this is the first message with the flop.
        """
        if isinstance(req.get("hole_cards"), list):
            self._set_hole3(req["hole_cards"])
        if isinstance(req.get("board"), list):
            self.board = parse_valid(req["board"])
        self.street = "flop"
        self._copy_numbers(req, ("pot", "my_stack", "opp_stack"))
        self.rebuild_dead()

    def update_from_discard_result(self, msg):
        if isinstance(msg.get("my_discard"), str):
            self.my_discard = msg["my_discard"]
        if isinstance(msg.get("opp_discard"), str):
            self.opp_discard = msg["opp_discard"]
        if isinstance(msg.get("hole_cards"), list):
            self.hole = parse_valid(msg["hole_cards"])
        self.rebuild_dead()


class LegState:
    def __init__(self):
        self.total_hands = 200
        self.time_bank_ms = 30000
        self.per_response_ms = 5000
        self.small_blind = 1
        self.big_blind = 2
        self.starting_stack = 200
        self.hands_done = 0
        self.net = 0
        self.notices = 0
        self.results = []

    def configure(self, msg):
        """Apply an init message; keep the defaults for anything missing or not a positive number."""
        for name in ("total_hands", "time_bank_ms", "per_response_ms", "small_blind", "big_blind",
                     "starting_stack"):
            v = msg.get(name)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                setattr(self, name, v)

    def record(self, msg):
        self.hands_done += 1
        net = msg.get("net")
        if isinstance(net, (int, float)) and not isinstance(net, bool):
            self.net += net
        if len(self.results) < RESULTS_MAX:
            self.results.append({"hand_id": msg.get("hand_id"), "net": net, "result": msg.get("result"),
                                 "opp_hole_cards": msg.get("opp_hole_cards")})
