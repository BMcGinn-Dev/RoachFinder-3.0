"""
RoachFinder 3.0 — Escanor backtest + v2 calibration

    python backtest.py

Replays the 2024 and 2025 seasons week by week (Weeks 2-18) using only the
stats that were known before each game, and grades every pick against the
closing spread. It scores:

    0  current Escanor (the original formula)
    1  + Fix 1  league-average normalization
    2  + Fix 2  pick against the spread
    3  + Fix 3  sack direction / sack rate
    4  + Fix 4  zero-division smoothing + index cap
    5  + Fix 5  per-play rates + last-season blend
    6  + Fix 6  home field + turnovers + fitted weights

Anything that has to be fitted (points per score unit, weights) is fitted on
the OTHER season and tested on this one, so the results are out-of-sample.

Finally it fits the v2 parameters on both seasons and writes
data/escanor_v2_params.json (used by run_week.py) and
data/backtest_report.json.

Needs data/history/games_2023.json .. games_2025.json
(run  python fetch_history.py  first).
"""

import json
import statistics
from datetime import date

import numpy as np
import pandas as pd

import predictor as v1
import escanor_v2 as v2
from config import data_path
from espn_data import load_season_games, team_totals

TEST_SEASONS = [2024, 2025]
WEEKS = range(2, 19)
BREAK_EVEN = 52.38

STAGES = [
    ("Current Escanor", ()),
    ("+ Fix 1 normalize", ("normalize",)),
    ("+ Fix 2 vs spread", ("normalize", "ats")),
    ("+ Fix 3 sacks", ("normalize", "ats", "sack_fix")),
    ("+ Fix 4 smoothing", ("normalize", "ats", "sack_fix", "smooth")),
    ("+ Fix 5 rates/blend", ("normalize", "ats", "sack_fix", "smooth", "rates")),
    ("+ Fix 6 HFA/TO/fit", ("normalize", "ats", "sack_fix", "smooth", "rates", "fitted")),
]


# ── Original Escanor on ESPN totals (sanity check for the v2 engine) ───

def v1_frame(totals):
    rows = {}
    for team, t in totals.items():
        r = {}
        for side, pre in (("off", "Offensive"), ("def", "Defensive")):
            s = t[side]
            att, cmp_ = s["att"] or 1, s["cmp"] or 1
            r[f"{pre}_Passing_Cmp %"] = s["cmp"] / att * 100
            r[f"{pre}_Passing_Rate"] = v2._passer_rating(s)
            r[f"{pre}_Passing_1st%"] = s["fd_pass"] / att * 100
            r[f"{pre}_Passing_Sck"] = s["sacks"]
            r[f"{pre}_Passing_Yds/Att"] = s["gross_py"] / att
            ra = s["rush_att"] or 1
            r[f"{pre}_Rushing_YPC"] = s["rush_yds"] / ra
            r[f"{pre}_Rushing_TD"] = s["rush_td"]
            r[f"{pre}_Rushing_Rush 1st%"] = s["fd_rush"] / ra * 100
            r[f"{pre}_Rushing_Rush Yds"] = s["rush_yds"]
            r[f"{pre}_Receiving_Yds/Rec"] = s["gross_py"] / cmp_
            r[f"{pre}_Receiving_TD"] = s["pass_td"]
            r[f"{pre}_Receiving_Rec 1st%"] = s["fd_pass"] / cmp_ * 100
            r[f"{pre}_Downs_3rd Att"] = s["third_a"]
            r[f"{pre}_Downs_3rd Md"] = s["third_m"]
            r[f"{pre}_Downs_4th Att"] = s["fourth_a"]
            r[f"{pre}_Downs_4th Md"] = s["fourth_m"]
        rows["49Ers" if team == "49ers" else team] = r
    return pd.DataFrame.from_dict(rows, orient="index")


def _fix(name):
    return "49Ers" if name == "49ers" else name


# ── Build per-game feature rows ────────────────────────────────────────

def build_rows(games_by_season, fixes, blend_games=v2.DEFAULT_BLEND_GAMES, check_v1=False):
    rows = []
    mismatches = 0
    for season in TEST_SEASONS:
        games = games_by_season[season]
        prior = team_totals(games_by_season[season - 1])
        for week in WEEKS:
            totals = team_totals(games, before_week=week)
            ratings = v2.Ratings(totals, fixes, prior_totals=prior, blend_games=blend_games)
            df = v1_frame(totals) if check_v1 else None
            for g in games:
                if g["week"] != week or g["status"] != "STATUS_FINAL" or g["spread_home"] is None:
                    continue
                h = g["teams"]["home"]["name"].rsplit(" ", 1)[-1]
                a = g["teams"]["away"]["name"].rsplit(" ", 1)[-1]
                if h not in ratings.teams or a not in ratings.teams:
                    continue
                feats = ratings.features(h, a)
                gap = v2.score_gap(feats, v2.hand_weights())
                if check_v1:
                    winner, _, cf = v1.predict_matchup(df, _fix(a), _fix(h))
                    ref_gap = cf if winner == _fix(h) else -cf
                    if abs(ref_gap - gap) > 1e-6 * max(1, abs(gap)):
                        mismatches += 1
                rows.append({
                    "season": season, "week": week, "home": h, "away": a,
                    "margin": g["teams"]["home"]["score"] - g["teams"]["away"]["score"],
                    "spread_home": g["spread_home"],
                    "gap": gap,
                    "diffs": {s: feats[s][0] - feats[s][1] for s in v2.STAT_NAMES},
                })
    return rows, mismatches


