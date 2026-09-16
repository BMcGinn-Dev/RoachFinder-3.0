"""
RoachFinder 3.0 — ESPN game data for Escanor v2

Pulls every regular-season game's team box score, final score and closing
line from ESPN's public JSON APIs, and turns them into per-team season-to-date
totals (offense, and defense = what opponents did against them).

Why ESPN box scores instead of NFL.com season pages:
  * point-in-time: stats "through week N" can be rebuilt for any past week,
    which is what makes an honest backtest possible
  * games played is known, so everything can be a rate (bye weeks don't skew)
  * scores + closing spreads come from the same place

Cache: data/history/games_<season>.json (finished seasons never refetch;
the current season only fetches games it doesn't have as final yet).
"""

import json
import os
import time
from collections import defaultdict

import requests

from config import DATA_DIR

API = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
HISTORY_DIR = os.path.join(DATA_DIR, "history")

# NOTE: no browser User-Agent. ESPN returns 403 to requests that claim to be
# Chrome but aren't; the default python-requests agent is accepted.


def _get(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200 and r.text.strip():
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1 + i)
    return None


# ── Compact game record (same shape the backtest cache files use) ─────

def compact_game(event, week, season, summary, odds):
    comp = event["competitions"][0]
    rec = {
        "id": event["id"], "season": season, "week": week,
        "date": event.get("date", ""),
        "status": comp["status"]["type"]["name"],
        "teams": {}, "box": {},
        "spread_home": None, "total": None,
    }
    for t in comp["competitors"]:
        rec["teams"][t["homeAway"]] = {
            "abbr": t["team"]["abbreviation"],
            "name": t["team"]["displayName"],
            "score": float(t.get("score") or 0),
        }

    box = (summary or {}).get("boxscore") or {}
    for t in box.get("teams", []):
        d = {}
        for s in t.get("statistics", []):
            d.setdefault(s["name"], s.get("displayValue"))
        rec["box"][t["team"]["abbreviation"]] = d
    for p in box.get("players", []):
        d = rec["box"].setdefault(p["team"]["abbreviation"], {})
        for cat in p.get("statistics", []):
            if cat.get("name") not in ("passing", "rushing") or not cat.get("totals"):
                continue
            keys = cat.get("keys", [])
            for i, k in enumerate(keys):
                if "touchdowns" in k.lower():
                    d[cat["name"] + "_td"] = cat["totals"][i]
                    break
            if "passingYards" in keys:
                d["gross_pass_yds"] = cat["totals"][keys.index("passingYards")]

    # Closing line: first pre-game book with a numeric spread, preferring
    # ESPN BET, then the consensus line, then DraftKings, then anyone.
    items = (odds or {}).get("items") or []

    def _prov(i):
        return ((i.get("provider") or {}).get("name") or "")

    usable = [i for i in items
              if "live" not in _prov(i).lower() and isinstance(i.get("spread"), (int, float))]
    order = ["ESPN BET", "consensus", "DraftKings"]
    usable.sort(key=lambda i: order.index(_prov(i)) if _prov(i) in order else len(order))
    item = usable[0] if usable else None
    if item:
        if isinstance(item.get("spread"), (int, float)):
            rec["spread_home"] = float(item["spread"])
        if isinstance(item.get("overUnder"), (int, float)):
            rec["total"] = float(item["overUnder"])
        rec["odds_provider"] = (item.get("provider") or {}).get("name")
        rec["odds_details"] = item.get("details")
    return rec


def _fetch_game(event, week, season):
    eid = event["id"]
    summary = _get(f"{API}/summary?event={eid}")
    odds = _get(f"{CORE}/events/{eid}/competitions/{eid}/odds")
    return compact_game(event, week, season, summary, odds)


