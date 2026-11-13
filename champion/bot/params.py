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

# --- W2 ---
MIN_SAMPLES = 64             # equity: every sampling call draws at least this many (budget 0 -> exactly this)
MAX_SAMPLES = 20000          # equity: hard cap per call (64 + 32 * 623: a checkpoint); budget inf -> exactly this
CHECK_EVERY = 32             # equity: clock checked every this many samples / enumerated pairs
RIVER_SAFETY = 1.5           # river: enumerate exactly only if 1.5 x the predicted time fits the remaining budget

# --- W3 ---
DISCARD_MAX_SAMPLES = 2000        # D1: hard cap on shared samples per discard while betting is possible
DISCARD_ALLIN_MAX_SAMPLES = 4000  # D5: cap when all-in (no later decisions in this hand)
DISCARD_MIN_SAMPLES = 96          # fewer samples inside the budget -> the static max-S keep
DISCARD_CHECK_EVERY = 32          # clock checked every this many samples
DISCARD_ALLIN_BUDGET_MULT = 1.5   # all-in: discard budget x this (turn/river need no time), within the decision cap
DISCARD_TIE_MARGIN = 0.01         # D1: best two keeps within this equity -> prefer more draw potential (betting only)
S_FLUSH_DRAW = 0.25               # D3 static flop score S: draw bonuses (made hand below a straight only)
S_OPEN_ENDED = 0.20
S_GUTSHOT = 0.08
S_OVERCARD = 0.04                 # per hole card above the top flop card
POSTERIOR_BETA = 4.0              # D3 softmax rationality (0 = random discarder)
POSTERIOR_ETA = 0.1               # D3 toss-lowest noise
POSTERIOR_SMOOTH = 0.02           # D3 final smoothing: W = (1 - eps) q + eps / M

# --- W4 ---
# Preflop (strategies/04_preflop.md). Shares are of all 22,100 physical hands ("top X%"), ranked by the offline
# equity-vs-random table. Sizes are in big blinds or multiples of the bet faced; amounts are raise-to totals.
PF_BB = 2                         # the engine's big blind (sizes below are multiples of it)
PF_OPEN_PCT = 0.78                # P2: button open-raises the top 78%
PF_LIMP_PCT = 0.06                # ... completes (limps) the next 6%, folds the bottom 16%
PF_OPEN_BB = 3.0                  # P3: open to 3 BB (6 chips)
PF_ISO_PCT = 0.30                 # big blind raises a limp with the top 30%, checks the rest
PF_ISO_BB = 4.0                   # ... to 4 BB (8 chips)
PF_THREEBET_PCT = 0.15            # P2: big blind 3-bets the top 15% vs an open
PF_THREEBET_MULT = 3.0            # P3: 3-bet to 3x the open (6 -> 18)
# P1/P2: defend (call + 3-bet) share vs the price faced, price = to_call / (pot + to_call):
# min-raise (2 into 6 = 0.25) -> top 92%; 3x open (4 into 8 = 0.333) -> top 70%; bigger opens -> less.
PF_DEFEND_CURVE = ((0.25, 0.92), (0.333, 0.70), (0.40, 0.52), (0.45, 0.38), (0.50, 0.25))
# P2: continue (call + 4-bet) share facing a 3-bet: 12 into 24 (0.333) -> top 38% (about half our opens)
PF_CONT3_CURVE = ((0.25, 0.50), (0.333, 0.38), (0.40, 0.28), (0.45, 0.20), (0.50, 0.15))
PF_FOURBET_PCT = 0.06             # 4-bet the top 6% facing a 3-bet
PF_FOURBET_MULT = 2.2             # P3: 4-bet to 2.2x the 3-bet (18 -> 40)
PF_SHOVE_COMMIT_FRAC = 0.40       # P3: a raise committing more than 40% of the stack goes all-in instead
PF_BIG_CALL_FRAC = 0.35           # a call of >= 35% of our stack (or an all-in) is priced as an all-in decision
PF_R_IP = 1.08                    # 05/B1 equity realisation: in position (button) ...
PF_R_OOP = 0.92                   # ... and out of position; used facing a 4-bet that is not all-in (P2)
PF_CALL_MARGIN = 0.0              # extra equity required over the break-even price
PF_FOURBET_RANGE = 0.08           # assumed width of an unknown opponent's 4-bet range
PF_SHOVE_RANGE = 0.20             # assumed width of an unknown opponent's shoving range (conservative: strong)
PF_SHOVE_WIDEN = 1.0              # shoving range = max(PF_SHOVE_RANGE, PF_SHOVE_WIDEN x their shove frequency)
PF_VALUE_SHOVE_PCT = 0.05         # facing a big bet with a raise still legal: re-shove the top 5%
PF_LOW_TRIPS_MAX_RANK = 7         # rank index of 9: 222-999 never 4-bet / shove-raise (P1 traps)
PF_MIX_BAND = 0.02                # hands within 2 percentile points of a cut are mixed (light randomisation)
PF_FALLBACK_RANGE_DROP = 0.12     # no range table: equity vs a top-w range ~ eq - (1 - w) x (this + ...)
# P4 exploit hooks. Frequency stats are read once the opponent model reports PF_EXPLOIT_MIN_HANDS observed hands
# (stub: 0 -> off); the shove estimate is read from the first hand (06/M1: a shrunk Beta estimate). Maniac /
# station overrides are blended by the model's archetype weights (06/M2, M4), never switched.
PF_EXPLOIT_MIN_HANDS = 20
PF_STEAL_FOLD_RAMP = (0.57, 0.67) # fold-to-steal ramp (centre 0.62) -> blend towards opening every button ...
PF_STEAL_TO_BB = 2.0              # ... as a min-raise to 2 BB (4 chips)
PF_OPEN_PCT_VS_MANIAC = 0.45      # vs a maniac: open tighter, no limps (no small speculative opens)
PF_MANIAC_DEFEND_BONUS = 0.10     # vs a maniac: defend and 3-bet this much wider
PF_STATION_VALUE_PCT = 0.45       # vs a station: raise the top 45% for value (larger), complete the rest
PF_OPEN_BB_VS_STATION = 4.0
PF_ISO_PCT_VS_STATION = 0.45
PF_WIDE_3BET_RAMP = (0.25, 0.35)  # their 3-bet frequency ramp (centre 0.30) -> continue wider vs 3-bets ...
PF_WIDE_3BET_CONT_BONUS = 0.10