# ── Fitting ────────────────────────────────────────────────────────────

def fit_points_per_unit(rows):
    x = np.array([r["gap"] for r in rows])
    y = np.array([r["margin"] for r in rows])
    return float((x @ y) / (x @ x)) if (x @ x) > 0 else 0.0


def fit_weights(rows, lam=None):
    """Ridge regression: margin = hfa + sum(w_s * diff_s)."""
    X = np.array([[r["diffs"][s] for s in v2.STAT_NAMES] for r in rows])
    y = np.array([r["margin"] for r in rows])
    if lam is None:
        lam = _choose_lambda(X, y)
    n, p = X.shape
    A = np.hstack([np.ones((n, 1)), X])
    reg = lam * np.eye(p + 1)
    reg[0, 0] = 0.0                     # don't shrink home-field
    beta = np.linalg.solve(A.T @ A + reg, A.T @ y)
    return float(beta[0]), {s: float(b) for s, b in zip(v2.STAT_NAMES, beta[1:])}, lam


def _choose_lambda(X, y, grid=(10, 30, 100, 300, 1000, 3000), folds=5):
    idx = np.arange(len(y))
    best, best_err = grid[0], float("inf")
    for lam in grid:
        err = 0.0
        for k in range(folds):
            test = idx % folds == k
            A = np.hstack([np.ones((len(y), 1)), X])
            reg = lam * np.eye(A.shape[1])
            reg[0, 0] = 0.0
            beta = np.linalg.solve(A[~test].T @ A[~test] + reg, A[~test].T @ y[~test])
            err += float(((A[test] @ beta - y[test]) ** 2).sum())
        if err < best_err:
            best, best_err = lam, err
    return best


# ── Grading ────────────────────────────────────────────────────────────

def grade(rows, fixes, params):
    """Returns pick-level results with confidence, sorted within weeks."""
    out = []
    for r in rows:
        if "fitted" in fixes:
            margin = params["fitted_hfa"] + sum(params["fitted_weights"][s] * r["diffs"][s]
                                                for s in v2.STAT_NAMES)
            gap = margin
        else:
            gap = r["gap"]
            margin = params["points_per_unit"] * gap if "ats" in fixes else None
        side, conf = v2.choose_side(gap, margin, r["spread_home"], fixes)
        cover = r["margin"] + r["spread_home"]          # home perspective
        if cover == 0:
            res = "P"
        elif (cover > 0) == (side == "home"):
            res = "W"
        else:
            res = "L"
        abs_err = abs(margin - r["margin"]) if margin is not None else None
        pred = margin if margin is not None else gap
        out.append({**r, "side": side, "conf": conf, "result": res, "abs_err": abs_err, "pred": pred})
    return out


def summarize(picks):
    def rec(items):
        w = sum(p["result"] == "W" for p in items)
        l = sum(p["result"] == "L" for p in items)
        pu = sum(p["result"] == "P" for p in items)
        return {"w": w, "l": l, "p": pu, "pct": round(100 * w / (w + l), 1) if w + l else 0.0}

    top5, above = [], []
    for season in TEST_SEASONS:
        seen = []
        for week in WEEKS:
            wk = sorted([p for p in picks if p["season"] == season and p["week"] == week],
                        key=lambda p: p["conf"], reverse=True)
            if not wk:
                continue
            top5 += wk[:5]
            seen += [p["conf"] for p in wk]
            med = statistics.median(seen)
            above += [p for p in wk if p["conf"] >= med]
    errs = [p["abs_err"] for p in picks if p["abs_err"] is not None]
    decided = [p for p in picks if p["margin"] != 0]
    su = sum((p["pred"] > 0) == (p["margin"] > 0) for p in decided) / len(decided)
    corr = float(np.corrcoef([p["pred"] for p in picks], [p["margin"] for p in picks])[0, 1])
    return {
        "straight_up_pct": round(100 * su, 1),
        "margin_corr": round(corr, 3),
        "all": rec(picks), "top5": rec(top5), "above_median": rec(above),
        "by_season": {s: rec([p for p in picks if p["season"] == s]) for s in TEST_SEASONS},
        "margin_mae": round(sum(errs) / len(errs), 2) if errs else None,
    }


