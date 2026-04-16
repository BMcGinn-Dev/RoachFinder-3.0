"""
RoachFinder 3.0 — Predictor (Escanor Algorithm)

This is a faithful port of the original Escanor.py algorithm.
The math, weights, and ratio logic are preserved VERBATIM.
Only the I/O layer changed: CSV → JSON, scattered globals → clean functions.

Algorithm summary:
  For each matchup, compare Away Offense vs Home Defense (and vice versa)
  across four categories — Passing, Rushing, Receiving, Downs — using
  weighted stat ratios. The team with the higher composite score is the
  algorithm's pick. The score difference is the Confidence Factor.

Category weights (% of total):
  Passing:   33%
  Rushing:   22%
  Receiving: 18%
  Downs:     27%
"""

import json
import os
import statistics
import pandas as pd

from config import (
    CURRENT_WEEK,
    DATA_DIR,
    data_path,
    get_team_full_name,
)


# ═══════════════════════════════════════════════════════════════════
#  Ratio Functions — VERBATIM from Escanor.py
#  DO NOT MODIFY THE MATH
# ═══════════════════════════════════════════════════════════════════

def _fix_49ers(name: str) -> str:
    """Escanor's '49ers' → '49Ers' hotfix for index matching."""
    return "49Ers" if name == "49ers" else name


def provide_passing_metric(df: pd.DataFrame, away: str, home: str) -> list:
    """
    Returns [[away_pass_ratios], [home_pass_ratios]]
    Each list: [CmpPer, PassRate, 1stPer, Sacks, YPA]
    """
    away = _fix_49ers(away)
    home = _fix_49ers(home)
    away_row = df.loc[away]
    home_row = df.loc[home]

    # Away Offense vs Home Defense — Passing
    a_off_cmp = float(away_row["Offensive_Passing_Cmp %"])
    a_off_rate = float(away_row["Offensive_Passing_Rate"])
    a_off_1st = float(away_row["Offensive_Passing_1st%"])
    a_off_sck = float(away_row["Offensive_Passing_Sck"])
    a_off_ypa = float(away_row["Offensive_Passing_Yds/Att"])

    h_def_cmp = float(home_row["Defensive_Passing_Cmp %"])
    h_def_rate = float(home_row["Defensive_Passing_Rate"])
    h_def_1st = float(home_row["Defensive_Passing_1st%"])
    h_def_sck = float(home_row["Defensive_Passing_Sck"])
    h_def_ypa = float(home_row["Defensive_Passing_Yds/Att"])

    a_cmp_r = a_off_cmp / h_def_cmp
    a_rate_r = a_off_rate / h_def_rate
    a_1st_r = a_off_1st / h_def_1st
    try:
        a_sck_r = a_off_sck / h_def_sck
    except ZeroDivisionError:
        a_sck_r = a_off_sck / 1
    a_ypa_r = a_off_ypa / h_def_ypa

    a_pass_ratios = [a_cmp_r, a_rate_r, a_1st_r, a_sck_r, a_ypa_r]

    # Home Offense vs Away Defense — Passing
    h_off_cmp = float(home_row["Offensive_Passing_Cmp %"])
    h_off_rate = float(home_row["Offensive_Passing_Rate"])
    h_off_1st = float(home_row["Offensive_Passing_1st%"])
    h_off_sck = float(home_row["Offensive_Passing_Sck"])
    h_off_ypa = float(home_row["Offensive_Passing_Yds/Att"])

    a_def_cmp = float(away_row["Defensive_Passing_Cmp %"])
    a_def_rate = float(away_row["Defensive_Passing_Rate"])
    a_def_1st = float(away_row["Defensive_Passing_1st%"])
    a_def_sck = float(away_row["Defensive_Passing_Sck"])
    a_def_ypa = float(away_row["Defensive_Passing_Yds/Att"])

    h_cmp_r = h_off_cmp / a_def_cmp
    h_rate_r = h_off_rate / a_def_rate
    h_1st_r = h_off_1st / a_def_1st
    try:
        h_sck_r = h_off_sck / a_def_sck
    except ZeroDivisionError:
        h_sck_r = h_off_sck / 1
    h_ypa_r = h_off_ypa / a_def_ypa

    h_pass_ratios = [h_cmp_r, h_rate_r, h_1st_r, h_sck_r, h_ypa_r]

    return [a_pass_ratios, h_pass_ratios]


