"""Forecast GTA VI (PS5) trophy earn rates on Exophase at a case's target.

Model: earners over players, not rates alone.
------------------------------------------------
Exophase only refreshes the page it prints every few hours. Between two
refreshes every read shows the same page, so a rate by itself says nothing
about where it is heading; what moves underneath it is the pair of counts:

    earners(t) = rate(t) / 100 * players_tracked(t)

Earners can only grow (a player who earned a trophy keeps it) while the
tracked-player count grows too, so a rate falls whenever players are added
faster than earners. A forecast that only extends the last rate misses
both movements. The forecast below therefore works from the distinct
snapshots the page actually printed, and treats a flat history (no
refresh seen yet) as a refresh waiting to happen:

  1. Collapse the history to its distinct snapshots. Reads that repeat the
     previous page carry no new information and are dropped.
  2. Fit a saturating curve to each trophy's rate against hours since
     release, one curve per trophy, over the distinct snapshots:
         rate(h) = R * (1 - exp(-h / tau))
     R (the share of players who will ever earn it) and tau (how fast
     they get there) come from a grid search over tau, least squares in
     percent. The shape matters: trophy earning is concave, fast at
     first while the keenest players rush through, then flattening as
     the remaining players take their time. A straight line in log-time
     keeps climbing where the truth bends over, and on every synthetic
     history with refreshes it overshoots by a factor of two or more.
     The curve is fitted to the rates the page actually printed, so the
     dilution at each refresh is already inside the points it fits.
     A tier floor on tau keeps a thin history honest: a platinum
     cannot be fitted as a fast trophy (tau >= 192h), gold >= 96h,
     silver >= 48h, bronze >= 12h.
  3. When the history is flat (a single snapshot, as on launch night),
     there is no curve to fit. Fall back to a refresh prior: the page is
     stale, so a refresh is assumed before the target. The tracked count is
     taken to jump by the factor the house itself documents for the first
     refresh (638 -> 3,868 players, about 6.06x), and the earners grow by
     the players added times the trophy's old rate times a small share
     (newcomers have had little time to earn anything, so they earn each
     trophy at roughly a fifth of the old rate; the share rises to 1 as a
     rate approaches 100%, which keeps a 100% trophy at 100%).
  4. Spread on the logit scale: a random-walk term growing with the square
     root of the horizon, plus the residual scatter of the curve fit.
     Flat histories get a wide spread because the refresh may or may not
     land before the target.

Output: {"trophies": [{"id": n, "q": [q05, q25, q50, q75, q95]}, ...]},
five quantiles per trophy, non-decreasing, in percent. Pure standard
library, fully deterministic, no randomness, no network.
"""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z_SCORES = [-1.6448536269514722, -0.6744897501960817, 0.0,
            0.6744897501960817, 1.6448536269514722]

# Release of the game; log-time is measured from here.
RELEASE = datetime(2026, 11, 19, 0, 0, 0, tzinfo=timezone.utc)

# Time constants (hours) tried for a trophy's earning curve.
TAU_GRID = [12, 24, 48, 96, 192, 384, 768, 1536]
# A trophy cannot be fitted as faster than this, by tier: with only a
# few snapshots a free fit would happily call a platinum a fast trophy.
TAU_FLOOR = {"platinum": 192, "gold": 96, "silver": 48, "bronze": 12}

# First-refresh jump in tracked players, as documented in the kit's rules
# (638 players before the refresh, 3,868 after it). Only used when the
# history is a single flat snapshot and no slope can be fitted.
REFRESH_JUMP = 3868.0 / 638.0

# Share of the old earn rate at which newly tracked players are assumed to
# have earned a trophy by the refresh. Rare trophies: newcomers barely
# earned them; near-100% trophies: newcomers earned them too.
NEWCOMER_SHARE = 0.22


