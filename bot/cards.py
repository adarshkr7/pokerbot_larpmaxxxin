"""Card parsing and formatting. Card id = rank * 4 + suit; rank 0..12 = 2..A, suit 0..3 = s h d c."""

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK = {r: i for i, r in enumerate(RANKS)}
SUIT = {s: i for i, s in enumerate(SUITS)}


def is_valid(s):
    """True iff `s` is a card string the engine accepts (e.g. "As", "Td")."""
    return isinstance(s, str) and len(s) == 2 and s[0] in RANK and s[1] in SUIT


def parse(s):
    """"As" -> 48. Raises ValueError on anything that is not a valid card string."""
    if not is_valid(s):
        raise ValueError(f"bad card {s!r}")
    return RANK[s[0]] * 4 + SUIT[s[1]]


def fmt(c):
    """48 -> "As"."""
    return RANKS[c // 4] + SUITS[c % 4]


def parse_valid(cards):
    """Parse a received card list leniently: skip invalid entries and duplicates; non-list -> []."""
    if not isinstance(cards, list):
        return []
    out = []
    for s in cards:
        if is_valid(s):
            c = parse(s)
            if c not in out:
                out.append(c)
    return out


# --- F02 additions: pairs, dead masks, decks ---------------------------------------------------

def pair_index(a, b):
    """Index of the unordered pair {a, b} (a != b) in 0..1325: hi*(hi-1)//2 + lo. Inverse: PAIRS."""
    if a < b:
        return b * (b - 1) // 2 + a
    return a * (a - 1) // 2 + b


PAIRS = [(lo, hi) for hi in range(52) for lo in range(hi)]   # PAIRS[pair_index(a, b)] == (min, max)


def dead_mask(cards):
    """bytearray(52) with the given card ids set; anything that is not an int in 0..51 is ignored."""
    m = bytearray(52)
    for c in cards:
        if isinstance(c, bool):
            continue
        try:
            i = c.__index__()
        except Exception:
            continue
        if 0 <= i < 52:
            m[i] = 1
    return m


def deck_without(dead):
    """Card ids not flagged in `dead` (any length-52 sequence of flags, e.g. HandState.dead)."""
    return [c for c in range(52) if not dead[c]]
