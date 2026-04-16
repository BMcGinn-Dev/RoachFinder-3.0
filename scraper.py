"""
RoachFinder 3.0 — Unified Scraper
Consolidates the original 13 individual stat-scraper files + GetMatchups.py
into a single module.

Outputs:
  - data/raw_week_XX.json   (master team stats — 32 teams x 108 stat columns)
  - Weekly matchup data returned as a list of dicts for predictor.py
"""

import json
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from functools import reduce

from config import (
    CURRENT_WEEK,
    CURRENT_SEASON_START_YEAR,
    ESPN_SCHEDULE_URL,
    NFL_STATS_BASE_URL,
    STAT_PAGES,
    REQUEST_HEADERS,
    SCRAPE_DELAY,
    DATA_DIR,
    data_path,
)


# ═══════════════════════════════════════════════════════════════════
#  NFL.com Team Stats Scraper  (replaces 13 individual Get*.py files)
# ═══════════════════════════════════════════════════════════════════

def _scrape_nfl_stat_page(side: str, category: str, url_segment: str, year: int) -> pd.DataFrame:
    """
    Scrape a single NFL.com team-stats page and return a DataFrame.

    Parameters
    ----------
    side : str        – "Defensive" or "Offensive"
    category : str    – e.g. "Passing", "Rushing", "Downs"
    url_segment : str – e.g. "offense/passing"
    year : int        – NFL season start year

    Returns
    -------
    pd.DataFrame with 32 rows (one per team). Column names are prefixed
    with "{side}_{category}_" except for the "Team" column.
    """
    url = f"{NFL_STATS_BASE_URL}/{url_segment}/{year}/reg/all"
    prefix = f"{side}_{category}_"

    print(f"  Scraping {side} {category}...")
    response = requests.get(url, headers=REQUEST_HEADERS)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    table = soup.find(
        "table",
        class_="d3-o-table d3-o-table--detailed d3-o-team-stats--detailed "
               "d3-o-table--sortable {sortlist: [[0,0]], sortinitialorder: 'asc'}",
    )
    if table is None:
        raise RuntimeError(f"Could not find stats table at {url}")

    # Separate header row and body rows (skip empty tags)
    good_sections = [tag for tag in table if len(tag) > 1]
    header_section = good_sections[0]
    body_section = good_sections[1]

    # ── Extract column headers ──
    raw_headers = [th.text.strip() for th in header_section.find_all("th")]
    columns = []
    for h in raw_headers:
        columns.append(h if h == "Team" else f"{prefix}{h}")

    # ── Extract body rows ──
    rows = []
    for tr in body_section:
        if len(tr) == 1:
            continue
        team_div = tr.find("div", class_="d3-o-club-fullname")
        if team_div is None:
            continue
        team_name = team_div.text.strip()
        tds = tr.find_all("td")
        values = [team_name] + [td.text.strip() for td in tds[1:]]
        rows.append(values)

    df = pd.DataFrame(rows, columns=columns)

    if len(df) != 32:
        print(f"    WARNING: Expected 32 teams, got {len(df)} for {side} {category}")
    else:
        print(f"    OK — 32 teams scraped for {side} {category}")

    time.sleep(SCRAPE_DELAY)
    return df


def scrape_all_stats(year: int = None) -> pd.DataFrame:
    """
    Scrape all 13 stat categories from NFL.com and merge into a single
    master DataFrame (32 rows x ~108 stat columns), indexed by team short name.

    This replaces the original:
      PopulationStation.py → imports 13 Get*.py files
      PopulationStation_MergeMaster_Child.py → merges them
      MergeMaster.py → also merges them
    """
    if year is None:
        year = CURRENT_SEASON_START_YEAR

    print(f"\n{'='*60}")
    print(f"  Scraping NFL.com team stats for {year} season")
    print(f"{'='*60}")

    dfs = []
    for side, category, url_segment in STAT_PAGES:
        df = _scrape_nfl_stat_page(side, category, url_segment, year)
        dfs.append(df)

    # Merge all DataFrames on the "Team" column
    master_df = reduce(
        lambda left, right: pd.merge(left, right, on="Team", how="inner"),
        dfs,
    )

    print(f"\n  Master DataFrame: {len(master_df)} teams x {master_df.shape[1]} columns")
    if len(master_df) != 32:
        raise RuntimeError(f"Master merge resulted in {len(master_df)} teams instead of 32!")

    # Set Team as index (short name = last word of full name)
    master_df.index = master_df["Team"].apply(lambda t: t.rsplit(" ", 1)[-1])
    master_df.drop(columns=["Team"], inplace=True)

    return master_df


# ═══════════════════════════════════════════════════════════════════
#  ESPN Matchups Scraper  (replaces GetMatchups.py)
# ═══════════════════════════════════════════════════════════════════

