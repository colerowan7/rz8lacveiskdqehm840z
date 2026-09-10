"""
Fantasy Football Manager — nflverse Supplementary Data

nflverse (https://github.com/nflverse/nflverse-data) publishes free,
public weekly player stats as plain CSV releases on GitHub — real usage
numbers (targets, carries, target share, snap-adjacent metrics) rather
than a single projection number. We use it to sanity-check ESPN's
projections against actual recent role/production.

Early in a season there's no current-year data yet (games haven't been
played), so this falls back to full prior-season per-game averages —
still a useful "what was this player's role last year" signal. Once the
current season has games in the books, it switches to a trailing
3-week recent-form window automatically.

nflverse has no direct ESPN-ID crosswalk, so players are matched by
normalized name + position (see name_match.py) in analyze.py.

Usage:
    python scripts/fetch_nflverse.py
"""

import csv
import io
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from name_match import normalize_name

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RELEASE_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{year}.csv"

TRAILING_WEEKS = 3

# Counting stats we track per position group; everything else in the 150
# column nflverse file is defense/kicking detail we don't need here.
TRACKED_FIELDS = [
    "fantasy_points_ppr", "targets", "receptions", "target_share",
    "carries", "passing_yards", "passing_tds", "rushing_yards",
    "rushing_tds", "receiving_yards", "receiving_tds",
]


def fetch_week_csv(year):
    url = RELEASE_URL.format(year=year)
    resp = requests.get(url, timeout=60)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.text


def parse_rows(csv_text):
    return list(csv.DictReader(io.StringIO(csv_text)))


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def aggregate(rows):
    """Sum tracked fields per (normalized_name, position), track games played."""
    sums = defaultdict(lambda: defaultdict(float))
    games = defaultdict(int)
    display_name = {}

    for row in rows:
        if row.get("season_type") != "REG":
            continue
        key = (normalize_name(row["player_display_name"]), row["position"])
        display_name[key] = row["player_display_name"]
        games[key] += 1
        for field in TRACKED_FIELDS:
            sums[key][field] += to_float(row.get(field))

    players = {}
    for key, g in games.items():
        name, position = key
        avgs = {f"avg_{f}": round(sums[key][f] / g, 2) for f in TRACKED_FIELDS}
        players[f"{name}|{position}"] = {
            "display_name": display_name[key],
            "position": position,
            "games_sample": g,
            **avgs,
        }
    return players


def main():
    year = int(os.environ.get("YEAR", datetime.now().year))
    current_week = None
    latest_path = DATA_DIR / "latest.json"
    if latest_path.exists():
        current_week = json.loads(latest_path.read_text()).get("current_week")

    print(f"Looking for nflverse weekly stats for {year}...")
    csv_text = fetch_week_csv(year)
    mode = None
    season_used = year
    weeks_included = None

    if csv_text:
        rows = parse_rows(csv_text)
        if current_week:
            rows = [r for r in rows if r.get("season_type") != "REG" or int(r["week"]) < current_week]
        if rows:
            weeks = sorted({int(r["week"]) for r in rows if r.get("season_type") == "REG"})
            weeks_included = weeks[-TRAILING_WEEKS:]
            rows = [r for r in rows if r.get("season_type") == "REG" and int(r["week"]) in weeks_included]
            mode = "recent_form"
        else:
            csv_text = None  # current year file exists but has no playable rows yet

    if not csv_text or mode is None:
        season_used = year - 1
        print(f"No current-season games yet - falling back to {season_used} full-season averages...")
        csv_text = fetch_week_csv(season_used)
        if not csv_text:
            raise SystemExit(f"Could not fetch nflverse data for {year} or {season_used}.")
        rows = parse_rows(csv_text)
        mode = "last_season_avg"

    print(f"Aggregating {len(rows)} rows ({mode}, season {season_used})...")
    players = aggregate(rows)

    output = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "season_used": season_used,
        "mode": mode,
        "weeks_included": weeks_included,
        "players": players,
    }

    out_path = DATA_DIR / "nflverse_trends.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Saved: {out_path} ({len(players)} players, mode={mode})")


if __name__ == "__main__":
    main()
