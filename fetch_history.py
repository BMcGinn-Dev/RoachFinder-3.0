"""
One-time download of past seasons for Escanor v2 (backtest + early-season blend).

    python fetch_history.py              # 2023, 2024, 2025
    python fetch_history.py 2025         # just one season

Saves data/history/games_<season>.json. Takes a few minutes per season the
first time; after that it's instant (cached).
"""
import sys

from espn_data import load_season_games

seasons = [int(a) for a in sys.argv[1:]] or [2023, 2024, 2025]
for season in seasons:
    games = load_season_games(season)
    final = [g for g in games if g["status"] == "STATUS_FINAL"]
    with_box = [g for g in final if len(g["box"]) >= 2]
    with_line = [g for g in final if g["spread_home"] is not None]
    print(f"  {season}: {len(final)} final games, {len(with_box)} with box scores, "
          f"{len(with_line)} with closing lines")
