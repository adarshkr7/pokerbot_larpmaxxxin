"""eval7 vs the engine's rank5 / best_hand (F02 plan 6A) and the cards.py additions (6C)."""
import random
from itertools import combinations, combinations_with_replacement

import pytest

import evaluator
from cards import PAIRS, dead_mask, deck_without, fmt, pair_index, parse
from engine_util import engine
from evaluator import category, eval7


def ids(s):
    return [parse(x) for x in s.split()]


def strs(cards):
    return [fmt(c) for c in cards]


def sign(x):
    return (x > 0) - (x < 0)


# ------------------------------------------------------------------------- 6A1: exhaustive 5-card classes
def five_card_classes():
    hands = []
    for ranks in combinations_with_replacement(range(13), 5):
        if any(ranks.count(r) > 4 for r in ranks):
            continue
        seen = {}
        cards = []
        distinct = len(set(ranks)) == 5
        for i, r in enumerate(ranks):
            if distinct:
                s = i % 4                       # suits 0,1,2,3,0: never a flush
            else:
                s = seen.get(r, 0)              # j-th copy of a rank gets suit j: never a flush
                seen[r] = s + 1
            cards.append(r * 4 + s)
        hands.append(cards)
        if distinct:
            hands.append([r * 4 for r in ranks])   # the same ranks as a flush (spades)
    return hands


def test_exhaustive_five_card_ordering():
    hands = five_card_classes()
    assert len(hands) == 6175 + 1287
    rows = sorted((engine.rank5(strs(h)), eval7(h)) for h in hands)
    assert len({r for r, _ in rows}) == 7462
    assert len({v for _, v in rows}) == 7462
    for (r1, v1), (r2, v2) in zip(rows, rows[1:]):
        assert r1 < r2 and v1 < v2, (r1, r2, v1, v2)


# ------------------------------------------------------------------------- 6A2: random showdowns
# The engine's best_hand runs ~4k 7-card hands/s, so 50k showdowns against it would take ~25 s. Direct engine
# checks use 12k 7-card deals; the 50k-deal check uses "max over the 21 five-card subsets of eval7" as the
# oracle, which is exactly the engine's best_hand ordering because test_exhaustive_five_card_ordering proves that
# eval7 orders every 5-card class as rank5 does (best_hand = max of rank5 over the same subsets).
@pytest.mark.parametrize("board_len, deals", [(5, 12000), (4, 10000), (3, 10000)])
def test_random_showdowns_match_engine(board_len, deals):
    rng = random.Random(1000 + board_len)
    for _ in range(deals):
        a = rng.sample(range(52), 4 + board_len)
        h1, h2, b = a[:2], a[2:4], a[4:]
        e1, e2 = engine.best_hand(strs(h1), strs(b)), engine.best_hand(strs(h2), strs(b))
        e = (e1 > e2) - (e1 < e2)
        f = sign(eval7(h1 + b) - eval7(h2 + b))
        assert e == f, (strs(h1), strs(h2), strs(b))


def test_random_7_card_showdowns_vs_subset_max():
    rng = random.Random(2005)
    for _ in range(50000):
        a = rng.sample(range(52), 9)
        h1, h2, b = a[:2], a[2:4], a[4:]
        o1 = max(eval7(c) for c in combinations(h1 + b, 5))
        o2 = max(eval7(c) for c in combinations(h2 + b, 5))
        assert eval7(h1 + b) == o1 and eval7(h2 + b) == o2, (strs(h1), strs(h2), strs(b))


def test_categories_match_engine_on_random_7_cards():
    rng = random.Random(7)
    for _ in range(5000):
        h = rng.sample(range(52), 7)
        assert category(eval7(h)) == engine.best_hand(strs(h[:2]), strs(h[2:]))[0]


def test_warm_tables_give_identical_values():
    rng = random.Random(8)
    hands = [rng.sample(range(52), rng.choice((5, 6, 7))) for _ in range(3000)]
    cold = [eval7(h) for h in hands]
    evaluator.warm()
    assert [eval7(h) for h in hands] == cold


# ------------------------------------------------------------------------- 6A3: named edge cases
def cmp(a, b):
    return sign(eval7(ids(a)) - eval7(ids(b)))


