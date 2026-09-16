"""
RoachFinder 3.0 — Escanor v2

Same thought process as the original Escanor (predictor.py): for every stat,
size up each offense against the opposing defense, blend the stats into
Passing / Rushing / Receiving / Downs scores, and compare the two teams.

What v2 changes (each can be switched off in FIXES for comparison):
  normalize  Fix 1  offense and defense are both measured against the league
                    average, so facing a bad defense helps an offense
  ats        Fix 2  the score gap is converted to projected points and the pick
                    is made against the spread (confidence = points of edge)
  sack_fix   Fix 3  sacks count against an offense, as a rate per dropback
  smooth     Fix 4  small samples are pulled toward league average and every
                    matchup index is capped, so 3 / 0 can't swing a game
  rates      Fix 5  TDs and yards become per-play / per-game rates, and early
                    weeks lean on last season's stats
  fitted     Fix 6  home-field edge, a turnover category, and weights fitted to
                    past results instead of hand-picked

With every fix off this reproduces the original Escanor math (the backtest
checks that against predictor.py).
"""

import json
import os

from espn_data import team_totals
from config import data_path

PARAMS_FILE = data_path("escanor_v2_params.json")

ALL_FIXES = ("normalize", "ats", "sack_fix", "smooth", "rates", "fitted")

CATEGORY_WEIGHTS = {"passing": 0.33, "rushing": 0.22, "receiving": 0.18, "downs": 0.27}

# name, category, v1 sub-weight
STATS = [
    ("cmp_pct",   "passing",   25),
    ("rating",    "passing",   35),
    ("pass_1st",  "passing",   10),
    ("sacks",     "passing",   15),
    ("ypa",       "passing",   20),
    ("ypc",       "rushing",   40),
    ("rush_td",   "rushing",   15),
    ("rush_1st",  "rushing",   20),
    ("rush_yds",  "rushing",   25),
    ("ypr",       "receiving", 50),
    ("rec_td",    "receiving", 15),
    ("rec_1st",   "receiving", 35),
    ("third",     "downs",     80),
    ("fourth",    "downs",     20),
    ("turnovers", "turnovers", 0),   # only used when fitted
]
STAT_NAMES = [s[0] for s in STATS]

# Stats where a HIGHER number is BAD for the offense (once fixed)
LOWER_IS_BETTER = {"sacks", "turnovers"}

INDEX_CAP = (0.5, 2.0)
SMOOTH_GAMES = 1.0       # prior strength: one league-average game
DEFAULT_BLEND_GAMES = 4  # last season counts as this many games


# ── Rates ──────────────────────────────────────────────────────────────

def _passer_rating(t):
    att = t["att"]
    if att <= 0:
        return 0.0
    clamp = lambda x: max(0.0, min(2.375, x))
    a = clamp((t["cmp"] / att - 0.3) * 5)
    b = clamp((t["gross_py"] / att - 3) * 0.25)
    c = clamp(t["pass_td"] / att * 20)
    d = clamp(2.375 - t["ints"] / att * 25)
    return (a + b + c + d) / 6 * 100


def _parts(stat, t, gp, fixes):
    """(numerator, denominator) for a stat from a totals dict.
    Denominator None means 'already a finished value' (numerator is it)."""
    rates = "rates" in fixes
    if stat == "cmp_pct":
        return t["cmp"], t["att"]
    if stat == "rating":
        return _passer_rating(t), None
    if stat == "pass_1st":
        return t["fd_pass"], t["att"]
    if stat == "sacks":
        if "sack_fix" in fixes:
            return t["sacks"], t["att"] + t["sacks"]
        return t["sacks"], None                      # v1: raw count
    if stat == "ypa":
        return t["gross_py"], t["att"]
    if stat == "ypc":
        return t["rush_yds"], t["rush_att"]
    if stat == "rush_td":
        return (t["rush_td"], t["rush_att"]) if rates else (t["rush_td"], None)
    if stat == "rush_1st":
        return t["fd_rush"], t["rush_att"]
    if stat == "rush_yds":
        return (t["rush_yds"], gp) if rates else (t["rush_yds"], None)
    if stat == "ypr":
        return t["gross_py"], t["cmp"]
    if stat == "rec_td":
        return (t["pass_td"], t["cmp"]) if rates else (t["pass_td"], None)
    if stat == "rec_1st":
        return t["fd_pass"], t["cmp"]
    if stat == "third":
        return t["third_m"], t["third_a"]
    if stat == "fourth":
        return t["fourth_m"], t["fourth_a"]
    if stat == "turnovers":
        return t["turnovers"], t["drives"]
    raise KeyError(stat)