def parse_time(text):
    """ISO-8601 timestamp -> aware datetime (UTC)."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def hours_since_release(moment):
    return max(0.0, (moment - RELEASE).total_seconds() / 3600.0)


def log_time(moment):
    return math.log1p(hours_since_release(moment))


def clamp_pct(value):
    return min(99.99, max(0.01, value))


def logit_of(pct):
    p = clamp_pct(pct) / 100.0
    return math.log(p / (1.0 - p))


def pct_of(logit_value):
    return 100.0 / (1.0 + math.exp(-logit_value))


def round4(value):
    """Round to 4 decimals, halves away from zero, as a plain number."""
    scaled = value * 10000.0
    whole = math.floor(scaled + 0.5)
    out = whole / 10000.0
    return int(out) if float(out).is_integer() else out


def distinct_snapshots(history):
    """Keep the first read and every read whose page differs from the last kept."""
    snaps = []
    prev_players = None
    prev_rates = None
    for read in history:
        rates = read.get("rates") or []
        players = read.get("players_tracked")
        if prev_players is None or players != prev_players or rates != prev_rates:
            snaps.append(read)
            prev_players = players
            prev_rates = rates
    return snaps


def forecast_trophy(trophy, snaps, horizon_days, target_x):
    """Median rate (percent) and logit spread for one trophy."""
    tier = trophy.get("tier", "bronze")
    # Trophies are listed in id order and rates follow the same order.
    idx = trophy["_pos"]

    # Earners and players at each distinct snapshot.
    xs, earners, players = [], [], []
    for snap in snaps:
        rates = snap.get("rates") or []
        if idx >= len(rates) or rates[idx] is None:
            continue
        p = snap.get("players_tracked")
        if not p or p <= 0:
            continue
        xs.append(log_time(parse_time(snap["at"])))
        players.append(float(p))
        earners.append(max(0.0, rates[idx] / 100.0 * p))

    last_rate = earners[-1] / players[-1] * 100.0 if earners else 0.0
    if last_rate >= 99.995:
        # Everybody tracked holds it; newcomers hold it too.
        return 100.0, 0.05

    # --- Trend branch: enough distinct snapshots to fit a curve. ---
    if len(xs) >= 3 and len(set(players)) >= 2 and len(set(earners)) >= 2:
        # (hour since release, printed rate) at each snapshot that has
        # this trophy, and the target hour from the log-time passed in.
        pairs = []
        for snap in snaps:
            rates = snap.get("rates") or []
            if idx < len(rates) and rates[idx] is not None:
                pairs.append((hours_since_release(parse_time(snap["at"])),
                              rates[idx]))
        target_h = math.expm1(target_x)
        best = None
        tau_floor = TAU_FLOOR.get(tier, 12)
        for tau in TAU_GRID:
            if tau < tau_floor:
                continue
            xx = [1.0 - math.exp(-h / tau) for h, _ in pairs]
            den = sum(v * v for v in xx)
            if den <= 0.0:
                continue
            big_r = sum(r * v for (_, r), v in zip(pairs, xx)) / den
            sse = sum((r - big_r * v) ** 2 for (_, r), v in zip(pairs, xx))
            if best is None or sse < best[0]:
                best = (sse, big_r, tau)
        _, big_r, tau = best
        median = clamp_pct(big_r * (1.0 - math.exp(-target_h / tau)))
        # Sanity clamps: a curve fitted on a thin history must not run
        # away from the last printed rate.
        median = min(median, max(last_rate * 8.0, last_rate + 5.0))
        median = max(median, last_rate * 0.10)
        # Saturation: a trophy already above 90% cannot climb much further.
        if last_rate > 90.0:
            median = min(median, last_rate + (100.0 - last_rate) * 0.5)
        # Spread from the fit's residual scatter, measured in logit space
        # so it counts the way the score counts, plus a random-walk term.
        resid = []
        for h, r in pairs:
            fit = clamp_pct(big_r * (1.0 - math.exp(-h / tau)))
            resid.append(logit_of(r) - logit_of(fit))
        resid_sd = math.sqrt(sum(v * v for v in resid) / max(1, len(resid)))
        resid_sd = min(0.8, max(0.08, resid_sd))
        sigma = math.sqrt((0.25 * math.sqrt(horizon_days)) ** 2
                          + resid_sd ** 2 + 0.10 ** 2)
        sigma = min(0.90, max(0.30, sigma))
        return median, sigma

    # --- Flat branch: one snapshot, no slope. Assume a refresh lands. ---
    p_last = players[-1] if players else 1.0
    e_last = earners[-1] if earners else 0.0
    p_tgt = p_last * REFRESH_JUMP
    share = NEWCOMER_SHARE + (1.0 - NEWCOMER_SHARE) * (e_last / p_last)
    e_tgt = e_last + (p_tgt - p_last) * (e_last / p_last) * share
    e_tgt = min(e_tgt, p_tgt)
    median = clamp_pct(100.0 * e_tgt / p_tgt)
    sigma = 0.50
    return median, sigma


def forecast_case(case):
    if not case.get("history"):
        raise ValueError("case has no history")
    target = parse_time(case["target"])
    target_x = log_time(target)
    horizon_days = case["horizon_minutes"] / 1440.0
    snaps = distinct_snapshots(case["history"])
    rows = []
    for pos, trophy in enumerate(case["trophies"]):
        trophy = dict(trophy)
        trophy["_pos"] = pos
        median, sigma = forecast_trophy(trophy, snaps, horizon_days, target_x)
        if median >= 100.0:
            qs = [100, 100, 100, 100, 100]
        else:
            centre = logit_of(median)
            qs = []
            prev = None
            for z in Z_SCORES:
                q = round4(pct_of(centre + z * sigma))
                q = min(100.0, max(0.01, q))
                if prev is not None and q < prev:
                    q = prev
                qs.append(q)
                prev = q
        rows.append({"id": trophy["id"], "q": qs})
    return {"trophies": rows}


def main():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        out = OUTPUT_DIR / (path.stem + ".out")
        out.write_text(json.dumps(forecast, separators=(",", ":")) + "\n",
                       encoding="utf-8")


if __name__ == "__main__":
    main()
