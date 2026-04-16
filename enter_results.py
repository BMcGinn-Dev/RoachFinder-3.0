"""
RoachFinder 3.0 — Enter Results CLI

After each week's games complete, run this to record W/L/Push for each pick.
Updates data/season_record.json with results and recalculates cumulative records.

Usage:
    python enter_results.py              # Enter results for CURRENT_WEEK
    python enter_results.py --week 5     # Enter results for a specific week
"""

import argparse
import json
import os
import statistics

from config import CURRENT_WEEK, DATA_DIR, SITE_DATA_DIR, data_path


def load_season_record() -> dict:
    """Load existing season record or create a fresh one."""
    path = data_path("season_record.json")
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {
        "cumulative": {
            "all_spreads": {"wins": 0, "losses": 0, "pushes": 0},
            "above_median": {"wins": 0, "losses": 0, "pushes": 0},
            "top_5": {"wins": 0, "losses": 0, "pushes": 0},
        },
        "weeks": {},
    }


def load_current_week(week: int) -> dict:
    """Load the predictions for a given week."""
    path = data_path("current_week.json")
    if not os.path.exists(path):
        print(f"  ERROR: data/current_week.json not found. Run run_week.py first.")
        return None
    with open(path, "r") as f:
        data = json.load(f)
    if data.get("week") != week:
        print(f"  WARNING: current_week.json is for Week {data.get('week')}, not Week {week}.")
        print(f"  Make sure you're entering results for the correct week.")
    return data


def recalculate_cumulative(record: dict):
    """Recalculate cumulative records from all weeks' data."""
    cumulative = {
        "all_spreads": {"wins": 0, "losses": 0, "pushes": 0},
        "above_median": {"wins": 0, "losses": 0, "pushes": 0},
        "top_5": {"wins": 0, "losses": 0, "pushes": 0},
    }

    for week_key, week_data in record["weeks"].items():
        for game in week_data.get("games", []):
            result = game.get("result", "")
            if result == "win":
                cumulative["all_spreads"]["wins"] += 1
                if game.get("above_median"):
                    cumulative["above_median"]["wins"] += 1
                if game.get("top_5"):
                    cumulative["top_5"]["wins"] += 1
            elif result == "loss":
                cumulative["all_spreads"]["losses"] += 1
                if game.get("above_median"):
                    cumulative["above_median"]["losses"] += 1
                if game.get("top_5"):
                    cumulative["top_5"]["losses"] += 1
            elif result == "push":
                cumulative["all_spreads"]["pushes"] += 1
                if game.get("above_median"):
                    cumulative["above_median"]["pushes"] += 1
                if game.get("top_5"):
                    cumulative["top_5"]["pushes"] += 1

    # Add win percentages
    for cat in cumulative.values():
        total = cat["wins"] + cat["losses"]
        cat["win_pct"] = round(cat["wins"] / total * 100, 3) if total > 0 else 0.0

    record["cumulative"] = cumulative


def enter_results_for_week(week: int):
    """Interactive CLI to enter results for each game in a week."""
    record = load_season_record()
    week_data = load_current_week(week)

    if week_data is None:
        return

    week_key = str(week)
    if week_key in record["weeks"]:
        print(f"\n  Week {week} already has results recorded.")
        overwrite = input("  Overwrite? (y/n): ").strip().lower()
        if overwrite != "y":
            print("  Cancelled.")
            return

    games = week_data.get("games", [])
    if not games:
        print("  No games found in current_week.json.")
        return

    rolling_median_cf = week_data.get("rolling_median_cf", 0)
    top_5_labels = week_data.get("top_5_picks", [])

    print(f"\n{'='*60}")
    print(f"  Enter results for Week {week} ({len(games)} games)")
    print(f"  Rolling Median CF: {rolling_median_cf}")
    print(f"  For each game, enter: w (win), l (loss), or p (push)")
    print(f"{'='*60}\n")

    week_games = []
    for i, game in enumerate(games, 1):
        label = game.get("winning_pick_label", "???")
        cf = game.get("confidence_factor", 0)
        is_top5 = label in top_5_labels
        is_above_med = cf >= rolling_median_cf

        tags = []
        if is_top5:
            tags.append("TOP5")
        if is_above_med:
            tags.append(">=MED")
        tag_str = f"  [{', '.join(tags)}]" if tags else ""

        while True:
            result = input(f"  {i}. {label} (CF: {cf:.4f}){tag_str}  → w/l/p: ").strip().lower()
            if result in ("w", "l", "p"):
                break
            print("    Invalid. Enter w, l, or p.")

        result_map = {"w": "win", "l": "loss", "p": "push"}

        week_games.append({
            "pick": label,
            "confidence_factor": cf,
            "result": result_map[result],
            "above_median": is_above_med,
            "top_5": is_top5,
            "away_team": game.get("away_team_short", ""),
            "home_team": game.get("home_team_short", ""),
        })

    # Save week results
    record["weeks"][week_key] = {"games": week_games}

    # Recalculate cumulative
    recalculate_cumulative(record)

    # Recalculate rolling median CF across all weeks
    all_cfs = []
    for wk in record["weeks"].values():
        for g in wk.get("games", []):
            if "confidence_factor" in g:
                all_cfs.append(g["confidence_factor"])
    record["rolling_median_cf"] = round(statistics.median(all_cfs), 3) if all_cfs else 0.0

    # Save
    os.makedirs(DATA_DIR, exist_ok=True)
    filepath = data_path("season_record.json")
    with open(filepath, "w") as f:
        json.dump(record, f, indent=2)

    # Print summary
    c = record["cumulative"]
    print(f"\n{'='*60}")
    print(f"  Week {week} results saved!")
    print(f"  Season Record (cumulative):")
    print(f"    All Spreads:   {c['all_spreads']['wins']}-{c['all_spreads']['losses']}-{c['all_spreads']['pushes']}  ({c['all_spreads']['win_pct']}%)")
    print(f"    Above Median:  {c['above_median']['wins']}-{c['above_median']['losses']}-{c['above_median']['pushes']}  ({c['above_median']['win_pct']}%)")
    print(f"    Top 5:         {c['top_5']['wins']}-{c['top_5']['losses']}-{c['top_5']['pushes']}  ({c['top_5']['win_pct']}%)")
    print(f"{'='*60}\n")

    # Copy updated data to site/
    import shutil
    os.makedirs(SITE_DATA_DIR, exist_ok=True)
    for filename in os.listdir(DATA_DIR):
        src = os.path.join(DATA_DIR, filename)
        dst = os.path.join(SITE_DATA_DIR, filename)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
    print(f"  Updated data copied to site/data/\n")


def main():
    parser = argparse.ArgumentParser(description="RoachFinder 3.0 — Enter Game Results")
    parser.add_argument(
        "--week", type=int, default=CURRENT_WEEK,
        help=f"Week number to enter results for (default: {CURRENT_WEEK})"
    )
    args = parser.parse_args()
    enter_results_for_week(args.week)


if __name__ == "__main__":
    main()
