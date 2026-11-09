"""Run an MIT Pokerbots 2026 ("Toss'em Hold'em") Python bot under OUR engine's protocol.

LOCAL SPARRING ONLY. Nothing here, and nothing under rivals/, may be imported by bot/ or
shipped in a submission (Rulebook 10.1). scripts/build.py only packages bot/.

The MIT 2026 game differs from Discard Hold'em, so the translation is approximate:
  * MIT: preflop -> 2-card flop -> BB discards, then SB discards (sequential) -> the discards
    become BOARD cards -> betting on streets 4 (flop), 5 (turn), 6 (river). 400-chip stacks.
  * Ours: preflop -> 3-card flop betting with 3 hole cards -> simultaneous discard (dead cards)
    -> turn -> river. 200-chip stacks, 4-raise cap.
Mapping used:
  preflop            -> MIT street 0
  flop betting       -> the bot's discard logic is asked first (MIT street 2 or 3), then the flop
                        betting is shown as MIT street 4 with the 2 kept cards
  discard_request    -> the discard chosen above (or asked now if no flop betting happened)
  turn / river       -> MIT streets 5 / 6
Rival exceptions fall back to check/fold (like the official engine's correction) and are
counted on stderr, so a translation glitch never forfeits a sparring match.
"""
import importlib
import json
import os
import sys
import time
import traceback

REAL_STDOUT = sys.stdout


def log(*a):
    print("[adapter]", *a, file=sys.stderr, flush=True)


