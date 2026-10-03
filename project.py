#!/usr/bin/env python3
"""
project.py — quotes, chains, and the ledger, in one place.

What is special is only that the quote lab, the five-sport chain rules,
and the ledger live together: this script, plus data/ledger.xlsx beside
it. That packaging is not an edge. Do not bet real money.

Chain betas are unfitted illustrations. `python project.py fit` can fit a
multinomial logit, but only on synthetic draws, and only if numpy and
scipy import. A coefficient from that generator is not NFL data and not a
price.

The quote lab knows a latent probability. The strategy never sees it. It
sees two-sided American quotes. A fill happens only if that posted price
is still up when the order would arrive. Settlement is one Bernoulli draw
from the latent probability at the end of the path. PnL is the ticket.
CLV is the close implied probability minus the implied price you bet.

Parameters are illustrations. A sim score is not an edge. There is no
sportsbook client and no order placement.

Default: python project.py
  formulas, one chains demo, one Bengals-style sim (n=200), one quote sim.
Optional: python project.py fit --n 1500
"""

from __future__ import annotations

import math
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Formulas (printed by the default command; the code below matches them)
# ---------------------------------------------------------------------------

FORMULAS = """\
z(s,a) = b0 + sum b_f * x_f
P(a|s) = exp(z) / sum exp(z)
ticket: win pays A/100 if A>0 else 100/|A|, loss pays -1
edge = p_hat - implied(American price); fire only if edge >= 0.03 and spread cover uses p>=0.58 and |spread|<10
calibrate: p' = 0.5 + (p-0.5)*shrink
"""

EDGE_MIN = 0.03
SIGMA_MAX = 0.03
SPREAD_MIN_P = 0.58
SPREAD_ABS_MAX = 10.0  # absolute spread must be under 10


def print_formulas() -> None:
    print(FORMULAS, end="")


# ---------------------------------------------------------------------------
# American odds, tickets, devig
# ---------------------------------------------------------------------------

def american_to_implied(price: float) -> float:
    price = float(price)
    if price == 0:
        raise ValueError("American price cannot be 0")
    if price > 0:
        return 100.0 / (price + 100.0)
    return (-price) / ((-price) + 100.0)


def implied(price):
    """Same conversion. None stays None so the chain rule can refuse it."""
    if price is None:
        return None
    return american_to_implied(price)


