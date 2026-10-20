"""
RoachFinder 3.0 — Backfill a missed week's picks and results

Use this when a week was skipped entirely. ESPN's scoreboard API drops the
`odds` object once a game goes final, so scrape_matchups() returns no lines
for a week that has already been played and run_week.py refuses to run. This
script fills the lines back in from ESPN's core odds endpoint, which *does*
retain closing lines after the fact, reconstructs the picks, and grades them
against the final scores.

    python backfill_week.py --week 6
    python backfill_week.py --week 6 --dry-run    # print everything, write nothing
    python backfill_week.py --week 6 --force      # overwrite an existing week

What this is and isn't: the model inputs are point-in-time correct (team
stats only from weeks before the target week, same escanor_v2_params.json),
so the picks match what the model would have produced. But they were
generated after the games were played, so the week is tagged
"backfilled": true in season_record.json rather than passed off as live.
"""

import argparse
import json
import os
import shutil
import statistics

from config import (CURRENT_SEASON_START_YEAR, DATA_DIR, SITE_DATA_DIR,
                    data_path)
from scraper import scrape_matchups
from predictor import save_current_week
from escanor_v2 import run_predictions_v2
from espn_data import _get, API, CORE
from enter_results import load_season_record, recalculate_cumulative


# ── ESPN: scores and retained closing lines ──────────────────────────

def fetch_week_events(week, season):
    """Return {(away_display, home_display): {eid, status, away_score, home_score}}."""
    sb = _get(f"{API}/scoreboard?seasontype=2&week={week}&dates={season}")
    if not sb:
        raise RuntimeError(f"ESPN scoreboard request failed for Week {week}, {season}")

    events = {}
    for ev in sb.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        home, away = teams.get("home"), teams.get("away")
        if not home or not away:
            continue
        key = (away["team"].get("displayName", ""), home["team"].get("displayName", ""))
        events[key] = {
            "eid": ev["id"],
            "status": ((comp.get("status") or {}).get("type") or {}).get("name"),
            "away_score": float(away.get("score") or 0),
            "home_score": float(home.get("score") or 0),
        }
    return events


def fetch_closing_line(eid):
    """Return (spread_home, over_under, details) from the core odds endpoint.

    Mirrors espn_data.compact_game's book preference so a backfilled line
    matches what the cache/backtest would have used.
    """
    odds = _get(f"{CORE}/events/{eid}/competitions/{eid}/odds")
    items = (odds or {}).get("items") or []

    def prov(i):
        return ((i.get("provider") or {}).get("name") or "")

    usable = [i for i in items
              if "live" not in prov(i).lower()
              and isinstance(i.get("spread"), (int, float))]
    order = ["ESPN BET", "consensus", "DraftKings"]
    usable.sort(key=lambda i: order.index(prov(i)) if prov(i) in order else len(order))
    if not usable:
        return None, None, None, None
    item = usable[0]
    ou = item.get("overUnder")
    return (float(item["spread"]),
            float(ou) if isinstance(ou, (int, float)) else None,
            (item.get("details") or "").strip(),
            prov(item))


def patch_lines(matchups, events):
    """Fill spread/O-U fields on matchups whose lines ESPN has dropped."""
    patched, unmatched, nolines = 0, [], []
    for m in matchups:
        key = (m["away_team"], m["home_team"])
        ev = events.get(key)
        if not ev:
            unmatched.append(f"{m['away_team_short']} @ {m['home_team_short']}")
            continue
        m["event_id"] = ev["eid"]

        if m.get("spread_home") is not None:
            continue  # scoreboard still had it; leave it alone

        sh, ou, details, provider = fetch_closing_line(ev["eid"])
        if sh is None:
            nolines.append(f"{m['away_team_short']} @ {m['home_team_short']}")
            continue

        m["spread_home"] = sh
        m["spread_line"] = details or ""
        m["favored_team"] = details.rsplit(" ", 1)[0].strip() if details else ""
        m["spread_amount"] = abs(sh)
        m["over_under"] = f"{ou:g}" if ou is not None else ""
        m["odds_provider"] = provider
        patched += 1

    return patched, unmatched, nolines


# ── Grading ──────────────────────────────────────────────────────────

def grade(result, ev):
    """win / loss / push for the picked side against its own line."""
    sh = result["spread_home"]
    if result["pick_winner"] == result["home_team_short"]:
        margin, line = ev["home_score"] - ev["away_score"], sh
    else:
        margin, line = ev["away_score"] - ev["home_score"], -sh
    cover = margin + line
    if abs(cover) < 1e-9:
        return "push"
    return "win" if cover > 0 else "loss"