def provide_rushing_metric(df: pd.DataFrame, away: str, home: str) -> list:
    """
    Returns [[away_rush_ratios], [home_rush_ratios]]
    Each list: [YPC, TDs, 1stPer, Yrds]
    """
    away = _fix_49ers(away)
    home = _fix_49ers(home)
    away_row = df.loc[away]
    home_row = df.loc[home]

    # Away Offense vs Home Defense
    a_ypc = float(away_row["Offensive_Rushing_YPC"])
    a_td = float(away_row["Offensive_Rushing_TD"])
    a_1st = float(away_row["Offensive_Rushing_Rush 1st%"])
    a_yds = float(away_row["Offensive_Rushing_Rush Yds"])

    h_d_ypc = float(home_row["Defensive_Rushing_YPC"])
    h_d_td = float(home_row["Defensive_Rushing_TD"])
    h_d_1st = float(home_row["Defensive_Rushing_Rush 1st%"])
    h_d_yds = float(home_row["Defensive_Rushing_Rush Yds"])

    a_ypc_r = a_ypc / h_d_ypc
    try:
        a_td_r = a_td / h_d_td
    except ZeroDivisionError:
        a_td_r = a_td / 1
    a_1st_r = a_1st / h_d_1st
    a_yds_r = a_yds / h_d_yds

    a_rush = [a_ypc_r, a_td_r, a_1st_r, a_yds_r]

    # Home Offense vs Away Defense
    h_ypc = float(home_row["Offensive_Rushing_YPC"])
    h_td = float(home_row["Offensive_Rushing_TD"])
    h_1st = float(home_row["Offensive_Rushing_Rush 1st%"])
    h_yds = float(home_row["Offensive_Rushing_Rush Yds"])

    a_d_ypc = float(away_row["Defensive_Rushing_YPC"])
    a_d_td = float(away_row["Defensive_Rushing_TD"])
    a_d_1st = float(away_row["Defensive_Rushing_Rush 1st%"])
    a_d_yds = float(away_row["Defensive_Rushing_Rush Yds"])

    h_ypc_r = h_ypc / a_d_ypc
    try:
        h_td_r = h_td / a_d_td
    except ZeroDivisionError:
        h_td_r = h_td / 1
    h_1st_r = h_1st / a_d_1st
    h_yds_r = h_yds / a_d_yds

    h_rush = [h_ypc_r, h_td_r, h_1st_r, h_yds_r]

    return [a_rush, h_rush]


def provide_receiving_metric(df: pd.DataFrame, away: str, home: str) -> list:
    """
    Returns [[away_rec_ratios], [home_rec_ratios]]
    Each list: [YPRec, TDs, 1stPer]
    """
    away = _fix_49ers(away)
    home = _fix_49ers(home)
    away_row = df.loc[away]
    home_row = df.loc[home]

    # Away Offense vs Home Defense
    a_ypr = float(away_row["Offensive_Receiving_Yds/Rec"])
    a_td = float(away_row["Offensive_Receiving_TD"])
    a_1st = float(away_row["Offensive_Receiving_Rec 1st%"])

    h_d_ypr = float(home_row["Defensive_Receiving_Yds/Rec"])
    h_d_td = float(home_row["Defensive_Receiving_TD"])
    h_d_1st = float(home_row["Defensive_Receiving_Rec 1st%"])

    a_ypr_r = a_ypr / h_d_ypr
    try:
        a_td_r = a_td / h_d_td
    except ZeroDivisionError:
        a_td_r = a_td / 1
    a_1st_r = a_1st / h_d_1st

    a_rec = [a_ypr_r, a_td_r, a_1st_r]

    # Home Offense vs Away Defense
    h_ypr = float(home_row["Offensive_Receiving_Yds/Rec"])
    h_td = float(home_row["Offensive_Receiving_TD"])
    h_1st = float(home_row["Offensive_Receiving_Rec 1st%"])

    a_d_ypr = float(away_row["Defensive_Receiving_Yds/Rec"])
    a_d_td = float(away_row["Defensive_Receiving_TD"])
    a_d_1st = float(away_row["Defensive_Receiving_Rec 1st%"])

    h_ypr_r = h_ypr / a_d_ypr
    try:
        h_td_r = h_td / a_d_td
    except ZeroDivisionError:
        h_td_r = h_td / 1
    h_1st_r = h_1st / a_d_1st

    h_rec = [h_ypr_r, h_td_r, h_1st_r]

    return [a_rec, h_rec]