# --- W5 ---
# Postflop betting (strategies/05_postflop_betting.md B1-B7, B8b hooks). Equities are win + tie/2 in [0, 1].
# Time: flop = best-keep equity on shared samples (discard.keep_equities); turn = weighted MC; river = exact.
BET_FLOP_MAX_SAMPLES = 450        # flop: cap on shared samples for the first decision of the street
BET_FLOP_MIN_SAMPLES = 96         # fewer samples inside the budget -> the static path
BET_TURN_MAX_SAMPLES = 1000       # turn: cap on (pair, river) samples
BET_TURN_MIN_SAMPLES = 64
BET_RECALC_FRAC = 0.5             # later decisions on the same street (their range changed): this x cap and budget
BET_CHECK_EVERY = 32              # turn sampler: clock checked every this many samples
BET_MIN_EXTRA_MS = 2.0            # if fewer ms than this are left after the range work, use the static path
# B1 calling rule: call if R_pos * E > to_call / (pot + to_call) + margin (no future betting: R = 1, margin 0)
BET_R_IP = 1.08                   # equity realisation in position (button) on the flop / turn
BET_R_OOP = 0.92                  # ... out of position (big blind)
BET_MARGIN = {"flop": 0.03, "turn": 0.03, "river": 0.0}
# B2 value: bet / raise when equity vs their CALLING range clears these (baseline; B8b archetypes below)
BET_VALUE_TH = {"flop": 0.60, "turn": 0.58, "river": 0.56}
BET_RAISE_TH = {"flop": 0.66, "turn": 0.64, "river": 0.62}
BET_THIN_TH = 0.66                # value hands below this bet 1/3 pot (thin), above it 2/3
BET_BIG_TH = 0.78                 # ... and above this 1x pot on wet boards (always 1x for raises)
BET_SHOVE_SPR_TH = 0.75           # strong value (eq_call >= this) shoves when SPR after the bet <= BET_SHOVE_SPR
BET_SHOVE_SPR = 1.0
BET_NUTS_TH = 0.92                # vs a station: shove with this much equity
# B3 size menu (pot fractions) and shove-snap
BET_F_THIN = 1.0 / 3.0
BET_F_STD = 2.0 / 3.0
BET_F_BIG = 1.0
BET_SNAP_FRAC = 1.0 / 3.0         # behind < this x the pot after the call -> send max_raise
# B4: with raises_left == 1 (the last raise of the street) a value raise uses this fraction and SPR shove level
BET_LAST_RAISE_F = 1.0
BET_LAST_RAISE_SPR = 2.0
# B5 semi-bluffs (flop/turn draws): equity band, and how often (unknown opponent / folds a lot / folds little)
BET_SEMI_EQ_LO = 0.28
BET_SEMI_FTB = 0.45               # their fold-to-bet above this -> semi-bluff with BET_SEMI_P_HIGH
BET_SEMI_P_BASE = 0.20            # unknown opponent (stats not yet trusted): rarely, not never
BET_SEMI_P_HIGH = 0.70
BET_SEMI_RAISE_MULT = 0.5         # semi-bluff raises (facing a bet of <= half the pot) at this x the bet rate
BET_SEMI_MAX_PRICE = 0.30
# B6 river bluffs: air (equity below BET_AIR_TH) bluffs with p = min(1, (v / a) * B / (P + B)); exploit test
BET_AIR_TH = 0.22
BET_BLUFF_V = 0.25                # fixed estimates: share of river spots reached with a value bet ...
BET_BLUFF_A = 0.55                # ... and with air  (v/a = 0.45 -> ~18% of airs at 2/3 pot, ~23% at pot)
BET_BLUFF_MIN_FTB = 0.25          # known fold-to-bet below this -> no bluffs; >= B/(P+B) -> always bluff air
# B7 range model. Preflop prior over their triples by percentile p (preflop.PCT): soft cut at the top `width`
BET_PRIOR_SOFT = 0.04             # logistic softness of the cut (percentile points)
BET_PRIOR_FLOOR = 0.03            # weight far below the cut (robust to mis-modelling)
BET_PRIOR_TOP_KEEP = 0.35         # a caller / limper keeps this weight on the top they would have raised
BET_PRIOR_CALL3_FRAC = 0.6        # they raised then called our re-raise: width = pfr x this
# Postflop aggression: weight x exp(gamma * strength) per action; strength = min(S, BET_S_CAP) on the flop,
# BET_U_SCALE x (strength percentile within their range, draws lifted) on the turn and river
BET_TILT_RAISE = 1.1              # per bet / raise by them
BET_TILT_CALL = 0.0               # per call
BET_TILT_CHECK = -0.15            # per check (mildly weaker)
BET_TILT_MAX = 2.6                # |sum of tilts on one street| is clipped here
BET_S_CAP = 4.5
BET_U_SCALE = 3.0
BET_U_FLUSH_DRAW = 0.60           # turn: a flush draw counts at least as this strength percentile
BET_U_OESD = 0.55
BET_AGG_REF = 1.5                 # passivity multiplier = clip((REF / their aggression) ** 0.5, LO, HI); REF =
                                  # the 06/M1 aggression-factor prior, so an average opponent gets exactly 1