# ── Main ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="RoachFinder 3.0 — backfill a missed week")
    ap.add_argument("--week", type=int, required=True, help="NFL week to backfill")
    ap.add_argument("--season", type=int, default=CURRENT_SEASON_START_YEAR)
    ap.add_argument("--dry-run", action="store_true", help="print everything, write nothing")
    ap.add_argument("--force", action="store_true", help="overwrite an existing week in season_record.json")
    args = ap.parse_args()
    week, season = args.week, args.season

    record = load_season_record()
    if str(week) in record.get("weeks", {}) and not args.force and not args.dry_run:
        print(f"\n  Week {week} already has results in season_record.json. Use --force to overwrite.\n")
        return

    print(f"\n{'#'*62}")
    print(f"  Backfilling Week {week}, {season}")
    print(f"{'#'*62}")

    # 1. Scores and event ids
    events = fetch_week_events(week, season)
    unfinished = [k for k, v in events.items() if v["status"] != "STATUS_FINAL"]
    if unfinished:
        print(f"\n  ERROR: {len(unfinished)} Week {week} game(s) are not final yet.")
        print("  Backfill is only for weeks that have finished. Use run_week.py instead.\n")
        return
    print(f"\n  Found {len(events)} final games.")

    # 2. Matchups, then the lines ESPN dropped
    matchups = scrape_matchups(week, season)
    if not matchups:
        print("\n  ERROR: No matchups returned.\n")
        return

    print(f"\n  Restoring closing lines from the core odds endpoint...")
    patched, unmatched, nolines = patch_lines(matchups, events)
    print(f"    restored {patched} line(s)")
    if unmatched:
        print(f"\n  ERROR: no scoreboard match for: {', '.join(unmatched)}")
        print("  Team naming drifted between the two endpoints; cannot grade. Aborting.\n")
        return
    if nolines:
        print(f"\n  ERROR: no retained closing line for: {', '.join(nolines)}")
        print("  Cannot grade against the spread without a line. Aborting.\n")
        return
    for m in matchups:
        print(f"    {m['away_team_short']} @ {m['home_team_short']}  "
              f"{m['spread_line']}  (O/U {m['over_under'] or 'n/a'})  "
              f"[{m.get('odds_provider', 'scoreboard')}]")

    # 3. Reconstruct the picks (stats only from weeks before this one)
    results = run_predictions_v2(matchups, season, week)
    if not results:
        print("\n  ERROR: no predictions produced.\n")
        return

    # 4. Grade
    graded = []
    for r in results:
        ev = events[(r["away_team"], r["home_team"])]
        graded.append((r, ev, grade(r, ev)))

    print(f"\n{'='*62}")
    print(f"  Week {week} reconstructed picks, graded")
    print(f"{'='*62}")
    for r, ev, res in graded:
        print(f"    {res.upper():5}  {r['winning_pick_label']:22} "
              f"(CF {r['confidence_factor']:6.2f})  "
              f"final {r['away_team_short']} {ev['away_score']:.0f} - "
              f"{ev['home_score']:.0f} {r['home_team_short']}")

    w = sum(1 for _, _, x in graded if x == "win")
    l = sum(1 for _, _, x in graded if x == "loss")
    p = sum(1 for _, _, x in graded if x == "push")
    pct = f"  ({w / (w + l) * 100:.1f}%)" if (w + l) else ""
    print(f"\n  Week {week} ATS: {w}-{l}-{p}{pct}")

    if args.dry_run:
        print("\n  --dry-run: nothing written.\n")
        return

    # 5. Write current_week.json (+ an archive copy) and grade into season_record
    week_data = save_current_week(results, week)
    archive = data_path(f"week_{week:02d}_picks.json")
    with open(archive, "w") as f:
        json.dump(week_data, f, indent=2)
    print(f"  Archived a copy to {archive}")

    rolling = week_data.get("rolling_median_cf", 0)
    top5 = set(week_data.get("top_5_picks", []))

    week_games = []
    for r, ev, res in graded:
        label = r["winning_pick_label"]
        week_games.append({
            "pick": label,
            "confidence_factor": r["confidence_factor"],
            "result": res,
            "above_median": r["confidence_factor"] >= rolling,
            "top_5": label in top5,
            "away_team": r.get("away_team_short", ""),
            "home_team": r.get("home_team_short", ""),
        })

    record["weeks"][str(week)] = {"games": week_games, "backfilled": True}
    record["weeks"] = {k: record["weeks"][k] for k in sorted(record["weeks"], key=int)}
    recalculate_cumulative(record)

    all_cfs = [g["confidence_factor"]
               for wk in record["weeks"].values()
               for g in wk.get("games", [])
               if "confidence_factor" in g]
    record["rolling_median_cf"] = round(statistics.median(all_cfs), 3) if all_cfs else 0.0

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(data_path("season_record.json"), "w") as f:
        json.dump(record, f, indent=2)

    c = record["cumulative"]
    print(f"\n{'='*62}")
    print(f"  Week {week} written to season_record.json (tagged backfilled)")
    print(f"  Season Record (cumulative):")
    print(f"    All Spreads:   {c['all_spreads']['wins']}-{c['all_spreads']['losses']}-{c['all_spreads']['pushes']}  ({c['all_spreads']['win_pct']}%)")
    print(f"    Above Median:  {c['above_median']['wins']}-{c['above_median']['losses']}-{c['above_median']['pushes']}  ({c['above_median']['win_pct']}%)")
    print(f"    Top 5:         {c['top_5']['wins']}-{c['top_5']['losses']}-{c['top_5']['pushes']}  ({c['top_5']['win_pct']}%)")
    print(f"    Rolling median CF: {record['rolling_median_cf']}")
    print(f"{'='*62}")

    # 6. Excel + site copy
    try:
        from export_picks import export_week_to_excel
        export_week_to_excel()
    except PermissionError:
        print("\n  WARNING: picks workbook is open in Excel; skipped the Excel export.")
        print("  Close it and run:  python export_picks.py\n")

    os.makedirs(SITE_DATA_DIR, exist_ok=True)
    for filename in os.listdir(DATA_DIR):
        src = os.path.join(DATA_DIR, filename)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(SITE_DATA_DIR, filename))
    print(f"  Copied data/ → site/data/")

    print(f"\n  Next: set CURRENT_WEEK and run  python run_week.py  for the upcoming week.\n")


if __name__ == "__main__":
    main()