def provide_downs_metric(df: pd.DataFrame, away: str, home: str) -> list:
    """
    Returns [[away_downs_ratios], [home_downs_ratios]]
    Each list: [3rdDownSuccessRatio, 4thDownSuccessRatio]
    """
    away = _fix_49ers(away)
    home = _fix_49ers(home)
    away_row = df.loc[away]
    home_row = df.loc[home]

    # Away Offense vs Home Defense
    a_3att = float(away_row["Offensive_Downs_3rd Att"])
    a_3md = float(away_row["Offensive_Downs_3rd Md"])
    a_3sr = (a_3md / a_3att) * 100
    a_4att = float(away_row["Offensive_Downs_4th Att"])
    a_4md = float(away_row["Offensive_Downs_4th Md"])
    try:
        a_4sr = (a_4md / a_4att) * 100
    except ZeroDivisionError:
        a_4sr = 0

    h_d3att = float(home_row["Defensive_Downs_3rd Att"])
    h_d3md = float(home_row["Defensive_Downs_3rd Md"])
    h_d3sr = (h_d3md / h_d3att) * 100
    h_d4att = float(home_row["Defensive_Downs_4th Att"])
    h_d4md = float(home_row["Defensive_Downs_4th Md"])
    try:
        h_d4sr = (h_d4md / h_d4att) * 100
    except ZeroDivisionError:
        h_d4sr = 0

    try:
        a_3rd_ratio = a_3sr / (100 - h_d3sr)
    except ZeroDivisionError:
        a_3rd_ratio = 0
    try:
        a_4th_ratio = a_4sr / (100 - h_d4sr)
    except ZeroDivisionError:
        a_4th_ratio = 0

    a_downs = [a_3rd_ratio, a_4th_ratio]

    # Home Offense vs Away Defense
    h_3att = float(home_row["Offensive_Downs_3rd Att"])
    h_3md = float(home_row["Offensive_Downs_3rd Md"])
    h_3sr = (h_3md / h_3att) * 100
    h_4att = float(home_row["Offensive_Downs_4th Att"])
    h_4md = float(home_row["Offensive_Downs_4th Md"])
    try:
        h_4sr = (h_4md / h_4att) * 100
    except ZeroDivisionError:
        h_4sr = 0

    a_d3att = float(away_row["Defensive_Downs_3rd Att"])
    a_d3md = float(away_row["Defensive_Downs_3rd Md"])
    a_d3sr = (a_d3md / a_d3att) * 100
    a_d4att = float(away_row["Defensive_Downs_4th Att"])
    a_d4md = float(away_row["Defensive_Downs_4th Md"])
    try:
        a_d4sr = (a_d4md / a_d4att) * 100
    except ZeroDivisionError:
        a_d4sr = 0

    try:
        h_3rd_ratio = h_3sr / (100 - a_d3sr)
    except ZeroDivisionError:
        h_3rd_ratio = 0
    try:
        h_4th_ratio = h_4sr / (100 - a_d4sr)
    except ZeroDivisionError:
        h_4th_ratio = 0

    h_downs = [h_3rd_ratio, h_4th_ratio]

    return [a_downs, h_downs]


# ═══════════════════════════════════════════════════════════════════
#  Weighted Overall Ratios — VERBATIM weights from Escanor.py
# ═══════════════════════════════════════════════════════════════════

def overall_passing_ratio(away_ratios: list, home_ratios: list) -> list:
    """Passing sub-weights: CmpPer=25, Rate=35, 1stPer=10, Sacks=15, YPA=20"""
    w = [25, 35, 10, 15, 20]
    a = sum(w[i] * away_ratios[i] for i in range(5))
    h = sum(w[i] * home_ratios[i] for i in range(5))
    return [a, h]


def overall_rushing_ratio(away_ratios: list, home_ratios: list) -> list:
    """Rushing sub-weights: YPC=40, TDs=15, 1stPer=20, Yards=25"""
    w = [40, 15, 20, 25]
    a = sum(w[i] * away_ratios[i] for i in range(4))
    h = sum(w[i] * home_ratios[i] for i in range(4))
    return [a, h]


def overall_receiving_ratio(away_ratios: list, home_ratios: list) -> list:
    """Receiving sub-weights: YPRec=50, TDs=15, 1stPer=35"""
    w = [50, 15, 35]
    a = sum(w[i] * away_ratios[i] for i in range(3))
    h = sum(w[i] * home_ratios[i] for i in range(3))
    return [a, h]


def overall_downs_ratio(away_ratios: list, home_ratios: list) -> list:
    """Downs sub-weights: 3rd=80, 4th=20"""
    w = [80, 20]
    a = sum(w[i] * away_ratios[i] for i in range(2))
    h = sum(w[i] * home_ratios[i] for i in range(2))
    return [a, h]


# ═══════════════════════════════════════════════════════════════════
#  Main Prediction Logic
# ═══════════════════════════════════════════════════════════════════

