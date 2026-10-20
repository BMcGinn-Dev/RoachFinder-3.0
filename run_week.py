"""
RoachFinder 3.0 — Weekly Pipeline Entry Point

Usage:
    python run_week.py          # Uses CURRENT_WEEK from config.py
    python run_week.py --week 5 # Override the week number

Steps:
    1. Scrape all team stats from NFL.com (13 categories)
    2. Scrape matchups from ESPN
    3. Run the Escanor prediction algorithm
    4. Save results to data/current_week.json
    5. Copy data/ into site/data/ for deployment
"""

import argparse
import os
import shutil
import json

from config import (CURRENT_WEEK, ACTIVE_WEEKS, DATA_DIR, SITE_DATA_DIR,
                    MODEL_VERSION, CURRENT_SEASON_START_YEAR)
from scraper import scrape_all_stats, scrape_matchups, save_raw_stats
from predictor import run_predictions, save_current_week
from export_picks import export_week_to_excel
from escanor_v2 import run_predictions_v2


def copy_data_to_site():
    """Copy the data/ folder contents into site/data/ for static hosting."""
    os.makedirs(SITE_DATA_DIR, exist_ok=True)
    for filename in os.listdir(DATA_DIR):
        src = os.path.join(DATA_DIR, filename)
        dst = os.path.join(SITE_DATA_DIR, filename)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
    print(f"\n  Copied data/ → site/data/")


def check_lines(matchups, week):
    """Guard against running v2 on a week whose betting lines are gone.

    ESPN strips the odds object from a game once it goes final, so re-running a
    week that has already been played returns spread_home = None for every game.
    Escanor v2 picks against the spread; with no line, choose_side() silently
    falls back to a straight-up pick and the labels read "(no line)". Fail loudly
    instead.

    Returns True if the run should proceed.
    """
    missing = [m for m in matchups if m.get("spread_home") is None]
    if not missing:
        return True

    def label(m):
        return f"{m['away_team_short']} @ {m['home_team_short']}"

    if len(missing) == len(matchups):
        print(f"\n  ERROR: none of the {len(matchups)} Week {week} games came back with a")
        print("  betting line. ESPN drops the odds once a game goes final, so Week")
        print(f"  {week} has most likely already been played.")
        print(f"  config.py has CURRENT_WEEK = {CURRENT_WEEK}; set it to the upcoming week")
        print("  (or pass --week N) and rerun. Aborting rather than emitting")
        print("  straight-up picks labelled as spread picks.\n")
        return False

    print(f"\n  WARNING: {len(missing)} of {len(matchups)} Week {week} games have no line.")
    print("  These will fall back to straight-up picks labelled \"(no line)\":")
    for m in missing:
        print(f"    - {label(m)}")
    print("  Proceeding with the rest.\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="RoachFinder 3.0 — Weekly Pipeline")
    parser.add_argument(
        "--week", type=int, default=CURRENT_WEEK,
        help=f"NFL week number to process (default: {CURRENT_WEEK})"
    )
    args = parser.parse_args()

    week = args.week
    if week not in ACTIVE_WEEKS:
        print(f"\n  WARNING: Week {week} is outside the active range ({ACTIVE_WEEKS.start}-{ACTIVE_WEEKS.stop - 1}).")
        print(f"  RoachFinder only operates on Weeks 2-16. Proceeding anyway...\n")

    print(f"\n{'#'*60}")
    print(f"  RoachFinder 3.0 — Processing Week {week}")
    print(f"{'#'*60}")

    if MODEL_VERSION == "v2":
        # Step 1-3 (v2): matchups + lines from ESPN, team stats from ESPN box scores
        matchups = scrape_matchups(week)
        if not matchups:
            print("\n  ERROR: No matchups found. Is the ESPN schedule available for this week?")
            return
        if not check_lines(matchups, week):
            return
        results = run_predictions_v2(matchups, CURRENT_SEASON_START_YEAR, week)
    else:
        # Step 1: Scrape team stats
        master_df = scrape_all_stats()
        save_raw_stats(master_df, week)

        # Step 2: Scrape matchups
        matchups = scrape_matchups(week)

        if not matchups:
            print("\n  ERROR: No matchups found. Is the ESPN schedule available for this week?")
            return

        # Step 3: Run predictions
        results = run_predictions(master_df, matchups)

    # Step 4: Save results
    save_current_week(results, week)

    # Step 5: Copy to site/data/
    copy_data_to_site()

    # Step 6: Save picks to the season Excel workbook
    export_week_to_excel()

    print(f"\n{'#'*60}")
    print(f"  Done! Week {week} predictions are ready.")
    print(f"  Next steps:")
    print(f"    1. Review data/current_week.json")
    print(f"    2. git add -A, commit, push; then git pull on PythonAnywhere + Reload")
    print(f"    3. After games: python enter_results.py")
    print(f"{'#'*60}\n")


if __name__ == "__main__":
    main()