BET_AGG_MULT_LO = 0.6
BET_AGG_MULT_HI = 1.8
BET_TOSS_LOWEST_ON = 0.90         # opp.stat("toss_lowest") >= this (>= 6 showdowns) -> D3 toss-lowest likelihood
BET_TAU_RAMP = (0.55, 0.90)       # 03/D3: beta = POSTERIOR_BETA x clip((tau - 0.55) / 0.35, 0, 1)
# Calling range (B2): weight of each holding in their calling range
BET_CALL_S_MID = 0.9              # flop: logistic in S_best (a pair or a strong draw calls)
BET_CALL_S_SOFT = 0.25
BET_CALL_U_MID = 0.45             # turn / river: logistic in the strength percentile
BET_CALL_U_SOFT = 0.10
BET_CALL_FLOOR = 0.08
# Static (panic tier / no samples) equity from a flop-score-like S: piecewise-linear S -> E
BET_STATIC_S = (0.0, 0.4, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0)
BET_STATIC_E = (0.30, 0.42, 0.52, 0.60, 0.70, 0.82, 0.88, 0.92, 0.97)
BET_STATIC_CALL_DROP = 0.06       # static eq_call = static E - this
BET_STATIC_BOARD_DROP = 1.0       # river: our hand class no better than the board's -> S - this
# B8b archetype hooks: opp.archetype_weights() blends these overrides of the baseline (missing keys: baseline;
# unknown archetypes count as "neutral"). range_info: how much their actions / preflop line / discard inform.
BET_ARCH = {
    "station": {"value_th": 0.52, "raise_th": 0.62, "call_station": 1.0, "bluff": 0.0, "semi": 0.0,
                "size_mult": 1.5, "tilt": 1.3},
    "nit": {"tilt": 1.6, "cbet": 1.0},
    "random": {"value_th": 0.55, "raise_th": 0.68, "call_station": 1.0, "bluff": 0.0, "semi": 0.0,
               "size_mult": 1.5, "range_info": 0.0},
    "maniac": {"value_th": 0.55, "raise_th": 0.62, "call_station": 0.5, "bluff": 0.0, "semi": 0.0, "tilt": 0.4},
}
BET_ARCH_BASE = {"value_th": 0.0, "raise_th": 0.0, "call_station": 0.0, "bluff": 1.0, "semi": 1.0,
                 "size_mult": 1.0, "tilt": 1.0, "cbet": 0.0, "range_info": 1.0}   # 0.0 thresholds = per street
