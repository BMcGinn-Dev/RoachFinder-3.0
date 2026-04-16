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

from config import CURRENT_WEEK, ACTIVE_WEEKS, DATA_DIR, SITE_DATA_DIR
from scraper import scrape_all_stats, scrape_matchups, save_raw_stats
from predictor import run_predictions, save_current_week


def copy_data_to_site():
    """Copy the data/ folder contents into site/data/ for static hosting."""
    os.makedirs(SITE_DATA_DIR, exist_ok=True)
    for filename in os.listdir(DATA_DIR):
        src = os.path.join(DATA_DIR, filename)
        dst = os.path.join(SITE_DATA_DIR, filename)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
    print(f"\n  Copied data/ → site/data/")


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

    print(f"\n{'#'*60}")
    print(f"  Done! Week {week} predictions are ready.")
    print(f"  Next steps:")
    print(f"    1. Review data/current_week.json")
    print(f"    2. Upload site/ folder to cPanel")
    print(f"    3. After games: python enter_results.py")
    print(f"{'#'*60}\n")


if __name__ == "__main__":
    main()