class Adapter:
    def __init__(self, rival_dir):
        self.rival_dir = os.path.abspath(rival_dir)
        os.chdir(self.rival_dir)                 # rivals open data files relative to cwd
        sys.path.insert(0, self.rival_dir)
        sys.stdout = sys.stderr                  # rival prints must never reach the engine
        states = importlib.import_module("skeleton.states")
        self.A = importlib.import_module("skeleton.actions")
        self.states = states
        states.STARTING_STACK = 200
        self.player_mod = importlib.import_module("player")
        for mod in (self.player_mod, states):
            if hasattr(mod, "STARTING_STACK"):
                mod.STARTING_STACK = 200
        self.bot = self.player_mod.Player()
        self.errors = 0
        self.bankroll = 0
        self.total_hands = 1000

    # ------------------------------------------------------------- MIT state builders
    def round_state(self, street, my_bet, opp_bet, my_stack, opp_stack, board, hand,
                    opp_hand=None, button=None):
        idx = self.idx
        pips = [0, 0]; stacks = [0, 0]; hands = [[], []]
        pips[idx], pips[1 - idx] = my_bet, opp_bet
        stacks[idx], stacks[1 - idx] = my_stack, opp_stack
        hands[idx] = list(hand)
        hands[1 - idx] = list(opp_hand or [])
        values = dict(button=idx if button is None else button, street=street, pips=pips,
                      stacks=stacks, hands=hands, board=list(board), previous_state=None,
                      deck=None)
        RS = self.states.RoundState
        return RS(**{f: values.get(f) for f in RS._fields})

    def game_state(self, time_left_ms, hand_id):
        GS = self.states.GameState
        values = dict(bankroll=self.bankroll, game_clock=time_left_ms / 1000.0,
                      round_num=hand_id)
        return GS(**{f: values.get(f) for f in GS._fields})

    def call_rival(self, fn, *args):
        try:
            return fn(*args)
        except Exception:
            self.errors += 1
            if self.errors <= 5:
                log(f"rival exception #{self.errors}:\n" + traceback.format_exc())
            return None

    # ------------------------------------------------------------- engine messages
    def on_init(self, m):
        self.total_hands = m.get("total_hands", 1000)
        self.states.NUM_ROUNDS = self.total_hands
        if hasattr(self.player_mod, "NUM_ROUNDS"):
            self.player_mod.NUM_ROUNDS = self.total_hands

    def on_new_hand(self, m):
        self.idx = 0 if m["seat"] == "button" else 1    # MIT: player 0 = small blind
        self.hole = list(m["hole_cards"])
        self.kept = None
        self.planned_discard = None
        self.hand_id = m["hand_id"]
        self.last_street = "preflop"
        self.time_left_ms = 30000
        my_bet, opp_bet = (1, 2) if self.idx == 0 else (2, 1)
        rs = self.round_state(0, my_bet, opp_bet, 200 - my_bet, 200 - opp_bet, [], self.hole)
        self.call_rival(self.bot.handle_new_round,
                        self.game_state(self.time_left_ms, self.hand_id), rs, self.idx)

    def ask_discard(self, board, time_left_ms, pot_bets=(0, 0), stacks=(200, 200)):
        street = 2 if self.idx == 1 else 3          # legal for idx 1 on street 2, idx 0 on 3
        rs = self.round_state(street, 0, 0, stacks[0], stacks[1], board, self.hole,
                              button=self.idx)
        act = self.call_rival(self.bot.get_action, self.game_state(time_left_ms, self.hand_id),
                              rs, self.idx)
        if act is not None and type(act).__name__ == "DiscardAction":
            i = act.card
            if isinstance(i, int) and 0 <= i < len(self.hole):
                return self.hole[i]
        return min(self.hole, key=lambda c: "23456789TJQKA".index(c[0]))

    def on_action_request(self, m):
        self.time_left_ms = m.get("time_left_ms", 30000)
        street = m["street"]
        legal = m["legal_actions"]
        board = m["board"]
        if street == "preflop":
            mit_street, hand = 0, self.hole
        elif street == "flop":
            if self.planned_discard is None:
                self.planned_discard = self.ask_discard(board, self.time_left_ms,
                                                        stacks=(m["my_stack"], m["opp_stack"]))
            mit_street = 4
            hand = [c for c in self.hole if c != self.planned_discard]
        else:
            mit_street = 5 if street == "turn" else 6
            hand = self.kept or [c for c in self.hole if c != self.planned_discard][:2]
        acted_this_street = any(h.get("street") == street for h in m.get("history", []))
        button = self.idx + (2 if acted_this_street else 0)
        rs = self.round_state(mit_street, m["my_bet"], m["opp_bet"], m["my_stack"],
                              m["opp_stack"], board, hand, button=button)
        act = self.call_rival(self.bot.get_action,
                              self.game_state(self.time_left_ms, self.hand_id), rs, self.idx)
        return self.translate(act, m, legal)

    @staticmethod
    def translate(act, m, legal):
        name = type(act).__name__ if act is not None else None
        def pick(*prefs):
            for p in prefs:
                if p in legal:
                    return {"type": "action", "action": p}
            return {"type": "action", "action": legal[0]}
        if name == "RaiseAction" and "raise" in legal:
            amt = int(getattr(act, "amount", m["min_raise"]))
            amt = max(m["min_raise"], min(m["max_raise"], amt))
            return {"type": "action", "action": "raise", "amount": amt}
        if name in ("RaiseAction", "CallAction"):
            return pick("call", "check")
        if name == "FoldAction":
            return pick("fold", "check")
        if name == "CheckAction":
            return pick("check", "fold")
        return pick("check", "fold")          # exception / unknown: same as engine correction

    def on_discard_request(self, m):
        self.time_left_ms = m.get("time_left_ms", 30000)
        self.hole = list(m["hole_cards"])
        card = self.planned_discard
        if card not in self.hole:
            card = self.ask_discard(m["board"], self.time_left_ms,
                                    stacks=(m["my_stack"], m["opp_stack"]))
        return {"type": "discard", "card": card}

    def on_discard_result(self, m):
        self.kept = list(m["hole_cards"])

    def on_hand_result(self, m):
        net = m["net"]
        street_end = {0: 0, 3: 4, 4: 5, 5: 6}.get(len(m.get("board", [])), 6)
        deltas = [0, 0]
        deltas[self.idx], deltas[1 - self.idx] = net, -net
        mine = m.get("my_hole_cards") or self.hole
        rs = self.round_state(street_end, 0, 0, 0, 0, m.get("board", []), mine,
                              opp_hand=m.get("opp_hole_cards") or [])
        TS = self.states.TerminalState
        values = dict(deltas=deltas, previous_state=rs, bounty_hits=None)
        ts = TS(**{f: values.get(f) for f in TS._fields})
        self.call_rival(self.bot.handle_round_over,
                        self.game_state(self.time_left_ms, self.hand_id), ts, self.idx)
        self.bankroll += net


def send(msg):
    REAL_STDOUT.write(json.dumps(msg) + "\n")
    REAL_STDOUT.flush()


def main(rival_dir):
    t0 = time.perf_counter()
    ad = Adapter(rival_dir)
    log(f"loaded {rival_dir} in {time.perf_counter() - t0:.2f}s")
    handlers = {"init": ad.on_init, "new_hand": ad.on_new_hand,
                "discard_result": ad.on_discard_result, "hand_result": ad.on_hand_result}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
        except ValueError:
            continue
        t = m.get("type")
        if t == "action_request":
            try:
                send(ad.on_action_request(m))
            except Exception:
                ad.errors += 1
                log("adapter error:\n" + traceback.format_exc())
                send(Adapter.translate(None, m, m["legal_actions"]))
        elif t == "discard_request":
            try:
                send(ad.on_discard_request(m))
            except Exception:
                ad.errors += 1
                log("adapter error:\n" + traceback.format_exc())
                send({"type": "discard", "card": m["hole_cards"][0]})
        elif t == "match_end":
            break
        elif t in handlers:
            try:
                handlers[t](m)
            except Exception:
                ad.errors += 1
                if ad.errors <= 5:
                    log("adapter error:\n" + traceback.format_exc())
    log(f"leg done, rival/adapter errors: {ad.errors}")