def scrape_matchups(week: int = None, year: int = None) -> list:
    """
    Scrape the ESPN NFL schedule page for a given week and return a list
    of matchup dictionaries.

    Each dict contains:
      away_team, home_team, away_team_short, home_team_short,
      away_team_city, home_team_city, game_time, cheapest_ticket,
      stadium, spread_line, over_under, favored_team, spread_amount
    """
    if week is None:
        week = CURRENT_WEEK
    if year is None:
        year = CURRENT_SEASON_START_YEAR

    url = ESPN_SCHEDULE_URL.format(week=week, year=year)

    print(f"\n{'='*60}")
    print(f"  Scraping ESPN matchups — Week {week}, {year}")
    print(f"{'='*60}")

    response = requests.get(url, headers=REQUEST_HEADERS)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    target_class = "ScheduleTables mb5 ScheduleTables--nfl ScheduleTables--football"
    divs = soup.find_all("div", attrs={"class": target_class})

    matchups = []
    game_count = 0

    for div in divs:
        trs = div.find_all("tr")
        trs.pop(0)  # First row is always a header — discard

        for tr in trs:
            # ── Parse team names from <a> tag data attributes ──
            a_tag = tr.find("a", class_=lambda c: c and "zZygg" in c)
            if not a_tag:
                continue

            extras_json = a_tag.get("data-track-extras", "{}")
            extras = json.loads(extras_json)
            game_detail = extras.get("game_detail", "")

            # Remove leading ID and split "TeamA vs TeamB"
            team_part = " ".join(game_detail.split()[1:])
            if " vs " not in team_part:
                print(f"    WARNING: Could not parse teams from: {team_part}")
                continue

            away_team_full, home_team_full = team_part.split(" vs ")
            away_short = away_team_full.rsplit(" ", 1)[-1]
            home_short = home_team_full.rsplit(" ", 1)[-1]

            # ── Parse table cell values ──
            td_values = []
            for td in tr.find_all("td"):
                text = td.text.strip()
                if text:
                    td_values.append(text)
                else:
                    td_values.append("DNF")

            # td_values layout (after ESPN's HTML):
            #   [0] Away city display, [1] Home city display (with prefix),
            #   [2] Time, [3] ???, [4] Ticket (last 4 chars), [5] Stadium,
            #   [6] "Line: XXX O/U: YYY"

            # Fix home team city — strip first 5 chars (ESPN prefix artifact)
            if len(td_values) > 1:
                td_values[1] = td_values[1][5:] if len(td_values[1]) > 5 else td_values[1]

            # Extract cheapest ticket (last 4 chars of the ticket cell)
            cheapest_ticket = "N/A"
            if len(td_values) > 4:
                cheapest_ticket = td_values[4][-4:].strip()

            # Parse spread and over/under from combined field
            spread_str = ""
            over_under_str = ""
            favored_team = ""
            spread_amount = 0.0

            if len(td_values) > 6:
                combined = td_values[6]
                line_part, _, ou_part = combined.partition("O/U:")
                line_part = line_part.replace("Line:", "").strip()
                over_under_str = ou_part.strip()
                spread_str = line_part

                # Parse "KC -3" into team abbr and spread number
                if spread_str and spread_str != "DNF":
                    spread_parts = spread_str.rsplit(" ", 1)
                    if len(spread_parts) == 2:
                        favored_team = spread_parts[0].strip()
                        try:
                            spread_amount = float(spread_parts[1])
                        except ValueError:
                            spread_amount = 0.0

            stadium = td_values[5] if len(td_values) > 5 else "Unknown"
            game_time = td_values[2] if len(td_values) > 2 else "TBD"

            matchup = {
                "week_number": week,
                "away_team": away_team_full,
                "home_team": home_team_full,
                "away_team_short": away_short,
                "home_team_short": home_short,
                "away_team_city": td_values[0] if td_values else "",
                "home_team_city": td_values[1] if len(td_values) > 1 else "",
                "game_time": game_time,
                "cheapest_ticket": cheapest_ticket,
                "stadium": stadium,
                "spread_line": spread_str,
                "over_under": over_under_str,
                "favored_team": favored_team,
                "spread_amount": spread_amount,
            }

            matchups.append(matchup)
            game_count += 1
            print(f"    Game {game_count}: {away_short} @ {home_short}")

    print(f"\n  Total matchups scraped: {game_count}")
    return matchups


# ═══════════════════════════════════════════════════════════════════
#  Save raw stats to JSON
# ═══════════════════════════════════════════════════════════════════

def save_raw_stats(master_df: pd.DataFrame, week: int = None):
    """Save the master stats DataFrame to data/raw_week_XX.json."""
    import os
    if week is None:
        week = CURRENT_WEEK
    os.makedirs(DATA_DIR, exist_ok=True)

    filepath = data_path(f"raw_week_{week:02d}.json")
    master_df.to_json(filepath, orient="index", indent=2)
    print(f"\n  Saved raw stats to {filepath}")


# ═══════════════════════════════════════════════════════════════════
#  CLI entry point (can be run standalone for testing)
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    stats_df = scrape_all_stats()
    save_raw_stats(stats_df)

    matchups = scrape_matchups()
    print(f"\nMatchups preview:")
    for m in matchups[:3]:
        print(f"  {m['away_team_short']} @ {m['home_team_short']} — {m['spread_line']}")