def cross_season(rows, fixes):
    """Fit on one season, grade the other."""
    picks = []
    for test in TEST_SEASONS:
        train = [r for r in rows if r["season"] != test]
        params = {"points_per_unit": fit_points_per_unit(train)}
        if "fitted" in fixes:
            hfa, w, _ = fit_weights(train)
            params.update(fitted_hfa=hfa, fitted_weights=w)
        picks += grade([r for r in rows if r["season"] == test], fixes, params)
    return picks


# ── Main ───────────────────────────────────────────────────────────────

def main():
    games = {s: load_season_games(s, verbose=False) for s in [2023, 2024, 2025]}
    line_rows = []

    print(f"\n{'='*78}")
    print("  Escanor backtest — 2024 + 2025, Weeks 2-18, graded against closing spreads")
    print("  (fitted pieces are trained on the other season)")
    print(f"{'='*78}")
    print("  ATS = record against the spread.  SU = picked the right winner.")
    print("  Corr = how closely the model's numbers track actual final margins (0-1).\n")
    print(f"  {'Stage':22} {'ATS all games':>16} {'ATS top 5':>15} {'ATS >= median':>16} {'SU':>6} {'Corr':>5}")

    report = {"generated": date.today().isoformat(), "stages": []}
    for i, (label, fixes) in enumerate(STAGES):
        rows, mism = build_rows(games, fixes, check_v1=(i == 0))
        if i == 0:
            line_rows = rows
            if mism:
                print(f"  NOTE: v2 engine differs from predictor.py on {mism} games")
        s = summarize(cross_season(rows, fixes))
        f = lambda d: f"{d['w']}-{d['l']}-{d['p']} {d['pct']:>5}%"
        print(f"  {label:22} {f(s['all']):>16} {f(s['top5']):>15} {f(s['above_median']):>16} "
              f"{s['straight_up_pct']:>5}% {s['margin_corr']:>5.2f}")
        report["stages"].append({"stage": label, "fixes": list(fixes), **s})

    fav = [r for r in line_rows if r["margin"] != 0 and r["spread_home"] != 0]
    fav_su = sum((r["spread_home"] < 0) == (r["margin"] > 0) for r in fav) / len(fav)
    line_corr = np.corrcoef([-r["spread_home"] for r in line_rows], [r["margin"] for r in line_rows])[0, 1]
    print(f"  {'Vegas closing line':22} {'':>16} {'':>15} {'':>16} {100*fav_su:>5.1f}% {line_corr:>5.2f}")
    print(f"  Break-even at -110 odds: {BREAK_EVEN}%.  With ~500 games, differences")
    print("  under ~3 points of win % are within normal luck.")

    # Blend strength check for the final model
    print("\n  Last-season blend strength (all fixes):")
    best_b, best_mae = v2.DEFAULT_BLEND_GAMES, None
    for b in (0, 2, 4, 8):
        rows, _ = build_rows(games, v2.ALL_FIXES, blend_games=b)
        s = summarize(cross_season(rows, v2.ALL_FIXES))
        print(f"    counts as {b} games: {s['all']['pct']}% ATS, margin MAE {s['margin_mae']}")
        if best_mae is None or s["margin_mae"] < best_mae:
            best_b, best_mae = b, s["margin_mae"]

    # Final fit on both seasons for live use
    rows, _ = build_rows(games, v2.ALL_FIXES, blend_games=best_b)
    hfa, weights, lam = fit_weights(rows)
    params = {
        "fitted_on": TEST_SEASONS,
        "generated": date.today().isoformat(),
        "fixes": list(v2.ALL_FIXES),
        "blend_games": best_b,
        "points_per_unit": fit_points_per_unit(rows),
        "fitted_hfa": hfa,
        "fitted_weights": weights,
        "ridge_lambda": lam,
    }
    with open(v2.PARAMS_FILE, "w") as fh:
        json.dump(params, fh, indent=2)
    report["final_params"] = params
    with open(data_path("backtest_report.json"), "w") as fh:
        json.dump(report, fh, indent=2)

    print(f"\n  Chosen blend: {best_b} games.  Home-field edge: {hfa:+.2f} pts.")
    print("  Fitted weights (points per unit of index difference):")
    for s_, w in sorted(weights.items(), key=lambda kv: -abs(kv[1])):
        print(f"    {s_:10} {w:+7.2f}")
    print(f"\n  Saved {v2.PARAMS_FILE}")
    print(f"  Saved {data_path('backtest_report.json')}\n")


if __name__ == "__main__":
    main()