def implied_to_american(p: float) -> int:
    p = float(p)
    if not 0.0 < p < 1.0:
        raise ValueError("implied probability must be in (0, 1)")
    if p >= 0.5:
        return int(round(-100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


def ticket_payoff(american: float, win: bool) -> float:
    """1-unit stake. Win pays A/100 if A>0 else 100/|A|. Loss pays -1."""
    if not win:
        return -1.0
    american = float(american)
    if american > 0:
        return american / 100.0
    if american < 0:
        return 100.0 / abs(american)
    raise ValueError("American price cannot be 0")


def ticket_ev(p_side: float, american: float) -> float:
    """Expected ticket PnL at p_side. The posted price already includes hold."""
    return p_side * ticket_payoff(american, True) + (1.0 - p_side) * (-1.0)


def devig_two_way(q_home: float, q_away: float) -> Tuple[float, float]:
    total = q_home + q_away
    if total <= 0:
        raise ValueError("implied probabilities must be positive")
    return q_home / total, q_away / total


def quotes_from_fair(fair_home: float, hold: float) -> Tuple[int, int]:
    """Post both sides so the raw implied probabilities sum to 1+hold."""
    fair_home = min(0.90, max(0.10, fair_home))
    q_home = fair_home * (1.0 + hold)
    q_away = (1.0 - fair_home) * (1.0 + hold)
    return implied_to_american(q_home), implied_to_american(q_away)


# ---------------------------------------------------------------------------
# Quote lab
# ---------------------------------------------------------------------------

# Noise is already in probability units (a few points, not basis points).
DEFAULT_BOOKS = (
    {"name": "pine", "latency_ms": 40, "noise": 0.015, "threshold": 0.008, "hold": 0.040},
    {"name": "cedar", "latency_ms": 80, "noise": 0.018, "threshold": 0.010, "hold": 0.045},
    {"name": "oak", "latency_ms": 120, "noise": 0.020, "threshold": 0.010, "hold": 0.045},
    {"name": "ash", "latency_ms": 300, "noise": 0.025, "threshold": 0.015, "hold": 0.050},
    {"name": "elm", "latency_ms": 700, "noise": 0.030, "threshold": 0.020, "hold": 0.050},
    {"name": "yew", "latency_ms": 1500, "noise": 0.035, "threshold": 0.025, "hold": 0.055},
)
OWN_LATENCY_MS = 250  # slower than the fastest book, so the default can lose


def default_noises() -> List[float]:
    return [b["noise"] for b in DEFAULT_BOOKS]


def consensus_sigma(noises, freshness=None) -> float:
    """Inverse-variance sigma of a freshness-weighted mean, in probability.

    Weight is freshness / noise^2. Noise is already a probability, so it is
    not scaled by 1e4. With equal freshness this is 1/sqrt(sum 1/noise^2).
    """
    noises = list(noises)
    if not noises:
        return float("inf")
    if freshness is None:
        freshness = [1.0] * len(noises)
    weights = []
    for fresh, noise in zip(freshness, noises):
        if noise <= 0:
            raise ValueError("noise must be positive")
        weights.append(max(0.0, float(fresh)) / (float(noise) ** 2))
    wsum = sum(weights)
    if wsum <= 0:
        return float("inf")
    var = 0.0
    for w, noise in zip(weights, noises):
        var += (w / wsum) ** 2 * (float(noise) ** 2)
    return math.sqrt(var)


def weighted_mean(values, noises, freshness):
    weights = [max(0.0, f) / (n ** 2) for f, n in zip(freshness, noises)]
    wsum = sum(weights)
    if wsum <= 0:
        raise ValueError("no weight")
    mean = sum(w * v for w, v in zip(weights, values)) / wsum
    return mean, consensus_sigma(noises, freshness)


def decide_side(book: dict, p_hat: float, sigma: float, edge_min: float = EDGE_MIN) -> dict:
    """Pick a side from posted American prices. Never reads a latent probability.

    `book` is {"home": american, "away": american}. p_hat is P(home) from
    other books. Either side can fire. A fire needs edge >= edge_min, a
    positive ticket EV at the posted price (hold is already in that price),
    and leave-one-out sigma at or under 0.03.
    """
    home_price = book["home"]
    away_price = book["away"]
    candidates = []
    for side, p_side, price in (
        ("home", p_hat, home_price),
        ("away", 1.0 - p_hat, away_price),
    ):
        imp = american_to_implied(price)
        edge = p_side - imp
        ev = ticket_ev(p_side, price)
        candidates.append({
            "side": side,
            "price": int(price),
            "p_side": p_side,
            "implied": imp,
            "edge": edge,
            "ev": ev,
        })
    fires = [
        c for c in candidates
        if c["edge"] >= edge_min and c["ev"] > 0.0 and sigma <= SIGMA_MAX
    ]
    if fires:
        chosen = max(fires, key=lambda c: c["edge"])
        chosen["fire"] = True
    else:
        chosen = max(candidates, key=lambda c: (c["edge"], c["ev"]))
        chosen["fire"] = False
    chosen["sigma"] = sigma
    chosen["reason"] = None
    if not chosen["fire"]:
        if sigma > SIGMA_MAX:
            chosen["reason"] = "sigma"
        elif chosen["ev"] <= 0.0:
            chosen["reason"] = "negative_ev"
        elif chosen["edge"] < edge_min:
            chosen["reason"] = "edge"
        else:
            chosen["reason"] = "no_fire"
    return chosen


def sim(seed: int = 20261003, own_latency_ms: int = OWN_LATENCY_MS,
        steps: int = 240, dt_ms: int = 50) -> dict:
    """One event. The strategy sees posted American prices only."""
    rng = random.Random(seed)
    p = 0.50
    path = []
    for _ in range(steps):
        p = min(0.90, max(0.10, p + rng.gauss(0.0, 0.012)))
        path.append(p)

    books = []
    for spec in DEFAULT_BOOKS:
        books.append({
            "name": spec["name"],
            "latency_ms": spec["latency_ms"],
            "noise": spec["noise"],
            "threshold": spec["threshold"],
            "hold": spec["hold"],
            "fair": None,
            "home": None,
            "away": None,
            "updated_at": None,
            "moves": [],
        })

    timeline = []
    for t in range(steps):
        row = []
        for b in books:
            delay = b["latency_ms"] // dt_ms
            if t >= delay:
                obs = path[t - delay] + rng.gauss(0.0, b["noise"])
                obs = min(0.90, max(0.10, obs))
                if b["fair"] is None or abs(obs - b["fair"]) >= b["threshold"]:
                    home, away = quotes_from_fair(obs, b["hold"])
                    b["fair"] = obs
                    b["home"] = home
                    b["away"] = away
                    b["updated_at"] = t
                    b["moves"].append(t)
            row.append({
                "home": b["home"],
                "away": b["away"],
                "updated_at": b["updated_at"],
                "noise": b["noise"],
                "name": b["name"],
            })
        timeline.append(row)

    signals = []
    attempted = set()
    window = max(1, 1000 // dt_ms)
    own_delay = max(1, own_latency_ms // dt_ms)

    for t in range(steps):
        row = timeline[t]
        live = [i for i, q in enumerate(row) if q["home"] is not None]
        if len(live) < 4:
            continue
        movers = set()
        for j in live:
            for mt in books[j]["moves"]:
                if 0 <= t - mt <= window:
                    movers.add(j)
                    break
        for i in live:
            others = [j for j in live if j != i]
            freshness = []
            noises = []
            fairs = []
            for j in others:
                o = row[j]
                age_ms = (t - o["updated_at"]) * dt_ms
                freshness.append(math.exp(-age_ms / 800.0))
                noises.append(o["noise"])
                qh = american_to_implied(o["home"])
                qa = american_to_implied(o["away"])
                fair_h, _fair_a = devig_two_way(qh, qa)
                fairs.append(fair_h)
            p_hat, sigma = weighted_mean(fairs, noises, freshness)
            q = row[i]
            decision = decide_side({"home": q["home"], "away": q["away"]}, p_hat, sigma)
            if decision["edge"] < EDGE_MIN:
                continue
            key = (i, decision["side"], decision["price"])
            if key in attempted:
                continue
            attempted.add(key)
            decision["book"] = q["name"]
            decision["book_index"] = i
            decision["t"] = t
            decision["steam"] = len(movers)  # distinct books, not repeated ticks
            signals.append(decision)

    fires = [s for s in signals if s["fire"]]
    filled = []
    for s in fires:
        arrive = s["t"] + own_delay
        s["filled"] = False
        if arrive >= steps:
            continue
        moved = any(s["t"] < mt <= arrive for mt in books[s["book_index"]]["moves"])
        price_then = timeline[arrive][s["book_index"]][s["side"]]
        if moved or price_then != s["price"]:
            continue
        close = timeline[-1][s["book_index"]][s["side"]]
        s["filled"] = True
        s["close"] = close
        s["clv"] = american_to_implied(close) - american_to_implied(s["price"])
        filled.append(s)

    home_wins = rng.random() < path[-1]
    by_side = {
        "home": {"fills": 0, "hits": 0, "pnl": 0.0},
        "away": {"fills": 0, "hits": 0, "pnl": 0.0},
    }
    for s in filled:
        won = home_wins if s["side"] == "home" else (not home_wins)
        s["win"] = won
        s["pnl"] = ticket_payoff(s["price"], won)
        by_side[s["side"]]["fills"] += 1
        by_side[s["side"]]["hits"] += int(won)
        by_side[s["side"]]["pnl"] += s["pnl"]

    n_sig = len(signals)
    n_fire = len(fires)
    n_fill = len(filled)
    return {
        "signals": n_sig,
        "fires": n_fire,
        "fills": n_fill,
        "skips": n_sig - n_fill,
        "mean_edge": (sum(s["edge"] for s in signals) / n_sig) if n_sig else 0.0,
        "mean_clv": (sum(s["clv"] for s in filled) / n_fill) if n_fill else 0.0,
        "mean_pnl": (sum(s["pnl"] for s in filled) / n_fill) if n_fill else 0.0,
        "hit_rate": (sum(1 for s in filled if s["win"]) / n_fill) if n_fill else 0.0,
        "total_pnl": sum(s["pnl"] for s in filled),
        "by_side": by_side,
        "max_steam": max((s["steam"] for s in signals), default=0),
        "home_wins": home_wins,
        "p_end": path[-1],
    }


def format_quote_report(result: dict) -> str:
    lines = [
        "QUOTE LAB",
        "signals {signals}  fires {fires}  fills {fills}  skips {skips}".format(**result),
        "mean edge at decision (probability) {mean_edge:.4f}".format(**result),
        "mean CLV on fills {mean_clv:.4f}".format(**result),
        "mean ticket PnL per filled bet {mean_pnl:.4f}  hit rate {hit_rate:.3f}  total PnL {total_pnl:.4f}".format(**result),
        "by side",
    ]
    for side in ("home", "away"):
        s = result["by_side"][side]
        lines.append(
            "  {side}: fills {fills}  hits {hits}  pnl {pnl:.4f}".format(side=side, **s)
        )
    lines.append(
        "steam counts distinct books in the window (max at a signal: {max_steam})".format(**result)
    )
    lines.append("a positive number on this generator is not evidence of an edge")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Chains. Unfitted betas. "bet": true only means the rule printed.
# ---------------------------------------------------------------------------

def softmax(xs):
    m = max(xs)
    ex = [math.exp(x - m) for x in xs]
    s = sum(ex)
    return [e / s for e in ex]


def pick(actions, ps, rng):
    r = rng.random()
    cum = 0.0
    chosen = actions[-1]
    for a, p in zip(actions, ps):
        cum += p
        if r <= cum:
            return a
    return chosen


def edge_step(table, state, x, rng):
    actions = list(table[state])
    ps = softmax([
        table[state][a]["beta0"] + sum(
            table[state][a].get(f, 0.0) * x.get(f, 0.0) for f in x
        )
        for a in actions
    ])
    return pick(actions, ps, rng)


def calibrate(p, shrink=0.45):
    """p' = 0.5 + (p-0.5)*shrink. A raw sim rate is not a probability."""
    return 0.5 + (p - 0.5) * shrink


def allow(kind, p, price=None, spread=None, under_implied=None):
    """Rule that matches the header, not the old 0.56 / totals-off code.

    total: under's implied within 0.02 of 0.50, then the same +0.03 price test.
    spread: calibrated cover >= 0.58 and absolute spread under 10.
    winner: calibrated p >= implied(price) + 0.03.
    """
    if kind == "total":
        under = under_implied if under_implied is not None else implied(price)
        if under is None or abs(under - 0.50) > 0.02:
            return False
        be = implied(price)
        return be is not None and p >= be + 0.03
    if kind == "spread":
        if spread is None or abs(spread) >= SPREAD_ABS_MAX:
            return False
        return p >= SPREAD_MIN_P
    if kind == "winner":
        be = implied(price)
        return be is not None and p >= be + 0.03
    return False


def decide_winner(raw, price, shrink=0.5):
    """Hockey/winner helper. The bet uses calibrated p, not the raw sim rate."""
    p = calibrate(raw, shrink)
    be = implied(price)
    return {
        "raw": raw,
        "p": p,
        "win": p,
        "edge": None if be is None else p - be,
        "bet": allow("winner", p, price),
    }


FB = {
    "OPEN": {"CHUNK": {"beta0": 0.1, "secondary_stress": 0.8, "late_trailing": 0.4},
             "NO_EVENT": {"beta0": 0.0, "pressure_edge": 0.3}},
    "CHUNK": {"SCORE": {"beta0": -0.2, "secondary_stress": 0.6, "yac_env": 0.4},
              "FAIL": {"beta0": 0.1, "pressure_edge": 0.5}},
}


def fb_drive(x, rng):
    state = "OPEN"
    for _ in range(4):
        nxt = edge_step(FB, state, x, rng)
        if nxt in ("SCORE", "FAIL", "NO_EVENT"):
            return nxt
        state = nxt
    return "FAIL"


def football(dog_score, fav_score, quarter, mins_left, live_spread, pregame_spread,
             stress, n=4000, seed=20261003):
    rng = random.Random(seed)
    margin = fav_score - dog_score
    if quarter <= 2 and margin >= 17:
        return {"kill": True, "reason": "favorite up 17+ before half"}
    if live_spread + 0.5 < pregame_spread:
        return {"kill": True, "reason": "live number worse than pregame dog"}
    poss = max(1, int(round(max(0.4, ((4 - quarter) * 15 + mins_left) / 6.5))))
    covers = 0
    for _ in range(n):
        trail = max(0.0, min(1.0, margin / 17))
        xd = {"pressure_edge": 0.3, "yac_env": 0.35 + 0.15 * trail,
              "secondary_stress": stress, "late_trailing": trail}
        xf = {"pressure_edge": -0.05, "yac_env": 0.4,
              "secondary_stress": 0.15, "late_trailing": 0.0}
        d, f = dog_score, fav_score
        for _p in range(poss):
            if fb_drive(xd, rng) == "SCORE":
                d += 5.6
            if fb_drive(xf, rng) == "SCORE":
                f += 6.0
        noise = 3.2 * math.sqrt(poss / 4)
        d = max(0, rng.gauss(d, noise))
        f = max(0, rng.gauss(f, noise))
        if d + live_spread >= f:
            covers += 1
    p = calibrate(covers / n)
    return {
        "kill": False,
        "cover": p,
        "raw": covers / n,
        "bet": allow("spread", p, spread=live_spread) and live_spread + 0.5 >= pregame_spread,
    }


BB = {
    "INNING": {"EMPTY": {"beta0": 0.4, "starter_edge": 0.3},
               "RUNNER": {"beta0": -0.2, "starter_edge": -0.8}},
    "EMPTY": {"K": {"beta0": 0.1, "starter_edge": 0.9},
              "BB": {"beta0": -0.8, "starter_edge": -0.6},
              "INPLAY": {"beta0": 0.2, "park": 0.3}},
    "RUNNER": {"K": {"beta0": -0.1, "starter_edge": 0.7},
               "BB": {"beta0": -0.4, "starter_edge": -0.5},
               "INPLAY": {"beta0": 0.35, "park": 0.25}},
    "INPLAY": {"OUT": {"beta0": 0.55, "starter_edge": 0.4},
               "SCORE": {"beta0": -0.7, "starter_edge": -0.8, "park": 0.5}},
}


def half(x, rng):
    runs = outs = 0
    state = "INNING"
    for _ in range(12):
        if outs >= 3:
            break
        nxt = edge_step(BB, state, x, rng)
        if nxt in ("EMPTY", "RUNNER"):
            state = nxt
        elif nxt == "K" or nxt == "OUT":
            outs += 1
            state = "INNING"
        elif nxt == "BB":
            state = "RUNNER"
        elif nxt == "INPLAY":
            state = "INPLAY"
        elif nxt == "SCORE":
            runs += 1
            state = "INNING"
    return runs


def baseball(dog_score, fav_score, inning, dog_starter, fav_starter, price,
             n=4000, seed=20261003):
    rng = random.Random(seed)
    wins = 0
    for _ in range(n):
        d, f = dog_score, fav_score
        for inn in range(inning, 10):
            d += half({"starter_edge": fav_starter if inn <= 5 else 0.05, "park": 0.1}, rng)
            f += half({"starter_edge": dog_starter if inn <= 5 else -0.1, "park": 0.1}, rng)
        if d > f:
            wins += 1
    p = calibrate(wins / n, 0.55)
    be = implied(price)
    return {"win": p, "edge": p - be, "bet": allow("winner", p, price)}


HK = {
    "SHIFT": {"EVEN": {"beta0": 1.2, "power_play": -2.0},
              "POWER": {"beta0": -1.4, "power_play": 2.2}},
    "EVEN": {"SHOT": {"beta0": -0.2, "shot_edge": 0.8, "goalie": -0.5},
             "MISS": {"beta0": 0.3, "goalie": 0.3}},
    "POWER": {"SHOT": {"beta0": 0.4, "shot_edge": 0.6},
              "MISS": {"beta0": -0.2, "goalie": 0.4}},
    "SHOT": {"SAVE": {"beta0": 0.9, "goalie": 1.1},
             "SCORE": {"beta0": -1.3, "shot_edge": 0.7, "goalie": -1.0}},
}


def period(x, rng, shifts=18):
    goals = 0
    state = "SHIFT"
    for _ in range(shifts):
        nxt = edge_step(HK, state, x, rng)
        if nxt in ("EVEN", "POWER", "SHOT"):
            state = nxt
        elif nxt == "SCORE":
            goals += 1
            state = "SHIFT"
        else:
            state = "SHIFT"
    return goals


def hockey(dog_shot, fav_shot, dog_goalie, fav_goalie, price, n=3000, seed=20261003):
    rng = random.Random(seed)
    wins = 0
    for _ in range(n):
        d = f = 0
        for _p in range(3):
            d += period({"shot_edge": dog_shot, "goalie": fav_goalie, "power_play": 0.15}, rng)
            f += period({"shot_edge": fav_shot, "goalie": dog_goalie, "power_play": 0.2}, rng)
        if d > f:
            wins += 1
    raw = wins / n
    # Calibrated probability, not the raw sim rate.
    decided = decide_winner(raw, price, shrink=0.5)
    return {"win": decided["win"], "raw": raw, "edge": decided["edge"], "bet": decided["bet"]}


def fight(edge, finish, price, n=4000, seed=20261003):
    rng = random.Random(seed)
    wins = 0
    for _ in range(n):
        a = b = 0
        ended = False
        p_a = 1 / (1 + math.exp(-edge))
        for _r in range(3):
            if ended:
                break
            if rng.random() < p_a:
                a += 1
                if rng.random() < finish * 0.22:
                    a += 2
                    ended = True
            else:
                b += 1
                if rng.random() < finish * 0.18:
                    b += 2
                    ended = True
        if a > b or (a == b and rng.random() < p_a):
            wins += 1
    p = calibrate(wins / n, 0.6)
    be = implied(price)
    return {"win": p, "edge": p - be, "bet": allow("winner", p, price)}


NB = {
    "POSSESS": {
        "RIM": {"beta0": 0.15, "shot_edge": 0.4, "rim_pressure": -0.5},
        "THREE": {"beta0": 0.05, "three_env": 0.6},
        "TURNOVER": {"beta0": -0.8, "rim_pressure": 0.5},
    },
    "RIM": {"SCORE": {"beta0": 0.35, "shot_edge": 0.7},
            "FAIL": {"beta0": -0.1, "rim_pressure": 0.6}},
    "THREE": {"SCORE": {"beta0": -0.55, "three_env": 0.5},
              "FAIL": {"beta0": 0.4}},
}


def trip(x, rng):
    state = "POSSESS"
    for _ in range(3):
        nxt = edge_step(NB, state, x, rng)
        if nxt == "TURNOVER" or nxt == "FAIL":
            return 0
        if nxt in ("RIM", "THREE"):
            state = nxt
            continue
        if nxt == "SCORE":
            return 3 if state == "THREE" else 2
    return 0


def basketball(spread, dog_shot, fav_shot, n=3000, seed=20261003):
    rng = random.Random(seed)
    covers = 0
    for _ in range(n):
        d = f = 0
        for _p in range(100):
            d += trip({"shot_edge": dog_shot, "rim_pressure": fav_shot * 0.4, "three_env": 0.3}, rng)
            f += trip({"shot_edge": fav_shot, "rim_pressure": dog_shot * 0.3, "three_env": 0.3}, rng)
        if d + spread >= f:
            covers += 1
    p = calibrate(covers / n, 0.5)
    return {"cover": p, "bet": allow("spread", p, spread=spread)}


def chains_demo(seed=20261003, n_scale=1.0) -> None:
    print('betas are unfitted; "bet": true means the rule printed, not that you should bet.')
    def scaled(n):
        return max(1, int(round(n * n_scale)))

    print("FOOTBALL")
    fb = football(6, 17, 3, 14, 18.5, 14.5, 0.25, n=scaled(4000), seed=seed)
    print(" Iowa +18.5", fb)
    print("BASEBALL")
    print(" Yankees +118", baseball(0, 0, 1, 0.15, 0.35, 118, n=scaled(4000), seed=seed))
    print(" Padres +171", baseball(0, 0, 1, -0.15, 0.70, 171, n=scaled(4000), seed=seed))
    print("NHL")
    print(" Washington +165", hockey(0.30, 0.20, 0.25, 0.15, 165, n=scaled(3000), seed=seed))
    print(" Utah +110", hockey(0.10, 0.05, 0.15, 0.05, 110, n=scaled(3000), seed=seed))
    print(" Devils -115", hockey(0.25, 0.10, 0.20, 0.05, -115, n=scaled(3000), seed=seed))
    print(" Dallas -143", hockey(0.35, 0.05, 0.30, 0.05, -143, n=scaled(3000), seed=seed))
    print("UFC")
    print(" Silva -205", fight(0.55, 0.35, -205, n=scaled(4000), seed=seed))
    print("NBA")
    print(" Raptors +1.5", basketball(1.5, 0.18, 0.22, n=scaled(3000), seed=seed))


# ---------------------------------------------------------------------------
# Bengals-style chain sim. Illustrative gates, not a forecast.
# ---------------------------------------------------------------------------

@dataclass
class Transition:
    to: str
    p: float
    points: float = 0.0


@dataclass
class ChainDef:
    name: str
    owner: str
    start_state: str
    absorb: Tuple[str, ...]
    graph: Dict[str, List[Transition]]
    suppress_if_gate: Optional[str] = None
    amplify_if_gate_off: Optional[str] = None
    suppress_factor: float = 0.55
    amplify_factor: float = 1.35

    def scaled_graph(self, gates_on: Dict[str, bool]) -> Dict[str, List[Transition]]:
        g = {}
        for state, edges in self.graph.items():
            new_edges = []
            for e in edges:
                p = e.p
                if state == self.start_state and e.to not in ("NO_EVENT",) and e.to not in self.absorb:
                    if self.suppress_if_gate and gates_on.get(self.suppress_if_gate, False):
                        p *= self.suppress_factor
                    if self.amplify_if_gate_off and not gates_on.get(self.amplify_if_gate_off, True):
                        p *= self.amplify_factor
                new_edges.append(Transition(e.to, p, e.points))
            s = sum(e.p for e in new_edges)
            if s > 0:
                new_edges = [Transition(e.to, e.p / s, e.points) for e in new_edges]
            g[state] = new_edges
        return g


@dataclass
class Gate:
    name: str
    p_realize: float
    owner: str
    direct_points: float = 0.0


def football_round(x: float) -> int:
    buckets = [0, 3, 6, 7, 9, 10, 13, 14, 16, 17, 20, 21, 23, 24, 27, 28, 30, 31, 34, 35, 38, 41, 42, 45, 48]
    return min(buckets, key=lambda b: abs(b - x))


def half_life_weight(games_ago: int, half_life: float = 1.4) -> float:
    return 0.5 ** (games_ago / half_life)


def walk(graph, start, absorb, rng, max_steps=14):
    state = start
    path = [state]
    pts = 0.0
    for _ in range(max_steps):
        if state in absorb:
            break
        edges = graph[state]
        r = rng.random()
        cum = 0.0
        chosen = edges[-1]
        for e in edges:
            cum += e.p
            if r <= cum:
                chosen = e
                break
        state = chosen.to
        pts += chosen.points
        path.append(state)
    return path, pts, state


jax_scores = [34, 35, 24]
jax_allowed = [20, 17, 28]
cin_scores = [33, 27, 27]
cin_allowed = [27, 20, 30]
_w = [half_life_weight(2 - i) for i in range(3)]
_ws = sum(_w)
jax_off = sum(s * wt for s, wt in zip(jax_scores, _w)) / _ws
cin_off = sum(s * wt for s, wt in zip(cin_scores, _w)) / _ws
jax_def = sum(s * wt for s, wt in zip(jax_allowed, _w)) / _ws
cin_def = sum(s * wt for s, wt in zip(cin_allowed, _w)) / _ws

GATES = [
    Gate("cin_skill_explosion", p_realize=0.52, owner="CIN", direct_points=2.4),
    Gate("jax_efficiency_holds", p_realize=0.48, owner="JAX", direct_points=2.2),
    Gate("cin_pass_rush", p_realize=0.45, owner="CIN", direct_points=1.6),
    Gate("shootout_env", p_realize=0.60, owner="JAX", direct_points=1.2),
    Gate("cin_secondary_thin", p_realize=0.72, owner="JAX", direct_points=2.0),
    Gate("cin_ol_stress", p_realize=0.40, owner="JAX", direct_points=1.3),
    Gate("jax_cb_questionable", p_realize=0.35, owner="CIN", direct_points=1.1),
]

CHAINS = [
    ChainDef(
        name="burrow_chase",
        owner="CIN",
        start_state="OPEN",
        absorb=("SCORE", "FAIL", "NO_EVENT"),
        suppress_if_gate=None,
        amplify_if_gate_off="jax_cb_questionable",
        amplify_factor=0.85,
        graph={
            "OPEN": [Transition("CLEAN", 0.44), Transition("NO_EVENT", 0.56)],
            "CLEAN": [Transition("CHUNK", 0.50), Transition("ORDINARY", 0.50)],
            "CHUNK": [Transition("SCORE", 0.58, points=6.2), Transition("FAIL", 0.42)],
            "ORDINARY": [Transition("SCORE", 0.30, points=3.6), Transition("FAIL", 0.70)],
        },
    ),
    ChainDef(
        name="lawrence_drive",
        owner="JAX",
        start_state="OPEN",
        absorb=("SCORE", "FAIL", "NO_EVENT"),
        suppress_if_gate="cin_pass_rush",
        amplify_if_gate_off="cin_pass_rush",
        suppress_factor=0.58,
        amplify_factor=1.30,
        graph={
            "OPEN": [Transition("SUSTAIN", 0.42), Transition("NO_EVENT", 0.58)],
            "SUSTAIN": [Transition("REDZONE", 0.55), Transition("MIDFIELD_DIE", 0.45)],
            "REDZONE": [Transition("SCORE", 0.62, points=6.0), Transition("FAIL", 0.38)],
            "MIDFIELD_DIE": [Transition("SCORE", 0.12, points=2.8), Transition("FAIL", 0.88)],
        },
    ),
    ChainDef(
        name="jax_vs_thin_secondary",
        owner="JAX",
        start_state="OPEN",
        absorb=("SCORE", "FAIL", "NO_EVENT"),
        suppress_if_gate=None,
        graph={
            "OPEN": [Transition("CHUNK", 0.38), Transition("NO_EVENT", 0.62)],
            "CHUNK": [Transition("SCORE", 0.52, points=5.8), Transition("FAIL", 0.48)],
        },
    ),
    ChainDef(
        name="takeaway_either",
        owner="CIN",
        start_state="OPEN",
        absorb=("SCORE_CIN", "SCORE_JAX", "FAIL", "NO_EVENT"),
        graph={
            "OPEN": [
                Transition("CIN_TAKE", 0.16),
                Transition("JAX_TAKE", 0.14),
                Transition("NO_EVENT", 0.70),
            ],
            "CIN_TAKE": [Transition("SCORE_CIN", 0.58, points=5.8), Transition("FAIL", 0.42)],
            "JAX_TAKE": [Transition("SCORE_JAX", 0.55, points=5.8), Transition("FAIL", 0.45)],
        },
    ),
]


def boom_probability() -> float:
    off_quality = 0.72
    total_env = 0.75
    secondary_chaos = 0.68
    raw = (off_quality * total_env * secondary_chaos) ** (1 / 3)
    return 0.35 + 0.42 * raw


def base_means() -> Tuple[float, float]:
    mu_cin = 0.60 * cin_off + 0.40 * jax_def + 1.5
    mu_jax = 0.60 * jax_off + 0.40 * cin_def - 0.8
    return mu_cin, mu_jax


@dataclass
class Scenario:
    force_gates: Dict[str, Optional[bool]] = field(default_factory=dict)
    disable_chains: List[str] = field(default_factory=list)
    name: str = "baseline"


def one_trial(scenario: Scenario, p_boom: float, rng: random.Random) -> dict:
    mu_cin, mu_jax = base_means()
    gates_on = {}
    for g in GATES:
        if g.name in scenario.force_gates and scenario.force_gates[g.name] is not None:
            on = bool(scenario.force_gates[g.name])
        else:
            on = rng.random() < g.p_realize
        gates_on[g.name] = on
        if on:
            if g.owner == "CIN":
                mu_cin += g.direct_points
                mu_jax -= g.direct_points * 0.22
            else:
                mu_jax += g.direct_points
                mu_cin -= g.direct_points * 0.22

    chain_pts = {"CIN": 0.0, "JAX": 0.0}
    chain_scored = {}
    for ch in CHAINS:
        if ch.name in scenario.disable_chains:
            chain_scored[ch.name] = False
            continue
        graph = ch.scaled_graph(gates_on)
        if ch.name == "jax_vs_thin_secondary" and not gates_on.get("cin_secondary_thin", False):
            graph = {
                "OPEN": [Transition("CHUNK", 0.12), Transition("NO_EVENT", 0.88)],
                "CHUNK": [Transition("SCORE", 0.40, points=5.0), Transition("FAIL", 0.60)],
            }
        _path, pts, terminal = walk(graph, ch.start_state, ch.absorb, rng)
        if ch.name == "takeaway_either":
            if terminal == "SCORE_CIN":
                chain_pts["CIN"] += pts
                chain_scored[ch.name] = True
            elif terminal == "SCORE_JAX":
                chain_pts["JAX"] += pts
                chain_scored[ch.name] = True
            else:
                chain_scored[ch.name] = False
        else:
            chain_pts[ch.owner] += pts
            chain_scored[ch.name] = terminal in ("SCORE", "SCORE_CIN", "SCORE_JAX")

    mu_cin += chain_pts["CIN"]
    mu_jax += chain_pts["JAX"]
    boom = rng.random() < p_boom
    if boom:
        mu_cin += 3.5
        mu_jax += 3.4
        sd = 9.2
    else:
        sd = 7.5
    script = rng.gauss(0, 2.3)
    c = max(0.0, rng.gauss(mu_cin + script * 0.10, sd))
    j = max(0.0, rng.gauss(mu_jax - script * 0.10, sd))
    return {
        "cin": football_round(c),
        "jax": football_round(j),
        "gates": gates_on,
        "chain_scored": chain_scored,
        "boom": boom,
    }


def bengals_simulate(scenario: Scenario, n: int = 200, seed: int = 20261004) -> dict:
    rng = random.Random(seed)
    p_boom = boom_probability()
    cin_w = jax_w = ties = 0
    dog = under = 0
    gate_rates = Counter()
    chain_rates = Counter()
    cins, jaxs = [], []
    for _ in range(n):
        t = one_trial(scenario, p_boom, rng)
        cins.append(t["cin"])
        jaxs.append(t["jax"])
        if t["cin"] > t["jax"]:
            cin_w += 1
        elif t["jax"] > t["cin"]:
            jax_w += 1
        else:
            ties += 1
        if t["jax"] + 2.5 >= t["cin"]:
            dog += 1
        if t["cin"] + t["jax"] < 51.5:
            under += 1
        for g, on in t["gates"].items():
            if on:
                gate_rates[g] += 1
        for c, scored in t["chain_scored"].items():
            if scored:
                chain_rates[c] += 1
    cin_wp = cin_w / n
    # A constant written in the file. Not a live price.
    stated_market = 0.56
    return {
        "scenario": scenario.name,
        "n": n,
        "cin_win": cin_wp,
        "jax_win": jax_w / n,
        "tie": ties / n,
        "mean_cin": sum(cins) / n,
        "mean_jax": sum(jaxs) / n,
        "dog_cover": dog / n,
        "under": under / n,
        "p_boom": p_boom,
        "gate_rates": {k: v / n for k, v in gate_rates.items()},
        "chain_score_rates": {k: v / n for k, v in chain_rates.items()},
        "stated_market_cin": stated_market,
        "abs_gap": abs(cin_wp - stated_market),
    }


def bengals_demo(n: int = 200, seed: int = 20261004) -> dict:
    print("BENGALS-STYLE SIM n={}".format(n))
    print("Illustrative gates and chains. Not a forecast and not an edge.")
    out = bengals_simulate(Scenario(name="baseline_with_outs"), n=n, seed=seed)
    print("scenario {}  boom prior {:.3f}".format(out["scenario"], out["p_boom"]))
    print("Bengals win {:5.1f}%   Jaguars win {:5.1f}%   tie {:5.1f}%".format(
        out["cin_win"] * 100, out["jax_win"] * 100, out["tie"] * 100))
    print("mean score CIN {:.1f}  JAX {:.1f}".format(out["mean_cin"], out["mean_jax"]))
    print("JAX +2.5 cover rate {:5.1f}%   under 51.5 rate {:5.1f}%".format(
        out["dog_cover"] * 100, out["under"] * 100))
    print("absolute gap vs the constant 0.56 written in this file: {:.1f} points".format(
        out["abs_gap"] * 100))
    print("That gap is generator output. It is not an edge.")
    return out


# ---------------------------------------------------------------------------
# Optional fitter. Synthetic draws only. Numpy/scipy or a clean skip.
# ---------------------------------------------------------------------------

FEATURE_NAMES = [
    "pressure_edge", "yac_env", "secondary_stress", "ol_stress",
    "short_week_road", "backup_qb", "home", "shootout", "tilt", "late_trailing",
]


def cmd_fit(argv: List[str]) -> int:
    n = 1500
    args = list(argv)
    if "--n" in args:
        n = int(args[args.index("--n") + 1])
    elif args[:1] and args[0].isdigit():
        n = int(args[0])
    try:
        import numpy as np
        from scipy.optimize import minimize
    except ImportError:
        print("numpy/scipy are not installed; skipping fit.")
        print("The fitter uses synthetic draws, not NFL data. Nothing was written.")
        return 0

    from pathlib import Path

    print("Synthetic multinomial logit. These draws are not NFL play-by-play.")
    print("Generating {} synthetic observations...".format(n))

    def sigmoid(x):
        return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))

    def sample_features(regime: str):
        if regime == "clean_pocket_home":
            return {
                "pressure_edge": np.random.uniform(-0.6, -0.1),
                "yac_env": np.random.uniform(0.3, 0.7),
                "secondary_stress": np.random.uniform(0.0, 0.4),
                "ol_stress": np.random.uniform(0.0, 0.25),
                "short_week_road": 0.0,
                "backup_qb": 0.0,
                "home": np.random.uniform(0.3, 0.7),
                "shootout": np.random.uniform(0.2, 0.7),
                "tilt": 0.0,
                "late_trailing": np.random.uniform(0.0, 0.3),
            }
        if regime == "pressured_road":
            return {
                "pressure_edge": np.random.uniform(0.2, 0.8),
                "yac_env": np.random.uniform(0.15, 0.45),
                "secondary_stress": np.random.uniform(0.0, 0.35),
                "ol_stress": np.random.uniform(0.2, 0.7),
                "short_week_road": np.random.uniform(0.2, 0.7),
                "backup_qb": np.random.choice([0.0, 0.8], p=[0.85, 0.15]),
                "home": np.random.uniform(-0.6, -0.2),
                "shootout": np.random.uniform(0.1, 0.5),
                "tilt": np.random.choice([0.0, 0.7], p=[0.8, 0.2]),
                "late_trailing": np.random.uniform(0.0, 0.5),
            }
        if regime == "thin_secondary":
            return {
                "pressure_edge": np.random.uniform(-0.3, 0.3),
                "yac_env": np.random.uniform(0.35, 0.75),
                "secondary_stress": np.random.uniform(0.45, 0.95),
                "ol_stress": np.random.uniform(0.0, 0.3),
                "short_week_road": np.random.uniform(0.0, 0.3),
                "backup_qb": 0.0,
                "home": np.random.uniform(-0.3, 0.5),
                "shootout": np.random.uniform(0.3, 0.8),
                "tilt": 0.0,
                "late_trailing": np.random.uniform(0.0, 0.4),
            }
        return {
            "pressure_edge": np.random.uniform(-0.5, 0.5),
            "yac_env": np.random.uniform(0.2, 0.6),
            "secondary_stress": np.random.uniform(0.1, 0.6),
            "ol_stress": np.random.uniform(0.0, 0.4),
            "short_week_road": np.random.uniform(0.0, 0.4),
            "backup_qb": np.random.choice([0.0, 0.9], p=[0.9, 0.1]),
            "home": np.random.uniform(-0.5, 0.5),
            "shootout": np.random.uniform(0.2, 0.7),
            "tilt": np.random.choice([0.0, 0.6], p=[0.85, 0.15]),
            "late_trailing": np.random.uniform(0.0, 0.35),
        }

    def true_logit(state, action, x):
        if state == "OPEN" and action in ("CLEAN", "SUSTAIN", "CHUNK"):
            z = -0.25
            z += -0.85 * x["pressure_edge"]
            z += -0.35 * x["ol_stress"]
            z += -0.40 * x["short_week_road"]
            z += -0.50 * x["backup_qb"]
            z += 0.35 * x["home"]
            z += 0.25 * x["shootout"]
            z += -0.45 * x["tilt"]
            if action == "CHUNK":
                z += 1.20 * x["secondary_stress"] + 0.45 * x["yac_env"]
            return z
        if state == "OPEN" and action == "NO_EVENT":
            return 0.15
        if state in ("CLEAN",) and action == "CHUNK":
            return -0.10 + 0.75 * x["yac_env"] + 0.65 * x["secondary_stress"] + 0.30 * x["shootout"]
        if state in ("CLEAN",) and action == "ORDINARY":
            return 0.05
        if state == "SUSTAIN" and action == "REDZONE":
            return 0.05 + 0.25 * x["shootout"] - 0.35 * x["pressure_edge"]
        if state == "SUSTAIN" and action == "MIDFIELD_DIE":
            return -0.05 + 0.40 * x["pressure_edge"]
        if state in ("CHUNK", "REDZONE") and action == "SCORE":
            return 0.20 + 0.35 * x["shootout"] + 0.55 * x["late_trailing"] + 0.20 * x["home"]
        if state in ("CHUNK", "REDZONE") and action == "FAIL":
            return -0.20 + 0.25 * x["tilt"]
        if state == "ORDINARY" and action == "SCORE":
            return -0.75 + 0.30 * x["home"]
        if state == "ORDINARY" and action == "FAIL":
            return 0.75
        if state == "MIDFIELD_DIE" and action == "SCORE":
            return -1.6
        if state == "MIDFIELD_DIE" and action == "FAIL":
            return 1.6
        return 0.0

    graph = {
        "OPEN": ["CLEAN", "SUSTAIN", "CHUNK", "NO_EVENT"],
        "CLEAN": ["CHUNK", "ORDINARY"],
        "SUSTAIN": ["REDZONE", "MIDFIELD_DIE"],
        "CHUNK": ["SCORE", "FAIL"],
        "REDZONE": ["SCORE", "FAIL"],
        "ORDINARY": ["SCORE", "FAIL"],
        "MIDFIELD_DIE": ["SCORE", "FAIL"],
    }

    def generate(n_obs, py_rng):
        from collections import defaultdict
        regimes = ["clean_pocket_home", "pressured_road", "thin_secondary", "mixed"]
        data = defaultdict(list)
        for _ in range(n_obs):
            regime = py_rng.choice(regimes)
            x = sample_features(regime)
            x_vec = np.array([x[k] for k in FEATURE_NAMES], dtype=float)
            state = py_rng.choices(
                ["OPEN", "CLEAN", "SUSTAIN", "CHUNK", "REDZONE", "ORDINARY", "MIDFIELD_DIE"],
                weights=[0.35, 0.12, 0.12, 0.12, 0.10, 0.09, 0.10],
            )[0]
            actions = graph[state]
            logits = [true_logit(state, a, x) for a in actions]
            m = max(logits)
            ex = [math.exp(l - m) for l in logits]
            s = sum(ex)
            ps = [e / s for e in ex]
            chosen = py_rng.choices(range(len(actions)), weights=ps)[0]
            data[state].append((x_vec, chosen, actions))
        return data

    def fit_state(state, observations, l2=0.4):
        if not observations:
            return {}
        actions = observations[0][2]
        k = len(actions)
        d = len(FEATURE_NAMES)
        n_params = (k - 1) * (1 + d)
        x_mat = np.array([o[0] for o in observations])
        y = np.array([o[1] for o in observations])
        n_obs = len(y)

        def unpack(theta):
            mats = []
            for a in range(k - 1):
                base = a * (1 + d)
                mats.append((theta[base], theta[base + 1: base + 1 + d]))
            mats.append((0.0, np.zeros(d)))
            return mats

        def neg_ll(theta):
            mats = unpack(theta)
            logits = np.zeros((n_obs, k))
            for a, (b0, b) in enumerate(mats):
                logits[:, a] = b0 + x_mat @ b
            logits -= logits.max(axis=1, keepdims=True)
            exp = np.exp(logits)
            probs = exp / exp.sum(axis=1, keepdims=True)
            ll = np.log(probs[np.arange(n_obs), y] + 1e-12).sum()
            return -ll + 0.5 * l2 * np.sum(theta ** 2)

        def grad(theta):
            mats = unpack(theta)
            logits = np.zeros((n_obs, k))
            for a, (b0, b) in enumerate(mats):
                logits[:, a] = b0 + x_mat @ b
            logits -= logits.max(axis=1, keepdims=True)
            exp = np.exp(logits)
            probs = exp / exp.sum(axis=1, keepdims=True)
            g = np.zeros_like(theta)
            for a in range(k - 1):
                resid = (y == a).astype(float) - probs[:, a]
                base = a * (1 + d)
                g[base] = -resid.sum() + l2 * theta[base]
                g[base + 1: base + 1 + d] = -(x_mat.T @ resid) + l2 * theta[base + 1: base + 1 + d]
            return g

        res = minimize(neg_ll, np.zeros(n_params), jac=grad, method="L-BFGS-B",
                       options={"maxiter": 200})
        mats = unpack(res.x)
        out = {}
        for a, act in enumerate(actions):
            b0, b = mats[a]
            coef = {"beta0": float(b0)}
            for i, name in enumerate(FEATURE_NAMES):
                coef[name] = float(b[i])
            out[act] = coef
        return out

    py_rng = random.Random(42)
    np.random.seed(42)
    data = generate(n, py_rng)
    print("States:", {k: len(v) for k, v in data.items()})
    fitted = {}
    for state, obs in data.items():
        fitted[state] = fit_state(state, obs)
        print("  fitted {:12s}  n={:5d}".format(state, len(obs)))

    path = Path(__file__).resolve().parent / "fitted_betas.py"
    with path.open("w") as fh:
        fh.write("# Synthetic multinomial logit from project.py fit.\n")
        fh.write("# Not NFL data. Not an edge.\n")
        fh.write("FITTED_BETAS = ")
        fh.write(repr(fitted))
        fh.write("\nFEATURE_NAMES = ")
        fh.write(repr(list(FEATURE_NAMES)))
        fh.write("\n")
    print("Wrote {} (synthetic coefficients only).".format(path))
    # silence unused helper warning by referencing sigmoid once
    _ = sigmoid(0.0)
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "fit":
        return cmd_fit(argv[1:])
    print_formulas()
    print()
    chains_demo()
    print()
    bengals_demo(n=200)
    print()
    print(format_quote_report(sim()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