def _blend(cur, prior, blend_games):
    """Add last season's totals, scaled to `blend_games` games' worth."""
    if not prior or prior["gp"] == 0 or blend_games <= 0:
        return cur
    s = blend_games / prior["gp"]
    out = {"gp": cur["gp"] + blend_games, "off": {}, "def": {}}
    for side in ("off", "def"):
        keys = set(cur[side]) | set(prior[side])
        out[side] = {k: cur[side].get(k, 0.0) + prior[side].get(k, 0.0) * s for k in keys}
    return out


class Ratings:
    """Per-team offensive rates and defensive allowed rates for one week."""

    def __init__(self, totals, fixes, prior_totals=None, blend_games=DEFAULT_BLEND_GAMES):
        self.fixes = set(fixes)
        teams = {}
        for name, cur in totals.items():
            if "rates" in self.fixes and prior_totals:
                cur = _blend(cur, prior_totals.get(name), blend_games)
            teams[name] = cur
        self.teams = teams

        # League averages (offense and defense-allowed are the same pool)
        self.league = {}
        n_games = sum(t["gp"] for t in teams.values()) or 1
        for stat in STAT_NAMES:
            nums, dens, vals = 0.0, 0.0, []
            for t in teams.values():
                num, den = _parts(stat, t["off"], t["gp"], self.fixes)
                if den is None:
                    vals.append(num)
                else:
                    nums += num
                    dens += den
            if vals:
                self.league[stat] = (sum(vals) / len(vals), None)
            else:
                self.league[stat] = (nums / dens if dens else 0.0, dens / n_games)

        self.off = {n: self._rates(t, "off") for n, t in teams.items()}
        self.dfn = {n: self._rates(t, "def") for n, t in teams.items()}

    def _rates(self, t, side):
        out = {}
        for stat in STAT_NAMES:
            num, den = _parts(stat, t[side], t["gp"], self.fixes)
            lg_rate, lg_den_per_game = self.league[stat]
            if den is None:
                out[stat] = num
            elif "smooth" in self.fixes:
                k = SMOOTH_GAMES * (lg_den_per_game or 1.0)
                out[stat] = (num + k * lg_rate) / (den + k)
            else:
                out[stat] = num / den if den else 0.0
        return out

    def index(self, stat, offense, defense):
        """How favorable this stat is for `offense` against `defense`.
        1.0 = neutral, above 1 = good for the offense."""
        a = self.off[offense][stat]
        b = self.dfn[defense][stat]
        if "normalize" in self.fixes:
            lg = self.league[stat][0]
            if lg <= 0:
                idx = 1.0
            else:
                idx = (a / lg) * (b / lg)
                if stat in LOWER_IS_BETTER and ("sack_fix" in self.fixes or stat == "turnovers"):
                    idx = 1.0 / idx if idx > 0 else INDEX_CAP[1]
        else:
            # Original Escanor ratio: offense / what the defense allows
            if stat == "third" or stat == "fourth":
                stop = 1.0 - b
                idx = a / stop if stop != 0 else 0.0     # v1 behavior
            elif stat in LOWER_IS_BETTER and ("sack_fix" in self.fixes or stat == "turnovers"):
                idx = b / a if a > 0 else (b if "smooth" not in self.fixes else INDEX_CAP[1])
            else:
                idx = a / b if b else a                   # v1 zero fallback
        if "smooth" in self.fixes:
            idx = max(INDEX_CAP[0], min(INDEX_CAP[1], idx))
        return idx

    def features(self, home, away):
        """Per-stat index for each side: {stat: (home_idx, away_idx)}."""
        return {s: (self.index(s, home, away), self.index(s, away, home)) for s in STAT_NAMES}