def test_wheel_straights():
    assert category(eval7(ids("Ah 2s 3d 4c 5h"))) == 4
    assert cmp("Ah 2s 3d 4c 5h", "2h 3s 4d 5c 6h") == -1          # wheel loses to 6-high
    assert cmp("Ah 2s 3d 4c 5h Kd Qd", "Kh Qs Jd 9c 8h 7d 2c") == 1  # wheel beats high card
    sw = eval7(ids("Ah 2h 3h 4h 5h"))
    assert category(sw) == 8
    assert sw < eval7(ids("2h 3h 4h 5h 6h"))                         # steel wheel < 6-high straight flush
    assert sw > eval7(ids("Ks Kh Kd Kc Ah"))                         # ... but beats quads
    assert eval7(ids("Ah 2s 3d 4c 5h 6s")) == eval7(ids("2s 3d 4c 5h 6s"))   # 6-high straight is chosen


def test_board_only_ties():
    board = ids("Ts Js Qd Kc Ah")                                    # broadway on board
    assert eval7(ids("2c 3d") + board) == eval7(ids("4h 5s") + board)
    board = ids("As Ah Ad Ac Kh")                                    # quads + K kicker on board
    assert eval7(ids("2c 3d") + board) == eval7(ids("Qh Qs") + board)
    assert eval7(ids("Kd 2c") + board) == eval7(ids("2d 3c") + board)


def test_full_house_ordering():
    assert cmp("Ks Kh Kd 2c 2h", "Qs Qh Qd Ac Ah") == 1              # trips rank first
    assert cmp("Ks Kh Kd 3c 3h", "Kc Kh Kd 2c 2h") == 1              # then pair rank
    # two trips: higher trips + lower trips as the pair
    v = eval7(ids("9s 9h 9d 5c 5h 5d Ac"))
    assert category(v) == 6 and v == eval7(ids("9s 9h 9d 5c 5h"))
    # trips + two pairs: best pair
    assert eval7(ids("4s 4h 4d Qc Qh 7d 7c")) == eval7(ids("4s 4h 4d Qc Qh"))


def test_flush_vs_straight_and_category_priority():
    assert cmp("2h 7h 9h Jh Kh", "9s Td Jc Qh Ks") == 1             # flush > straight
    assert cmp("2h 3h 4h 5h 7h 6s", "9s Td Jc Qh Ks") == 1          # 6-card: flush beats K-high straight
    assert cmp("8s 8h 8d 2c 2h", "2h 7h 9h Jh Kh") == 1              # full house > flush
    # six cards of one suit: the top five of that suit only
    assert eval7(ids("2h 4h 7h 9h Jh Kh 3c")) == eval7(ids("4h 7h 9h Jh Kh"))
    # straight flush inside the suit beats a higher non-flush straight
    v = eval7(ids("5h 6h 7h 8h 9h Ts 2c"))
    assert category(v) == 8 and v == eval7(ids("5h 6h 7h 8h 9h"))


def test_kickers():
    assert cmp("As Ad Ah Ac 2h 3d Kc", "As Ad Ah Ac Qh Jd Tc") == 1  # quads kicker
    assert cmp("Ks Kh Qd Qc 9h 9d 8c", "Ks Kh Qd Qc 8h 7d 6c") == 1  # third pair plays as kicker (9 > 8)
    assert eval7(ids("Ks Kh Qd Qc 9h 9d 8c")) == eval7(ids("Ks Kh Qd Qc 9h"))
    assert cmp("7s 7h 7d Ac 2h", "7s 7h 7d Kc Qh") == 1
    assert cmp("As Ah Kd Qc 3h", "As Ah Kd Jc Th") == 1
    assert cmp("As Kh Qd Jc 9h", "As Kh Qd Jc 8h") == 1


def test_five_and_six_card_inputs():
    assert category(eval7(ids("2s 2h 5d 9c Kh"))) == 1
    assert category(eval7(ids("2s 2h 5d 5c Kh Kd"))) == 2
    assert eval7(ids("2s 2h 5d 5c Kh Kd")) == eval7(ids("Kh Kd 5d 5c 2s"))


# ------------------------------------------------------------------------- 6C: cards.py additions
def test_pair_index_bijection():
    seen = set()
    for a, b in combinations(range(52), 2):
        i = pair_index(a, b)
        assert i == pair_index(b, a) and 0 <= i < 1326
        assert PAIRS[i] == (a, b)
        seen.add(i)
    assert len(seen) == 1326 == len(PAIRS)


def test_dead_mask_and_deck_without():
    x = [0, 5, 51, 17]
    m = dead_mask(x + [52, -1, "As", None, True])
    assert sorted(i for i in range(52) if m[i]) == sorted(x)
    assert deck_without(m) == [c for c in range(52) if c not in x]
    assert deck_without([False] * 52) == list(range(52))