def load_season_games(season, max_week=18, verbose=True):
    """Return compact records for all regular-season games up to max_week,
    using and updating the cache."""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    path = os.path.join(HISTORY_DIR, f"games_{season}.json")
    cached = {}
    if os.path.exists(path):
        with open(path, "r") as f:
            cached = {g["id"]: g for g in json.load(f)}

    finals = [g for g in cached.values() if g["status"] == "STATUS_FINAL"]
    if len(finals) >= 270 and max_week >= 18:
        return sorted(cached.values(), key=lambda g: (g["week"], g["date"]))

    todo = []
    for week in range(1, max_week + 1):
        sb = _get(f"{API}/scoreboard?seasontype=2&week={week}&dates={season}")
        for ev in (sb or {}).get("events", []):
            old = cached.get(ev["id"])
            if old and old["status"] == "STATUS_FINAL" and len(old["box"]) >= 2:
                continue
            status = ev["competitions"][0]["status"]["type"]["name"]
            if status != "STATUS_FINAL":
                continue
            todo.append((ev, week))

    if todo:
        if verbose:
            print(f"  ESPN: fetching {len(todo)} game(s) for {season}...")
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as pool:
            for rec in pool.map(lambda x: _fetch_game(x[0], x[1], season), todo):
                cached[rec["id"]] = rec

    games = sorted(cached.values(), key=lambda g: (g["week"], g["date"]))
    with open(path, "w") as f:
        json.dump(games, f)
    return games


# ── Box score parsing ──────────────────────────────────────────────────

def _pair(s, sep):
    try:
        a, b = str(s).split(sep)
        return float(a), float(b)
    except (ValueError, AttributeError):
        return 0.0, 0.0


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def parse_box(d):
    cmp_, att = _pair(d.get("completionAttempts"), "/")
    sacks, sack_yds = _pair(d.get("sacksYardsLost"), "-")
    t_m, t_a = _pair(d.get("thirdDownEff"), "-")
    f_m, f_a = _pair(d.get("fourthDownEff"), "-")
    rz_m, rz_a = _pair(d.get("redZoneAttempts"), "-")
    net_py = _num(d.get("netPassingYards"))
    gross = d.get("gross_pass_yds")
    return {
        "cmp": cmp_, "att": att,
        "gross_py": _num(gross) if gross is not None else net_py + sack_yds,
        "net_py": net_py,
        "pass_td": _num(d.get("passing_td")),
        "ints": _num(d.get("interceptions")),
        "sacks": sacks, "sack_yds": sack_yds,
        "fd_pass": _num(d.get("firstDownsPassing")),
        "rush_att": _num(d.get("rushingAttempts")),
        "rush_yds": _num(d.get("rushingYards")),
        "rush_td": _num(d.get("rushing_td")),
        "fd_rush": _num(d.get("firstDownsRushing")),
        "third_m": t_m, "third_a": t_a,
        "fourth_m": f_m, "fourth_a": f_a,
        "rz_m": rz_m, "rz_a": rz_a,
        "plays": _num(d.get("totalOffensivePlays")),
        "yards": _num(d.get("totalYards")),
        "drives": _num(d.get("totalDrives")),
        "turnovers": _num(d.get("turnovers")),
    }


STAT_KEYS = list(parse_box({}).keys()) + ["points"]


def short_name(display_name):
    """'Chicago Bears' -> 'Bears' (matches the matchup scraper's short names)."""
    return display_name.rsplit(" ", 1)[-1]


def team_totals(games, before_week=None):
    """Season-to-date totals per team (keyed by short name).

    Returns {team: {"gp": n, "off": {...}, "def": {...}}}; 'def' holds what
    opponents did against that team.
    """
    tot = defaultdict(lambda: {"gp": 0, "off": defaultdict(float), "def": defaultdict(float)})
    for g in games:
        if g["status"] != "STATUS_FINAL" or len(g["box"]) < 2:
            continue
        if before_week is not None and g["week"] >= before_week:
            continue
        h, a = g["teams"]["home"], g["teams"]["away"]
        hb, ab = g["box"].get(h["abbr"]), g["box"].get(a["abbr"])
        if hb is None or ab is None:
            continue
        hs, as_ = parse_box(hb), parse_box(ab)
        hs["points"], as_["points"] = h["score"], a["score"]
        for me, mine, theirs in ((h, hs, as_), (a, as_, hs)):
            t = tot[short_name(me["name"])]
            t["gp"] += 1
            for k in STAT_KEYS:
                t["off"][k] += mine[k]
                t["def"][k] += theirs[k]
    return {k: {"gp": v["gp"], "off": dict(v["off"]), "def": dict(v["def"])} for k, v in tot.items()}
