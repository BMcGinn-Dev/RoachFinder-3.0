"""
RoachFinder 3.0 — Central Configuration
Update these values each season. Everything else reads from here.
"""

# ── Season Identity ──────────────────────────────────────────────
SEASON_LABEL = "2026-27"              # Short label (nav, filenames)
SEASON_LABEL_LONG = "2026-2027"       # Long label (display headings)
CURRENT_SEASON_START_YEAR = 2026      # Year the NFL season kicks off
ACTIVE_WEEKS = range(2, 17)           # Weeks 2-16 inclusive (Week 1 & 17 excluded)

# ── Current Week (update before each run_week.py execution) ──────
CURRENT_WEEK = 3                      # Set to the upcoming week number

# ── Prediction model ─────────────────────────────────────────────
# "v2" = Escanor v2 (ESPN box scores, picks against the spread; needs
#        data/escanor_v2_params.json from  python backtest.py)
# "v1" = original Escanor (NFL.com season stats, straight-up pick)
MODEL_VERSION = "v2"

# ── Data Sources ─────────────────────────────────────────────────
ESPN_SCHEDULE_URL = "https://www.espn.com/nfl/schedule/_/week/{week}/year/{year}/seasontype/2"
NFL_STATS_BASE_URL = "https://www.nfl.com/stats/team-stats"

# NFL.com stat page paths: (side, category, url_segment)
STAT_PAGES = [
    # Defense
    ("Defensive", "Downs",          "defense/downs"),
    ("Defensive", "Fumbles",        "defense/fumbles"),
    ("Defensive", "Interceptions",  "defense/interceptions"),
    ("Defensive", "Passing",        "defense/passing"),
    ("Defensive", "Receiving",      "defense/receiving"),
    ("Defensive", "Rushing",        "defense/rushing"),
    ("Defensive", "Scoring",        "defense/scoring"),
    ("Defensive", "Tackles",        "defense/tackles"),
    # Offense
    ("Offensive", "Downs",          "offense/downs"),
    ("Offensive", "Passing",        "offense/passing"),
    ("Offensive", "Receiving",      "offense/receiving"),
    ("Offensive", "Rushing",        "offense/rushing"),
    ("Offensive", "Scoring",        "offense/scoring"),
]

# ── File Paths ───────────────────────────────────────────────────
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
SITE_DATA_DIR = os.path.join(PROJECT_ROOT, "site", "data")

def data_path(filename):
    """Return absolute path to a file in the data/ directory."""
    return os.path.join(DATA_DIR, filename)

def site_data_path(filename):
    """Return absolute path to a file in the site/data/ directory."""
    return os.path.join(SITE_DATA_DIR, filename)

# ── Affiliate ────────────────────────────────────────────────────
DRAFTKINGS_AFFILIATE_URL = "https://sportsbook.draftkings.com/r/sb/roachjohnson/US-IL-SB"

# ── Team Abbreviation Mapping ────────────────────────────────────
TEAM_ABBREVIATIONS = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB":  "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC":  "Kansas City Chiefs",
    "LV":  "Las Vegas Raiders",
    "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE":  "New England Patriots",
    "NO":  "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SF":  "San Francisco 49ers",
    "SEA": "Seattle Seahawks",
    "TB":  "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WSH": "Washington Commanders",
}

def get_team_full_name(abbreviation):
    """Look up full team name from abbreviation. Returns abbreviation if not found."""
    return TEAM_ABBREVIATIONS.get(abbreviation.strip(), abbreviation.strip())

# ── Request Headers (shared by all scrapers) ─────────────────────
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── Scrape Delay (seconds between HTTP requests) ────────────────
SCRAPE_DELAY = 2