def predict_matchup(df: pd.DataFrame, away_short: str, home_short: str) -> tuple:
    """
    Run the Escanor algorithm on a single matchup.

    Returns (winner_short, loser_short, confidence_factor)
    """
    # Top-level category weights — VERBATIM
    passing_weight = 0.33
    rushing_weight = 0.22
    receiving_weight = 0.18
    downs_weight = 0.27

    # Get ratios
    a_pass, h_pass = provide_passing_metric(df, away_short, home_short)
    a_rush, h_rush = provide_rushing_metric(df, away_short, home_short)
    a_rec, h_rec = provide_receiving_metric(df, away_short, home_short)
    a_downs, h_downs = provide_downs_metric(df, away_short, home_short)

    # Compute overall ratios
    away_pass_score, home_pass_score = overall_passing_ratio(a_pass, h_pass)
    away_rush_score, home_rush_score = overall_rushing_ratio(a_rush, h_rush)
    away_rec_score, home_rec_score = overall_receiving_ratio(a_rec, h_rec)
    away_downs_score, home_downs_score = overall_downs_ratio(a_downs, h_downs)

    # Apply category weights
    away_total = (
        passing_weight * away_pass_score
        + rushing_weight * away_rush_score
        + receiving_weight * away_rec_score
        + downs_weight * away_downs_score
    )
    home_total = (
        passing_weight * home_pass_score
        + rushing_weight * home_rush_score
        + receiving_weight * home_rec_score
        + downs_weight * home_downs_score
    )

    if away_total > home_total:
        winner = away_short
        loser = home_short
        differential = away_total - home_total
    else:
        winner = home_short
        loser = away_short
        differential = home_total - away_total

    return winner, loser, differential


def run_predictions(master_df: pd.DataFrame, matchups: list) -> list:
    """
    Run the algorithm on all matchups for the week.

    Parameters
    ----------
    master_df : pd.DataFrame — indexed by team short name, 108 stat columns
    matchups  : list of dicts from scraper.scrape_matchups()

    Returns
    -------
    list of dicts — each matchup dict enriched with prediction fields:
        pick_winner, pick_loser, confidence_factor, winning_pick_label
    """
    # Apply the 49Ers index fix just like the original
    if "49ers" in master_df.index:
        master_df.rename(index={"49ers": "49Ers"}, inplace=True)

    print(f"\n{'='*60}")
    print(f"  Running Escanor predictions on {len(matchups)} matchups")
    print(f"{'='*60}")

    results = []
    for m in matchups:
        away = m["away_team_short"]
        home = m["home_team_short"]

        winner, loser, cf = predict_matchup(master_df, away, home)

        # Build the "winning pick label" (e.g. "Patriots -13.5" or "Chiefs +13.5")
        favored = m.get("favored_team", "")
        spread_amt = m.get("spread_amount", 0.0)

        if winner in get_team_full_name(favored):
            # Winner IS the favored team — show negative spread
            winning_pick_label = f"{winner} {spread_amt}"
        else:
            # Winner is the underdog — show positive spread
            winning_pick_label = f"{winner} +{abs(spread_amt)}"

        enriched = {
            **m,
            "pick_winner": winner,
            "pick_loser": loser,
            "confidence_factor": round(cf, 4),
            "winning_pick_label": winning_pick_label,
            "favored_team_full": get_team_full_name(favored),
        }
        results.append(enriched)
        print(f"    {away} @ {home}  →  Pick: {winning_pick_label}  (CF: {cf:.4f})")

    # Sort by confidence factor descending
    results.sort(key=lambda r: r["confidence_factor"], reverse=True)

    return results


def save_current_week(results: list, week: int = None):
    """
    Save prediction results to data/current_week.json.
    Also computes rolling median CF from season_record.json if available.
    """
    if week is None:
        week = CURRENT_WEEK

    os.makedirs(DATA_DIR, exist_ok=True)

    # Compute rolling median CF from prior weeks + this week
    all_cfs = [r["confidence_factor"] for r in results]

    # Load any existing season record to include prior CFs
    record_path = data_path("season_record.json")
    if os.path.exists(record_path):
        with open(record_path, "r") as f:
            season_record = json.load(f)
        for wk in season_record.get("weeks", {}).values():
            for game in wk.get("games", []):
                if "confidence_factor" in game:
                    all_cfs.append(game["confidence_factor"])

    rolling_median_cf = round(statistics.median(all_cfs), 3) if all_cfs else 0.0

    # Identify top 5 and above-median picks
    top_5 = [r["winning_pick_label"] for r in results[:5]]
    above_median = [
        r["winning_pick_label"]
        for r in results
        if r["confidence_factor"] >= rolling_median_cf
    ]

    output = {
        "week": week,
        "rolling_median_cf": rolling_median_cf,
        "top_5_picks": top_5,
        "above_median_picks": above_median,
        "games": results,
    }

    filepath = data_path("current_week.json")
    with open(filepath, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Saved predictions to {filepath}")
    print(f"  Rolling Median CF: {rolling_median_cf}")

    return output


# ═══════════════════════════════════════════════════════════════════
#  CLI entry point
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("predictor.py should be called via run_week.py")
    print("Or import and call run_predictions() / save_current_week() directly.")
