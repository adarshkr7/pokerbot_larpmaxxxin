"""Fast 5-7 card hand evaluator (F02 plan 3.2). Orders hands exactly as the engine's best_hand.

eval7(cards) -> int, higher is better, equal iff the engine's best_hand tuples are equal.
Encoding: cat << 20 | k1 << 16 | k2 << 12 | k3 << 8 | k4 << 4 | k5 (ranks 0..12 = 2..A, unused nibbles 0).
  8 straight flush (high card; wheel -> 3)   7 quads (quad, kicker)   6 full house (trips, pair)
  5 flush (top 5 of the flush suit)          4 straight (high; wheel -> 3)
  3 trips (trips, 2 kickers)   2 two pair (high, low, kicker)   1 pair (pair, 3 kickers)   0 high card (top 5)

Method: one pass sums a per-card code holding a 3-bit count per rank (bits 0..38) and a 4-bit count per suit
(bits 40..55). No suit has >= 5 cards -> the value depends only on the rank counts and is memoised by them
(at most ~74k distinct rank multisets of 5-7 cards). Otherwise -> flush / straight flush (with >= 5 cards of one
suit among <= 7, quads and full houses are impossible), memoised by the flush suit's 13-bit rank mask.
Callers guarantee 5-7 distinct ids in 0..51 (not validated: hot path).
"""

_RANK_BITS = (1 << 39) - 1
_K = [(1 << (3 * (c >> 2))) | (1 << (40 + 4 * (c & 3))) for c in range(52)]
_NF = {}      # rank-count key -> value (non-flush hands)
_FL = {}      # flush-suit rank mask -> value


def _straight_hi(mask):
    """High rank of the best straight in a 13-bit rank mask, or -1 (wheel A-2-3-4-5 -> 3)."""
    s = mask & (mask >> 1) & (mask >> 2) & (mask >> 3) & (mask >> 4)
    if s:
        return s.bit_length() + 3          # lowest rank of the top run + 4
    if mask & 0x100F == 0x100F:
        return 3
    return -1


def _top(mask, n):
    """The n highest ranks set in `mask`, as left-aligned kicker nibbles starting at k1."""
    v = 0
    shift = 16
    r = 12
    while n and r >= 0:
        if mask >> r & 1:
            v |= r << shift
            shift -= 4
            n -= 1
        r -= 1
    return v


def _nonflush(key):
    quads = -1
    trips = -1
    pairs = []          # ranks with count >= 2 that are not the (highest) trips / quads, high to low
    singles = 0         # mask of ranks with count == 1
    present = 0
    for r in range(12, -1, -1):
        n = (key >> (3 * r)) & 7
        if not n:
            continue
        present |= 1 << r
        if n == 4:
            quads = r
        elif n == 3:
            if trips < 0:
                trips = r
            else:
                pairs.append(r)       # a second trips counts as a pair (full house)
        elif n == 2:
            pairs.append(r)
        else:
            singles |= 1 << r
    if quads >= 0:
        return (7 << 20) | (quads << 16) | (_top(present & ~(1 << quads), 1) >> 4)
    if trips >= 0 and pairs:
        return (6 << 20) | (trips << 16) | (pairs[0] << 12)
    sh = _straight_hi(present)
    if sh >= 0:
        return (4 << 20) | (sh << 16)
    if trips >= 0:
        return (3 << 20) | (trips << 16) | (_top(singles, 2) >> 4)
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        return (2 << 20) | (p1 << 16) | (p2 << 12) | (_top(present & ~(1 << p1) & ~(1 << p2), 1) >> 8)
    if pairs:
        return (1 << 20) | (pairs[0] << 16) | (_top(singles, 3) >> 4)
    return _top(present, 5)


def _flush_value(mask):
    sh = _straight_hi(mask)
    if sh >= 0:
        return (8 << 20) | (sh << 16)
    return (5 << 20) | _top(mask, 5)


def eval7(cards):
    """Strength of the best 5-card hand among 5, 6 or 7 distinct card ids (higher is better)."""
    t = 0
    for c in cards:
        t += _K[c]
    sc = t >> 40
    if (sc + 0x3333) & 0x8888:           # some suit nibble >= 5
        s = 0
        while (sc >> (4 * s)) & 15 < 5:
            s += 1
        m = 0
        for c in cards:
            if c & 3 == s:
                m |= 1 << (c >> 2)
        v = _FL.get(m)
        if v is None:
            v = _FL[m] = _flush_value(m)
        return v
    k = t & _RANK_BITS
    v = _NF.get(k)
    if v is None:
        v = _NF[k] = _nonflush(k)
    return v


def warm():
    """Fill both memo tables completely (every 5-7 card rank multiset, every flush mask), so later calls never
    miss. Optional: callers may run it at start-up (uncharged time). Idempotent."""
    from itertools import combinations_with_replacement
    for n in (5, 6, 7):
        for ranks in combinations_with_replacement(range(13), n):
            k = 0
            for r in ranks:
                k += 1 << (3 * r)
            if k not in _NF and all(ranks.count(r) <= 4 for r in set(ranks)):
                _NF[k] = _nonflush(k)
    for m in range(8192):
        if m.bit_count() >= 5 and m.bit_count() <= 7 and m not in _FL:
            _FL[m] = _flush_value(m)


def category(value):
    """Hand category 0..8 of an eval7 value (0 high card ... 8 straight flush)."""
    return value >> 20
