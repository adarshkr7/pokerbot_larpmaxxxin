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