BET_NIT_CBET_F = 0.30             # nit hook: c-bet this pot fraction with probability = the "cbet" blend
# B7 size-aware narrowing: each of their bets / raises tilts by BET_TILT_RAISE x m, m = clip((x / REF) ** EXP,
# LO, HI) with x = what we must call / the pot if we called (opening bet: bet / pot before it); an all-in
# multiplies m by BET_SIZE_ALLIN (after the clip). The street total stays clipped at BET_TILT_MAX.
BET_SIZE_REF = 0.66               # a 2/3-pot bet tilts exactly as before (m = 1)
BET_SIZE_EXP = 0.5
BET_SIZE_LO = 0.6                 # a min-bet: m >= 0.6
BET_SIZE_HI = 2.0                 # a pot-size or bigger overbet: m <= 2
BET_SIZE_ALLIN = 1.2              # an all-in: m x 1.2 (so a shove reaches 1.1 x 2.4 = 2.64 -> clipped 2.6)
BET_SIZE_DAMP_ALLIN = (0.08, 0.30)  # their all-in frequency ramp: the amplification above m = 1 fades to 0 (a
                                  # maniac's shoves say little); 0.08 = the 06/M1 prior, so no damping by default
BET_MDF_MULT_LO = 0.5             # 07/G2: the MDF diagnostic may cut their tilt to no less than half

# --- W6 ---
# Opponent model (strategies/06_opponent_modelling.md M1, M2, M4). Frequencies: est = (k + N0 * prior) / (n + N0)
# over exponentially forgotten counts (every count x 0.5 ** (1 / OPP_HALF_LIFE) per observed hand).
OPP_HALF_LIFE = 70.0              # hands; the effective sample saturates at ~101 hands
OPP_FREQ = {                      # name: (prior, N0)
    "vpip": (0.65, 12), "pfr": (0.35, 12), "three_bet": (0.12, 10),
    "shove": (0.12, 4),           # N0 4, not 10: an all-in bot must be read within a few hands (see 06 report)
    "fold_to_steal": (0.40, 10), "fold_to_bet": (0.42, 12), "agg_freq": (0.30, 12), "allin": (0.08, 10),
    "discard_tau": (0.90, 6), "toss_rate": (0.60, 6),
}
OPP_STREET_N0 = 8                 # per-street fold-to-bet shrinks towards the overall estimate with this strength
OPP_AF_PRIOR = 1.5                # aggression factor (bets + raises + 1.5 k) / (calls + k)
OPP_AF_K = 15.0
OPP_CORR_N0 = 8.0                 # size -> strength correlation shrunk as n r / (n + 8)
OPP_TOSS_MIN_N = 6.0              # toss_lowest reported (raw rate) only from this many showdowns, else 0
OPP_LOG_EVERY = 50                # debug line with the weights and key stats every this many hands
# M2 archetype ramps on the shrunk estimates (centred on the 06/M1 thresholds, wide so one hand moves a weight little): ramp(x, a, b) = clip((x - a) / (b - a), 0, 1) (a > b: decreasing)
OPP_MANIAC_PFR = (0.50, 0.75)
OPP_MANIAC_SHOVE = (0.35, 0.60)
OPP_STATION_FTB = (0.30, 0.15)
OPP_STATION_AF = (1.00, 0.50)
OPP_NIT_VPIP = (0.45, 0.30)
OPP_NIT_FTB = (0.50, 0.65)
OPP_RANDOM_TAU = (0.60, 0.42)     # random discards keep the max-S pair ~1/3 of the time; toss-lowest ~0.69
OPP_RANDOM_TOSS = (0.75, 0.55)    # ... and a toss-lowest bot (rate ~1) is never "random"
OPP_RANDOM_CORR = (0.25, 0.10)    # bet size unrelated to showdown strength
OPP_RANDOM_SHOWDOWNS = (6.0, 15.0)  # ... and only with enough showdowns to tell (a false "random" label is costly)
# 07/G2 MDF diagnostic: our fold rate to their opening bets vs 1 - MDF, against aggressive opponents only
OPP_MDF_MIN_BETS = (15.0, 25.0)   # confidence ramp over the (forgotten) number of their opening bets
OPP_MDF_EXCESS = (0.05, 0.25)     # fold-rate excess over 1 - MDF -> reduction ramp 0 .. 1 - BET_MDF_MULT_LO
OPP_AGGRO_AF = (2.5, 3.5)         # aggressive = max(maniac weight, ramp of the aggression factor)
