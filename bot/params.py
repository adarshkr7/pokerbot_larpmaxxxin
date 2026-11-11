"""Tunable constants only, one section per workstream. No logic."""

# --- W1 ---
RESERVE_MIN_MS = 1500        # never plan to spend the last part of the bank
RESERVE_FRAC = 0.08          # reserve = max(RESERVE_MIN_MS, RESERVE_FRAC * bank): 2.4 s (stage 1), 6 s (stage 2)
PANIC_BANK_MULT = 1.25       # panic below 1.25 x reserve left
PANIC_PER_HAND_MS = 25.0     # panic below this per-hand budget
THROTTLE_PER_HAND_MS = 80.0  # throttle below this per-hand budget
TARGET_USE = 0.65            # plan to use this share of the per-hand budget
THROTTLE_MULT = 0.5
MAX_DECISION_MS = 400.0      # hard cap per decision (the engine limit is 5 s)
MAX_DECISION_FRAC = 0.2      # ... and at most this share of per_response_ms
SHARE = {"preflop": 0.02, "flop": 0.25, "discard": 0.30, "turn": 0.23, "river": 0.20}
RESULTS_MAX = 1000           # LegState.results is bounded