# ── Scoring ────────────────────────────────────────────────────────────

def hand_weights():
    return {name: CATEGORY_WEIGHTS[cat] * w for name, cat, w in STATS if cat in CATEGORY_WEIGHTS}


def score_gap(feats, weights):
    """home total minus away total."""
    return sum(w * (feats[s][0] - feats[s][1]) for s, w in weights.items())


def predict(feats, params, fixes):
    """Return (home_gap_score, projected_home_margin or None)."""
    fixes = set(fixes)
    if "fitted" in fixes:
        w = params["fitted_weights"]
        margin = params["fitted_hfa"] + score_gap(feats, w)
        return margin, margin
    gap = score_gap(feats, hand_weights())
    if "ats" in fixes:
        return gap, params["points_per_unit"] * gap
    return gap, None


def choose_side(gap, margin, spread_home, fixes):
    """Return (pick 'home'/'away', confidence).

    Without the ATS fix: pick the higher total, confidence = score gap.
    With it: pick the side the projected margin beats the line for,
    confidence = points of edge over the line.
    """
    if margin is not None and "ats" in set(fixes) and spread_home is not None:
        edge = margin + spread_home
        return ("home" if edge > 0 else "away"), abs(edge)
    return ("home" if gap > 0 else "away"), abs(gap)


# ── Live weekly use ────────────────────────────────────────────────────

def load_params():
    if not os.path.exists(PARAMS_FILE):
        raise RuntimeError(
            "Escanor v2 isn't calibrated yet. Run:  python backtest.py"
        )
    with open(PARAMS_FILE, "r") as f:
        return json.load(f)


def _line_label(team, line):
    if abs(line) < 1e-9:
        return f"{team} PK"
    return f"{team} {line:+.1f}"


def run_predictions_v2(matchups, season, week):
    """Drop-in replacement for predictor.run_predictions()."""
    from espn_data import load_season_games

    params = load_params()
    fixes = params["fixes"]

    print(f"\n{'='*60}")
    print(f"  Running Escanor v2 on {len(matchups)} matchups")
    print(f"{'='*60}")

    cur_games = load_season_games(season, max_week=max(week - 1, 0))
    prior_games = load_season_games(season - 1)
    ratings = Ratings(
        team_totals(cur_games, before_week=week),
        fixes,
        prior_totals=team_totals(prior_games),
        blend_games=params.get("blend_games", DEFAULT_BLEND_GAMES),
    )

    results = []
    for m in matchups:
        home, away = m["home_team_short"], m["away_team_short"]
        if home not in ratings.teams or away not in ratings.teams:
            print(f"    WARNING: no stats for {away} @ {home}; skipped")
            continue
        spread_home = m.get("spread_home")
        feats = ratings.features(home, away)
        gap, margin = predict(feats, params, fixes)
        side, conf = choose_side(gap, margin, spread_home, fixes)

        sh = spread_home or 0.0
        if side == "home":
            winner, loser, line = home, away, sh
        else:
            winner, loser, line = away, home, -sh
        label = _line_label(winner, line) if spread_home is not None else f"{winner} (no line)"

        results.append({
            **m,
            "pick_winner": winner,
            "pick_loser": loser,
            "confidence_factor": round(conf, 2),
            "winning_pick_label": label,
            "projected_home_margin": round(margin, 1) if margin is not None else None,
            "model_version": "v2",
        })
        # Show the projection in betting-line form: "Jets -10.0" = Jets by 10
        proj = f"model line {_line_label(home, -margin)}" if margin is not None else f"gap {gap:+.2f}"
        print(f"    {away} @ {home}  ({proj})  →  Pick: {label}  (edge {conf:.2f})")

    results.sort(key=lambda r: r["confidence_factor"], reverse=True)
    return results
