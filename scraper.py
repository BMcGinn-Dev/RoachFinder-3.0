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

    # Separate header row and body rows (look up <thead>/<tbody> directly —
    # a length-based filter breaks whenever the header row count changes)
    header_section = table.find("thead")
    body_section = table.find("tbody")
    if header_section is None or body_section is None:
        raise RuntimeError(f"Could not find thead/tbody in stats table at {url}")

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

ESPN_SCOREBOARD_API = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
)


def _to_eastern(iso_utc: str) -> str:
    """Convert ESPN's UTC kickoff ('2026-09-18T00:15Z') to e.g. '8:15 PM' ET.
    US DST rule computed by hand so no tzdata package is needed on Windows."""
    from datetime import datetime, timedelta, timezone
    try:
        utc = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return "TBD"
    y = utc.year
    # DST: 2nd Sunday of March 07:00 UTC -> 1st Sunday of November 06:00 UTC
    mar1 = datetime(y, 3, 1, tzinfo=timezone.utc)
    dst_start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7 + 7, hours=7)
    nov1 = datetime(y, 11, 1, tzinfo=timezone.utc)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7, hours=6)
    offset = -4 if dst_start <= utc < dst_end else -5
    local = utc + timedelta(hours=offset)
    return local.strftime("%I:%M %p").lstrip("0")


def scrape_matchups(week: int = None, year: int = None) -> list:
    """
    Pull the week's NFL matchups from ESPN's public scoreboard API and return
    a list of matchup dictionaries.

    (The ESPN schedule HTML page now blocks scripted requests with an empty
    HTTP 202, so the old HTML scraper no longer works.)

    Each dict contains:
      away_team, home_team, away_team_short, home_team_short,
      away_team_city, home_team_city, game_time, cheapest_ticket,
      stadium, spread_line, over_under, favored_team, spread_amount
    """
    if week is None:
        week = CURRENT_WEEK
    if year is None:
        year = CURRENT_SEASON_START_YEAR

    print(f"\n{'='*60}")
    print(f"  Fetching ESPN matchups — Week {week}, {year}")
    print(f"{'='*60}")

    params = {"seasontype": 2, "week": week, "dates": year}
    # No REQUEST_HEADERS here: ESPN's API returns 403 to requests that claim
    # to be Chrome but aren't. The default python-requests User-Agent works.
    response = requests.get(ESPN_SCOREBOARD_API, params=params, timeout=30)
    response.raise_for_status()
    if not response.text.strip():
        raise RuntimeError(
            f"ESPN API returned HTTP {response.status_code} with an empty body"
        )
    events = response.json().get("events", [])

    matchups = []
    for event in events:
        comp = (event.get("competitions") or [{}])[0]
        teams = {c.get("homeAway"): c.get("team", {}) for c in comp.get("competitors", [])}
        home, away = teams.get("home"), teams.get("away")
        if not home or not away:
            print(f"    WARNING: Could not parse teams for: {event.get('name')}")
            continue

        away_team_full = away.get("displayName", "")
        home_team_full = home.get("displayName", "")
        away_short = away_team_full.rsplit(" ", 1)[-1]
        home_short = home_team_full.rsplit(" ", 1)[-1]

        # Stadium: "Highmark Stadium, Orchard Park, NY"
        venue = comp.get("venue", {})
        addr = venue.get("address", {})
        stadium = ", ".join(
            x for x in (venue.get("fullName"), addr.get("city"), addr.get("state")) if x
        ) or "Unknown"

        # Cheapest ticket: last 4 chars of "Tickets as low as $452"
        tickets = comp.get("tickets") or []
        summary = tickets[0].get("summary", "") if tickets else ""
        cheapest_ticket = summary[-4:].strip() if summary else "N/A"

        # Odds: details "BUF -4.5", overUnder 54.5
        spread_str = ""
        over_under_str = ""
        favored_team = ""
        spread_amount = 0.0
        odds = (comp.get("odds") or [{}])[0]
        details = (odds.get("details") or "").strip()
        if details:
            spread_str = details
            parts = details.rsplit(" ", 1)
            if len(parts) == 2:
                try:
                    spread_amount = float(parts[1])
                    favored_team = parts[0].strip()
                except ValueError:
                    spread_amount = 0.0   # e.g. "EVEN"
        spread_home = odds.get("spread")
        spread_home = float(spread_home) if isinstance(spread_home, (int, float)) else None
        if spread_home is None and favored_team and spread_str:
            # Fall back to the "BUF -4.5" text: negative if the home team is favored
            home_abbr = home.get("abbreviation", "")
            spread_home = spread_amount if favored_team == home_abbr else -spread_amount
        ou = odds.get("overUnder")
        if ou is not None:
            over_under_str = f"{float(ou):g}"

        matchup = {
            "week_number": week,
            "away_team": away_team_full,
            "home_team": home_team_full,
            "away_team_short": away_short,
            "home_team_short": home_short,
            "away_team_city": away.get("location", ""),
            "home_team_city": home.get("location", ""),
            "game_time": _to_eastern(event.get("date", "")),
            "cheapest_ticket": cheapest_ticket,
            "stadium": stadium,
            "spread_line": spread_str,
            "over_under": over_under_str,
            "favored_team": favored_team,
            "spread_amount": spread_amount,
            "spread_home": spread_home,
        }
        matchups.append(matchup)
        print(f"    Game {len(matchups)}: {away_short} @ {home_short}  {spread_str}")

    print(f"\n  Total matchups: {len(matchups)}")
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
