"""
Fantasy Football Manager — Sleeper Supplementary Data

Sleeper's API is free and needs no auth/API key. It gives us two things
ESPN's API doesn't:
  1. Richer injury detail (practice participation, body part, notes)
  2. "Trending" adds/drops: how many Sleeper leagues added/dropped a
     player in the last 24h — a much faster buzz signal than ESPN's
     percent_owned, which updates slowly.

Sleeper player records include an `espn_id` field, so we cross-reference
by ESPN player ID (see `espn_player_id` in data/latest.json) rather than
fuzzy name matching.

Usage:
    python scripts/fetch_sleeper.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BASE_URL = "https://api.sleeper.app/v1"

# Fields worth keeping per player — the full Sleeper record has 50+ fields
# (odds/IDs for services we don't use), so trim to what we actually use.
KEEP_FIELDS = [
    "full_name", "position", "team", "status",
    "injury_status", "injury_body_part", "injury_notes", "practice_participation",
]


def fetch_players():
    resp = requests.get(f"{BASE_URL}/players/nfl", timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_trending(kind, lookback_hours=24, limit=25):
    resp = requests.get(
        f"{BASE_URL}/players/nfl/trending/{kind}",
        params={"lookback_hours": lookback_hours, "limit": limit},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def build_espn_crosswalk(players):
    """espn_player_id (int) -> trimmed Sleeper player record."""
    crosswalk = {}
    for sleeper_id, p in players.items():
        espn_id = p.get("espn_id")
        if not espn_id:
            continue
        record = {k: p.get(k) for k in KEEP_FIELDS}
        record["sleeper_id"] = sleeper_id
        crosswalk[str(espn_id)] = record
    return crosswalk


def resolve_trending(entries, players):
    resolved = []
    for e in entries:
        p = players.get(e["player_id"])
        if not p:
            continue  # team defenses etc. show up as non-numeric ids we can skip
        resolved.append({
            "name": p.get("full_name"),
            "position": p.get("position"),
            "team": p.get("team"),
            "espn_player_id": p.get("espn_id"),
            "count": e["count"],
        })
    return resolved


def main():
    print("Fetching Sleeper player database (~15MB, one-time-ish, cached after)...")
    players = fetch_players()
    print(f"Loaded {len(players)} Sleeper player records.")

    print("Fetching trending adds/drops (last 24h)...")
    trending_adds = resolve_trending(fetch_trending("add"), players)
    trending_drops = resolve_trending(fetch_trending("drop"), players)

    crosswalk = build_espn_crosswalk(players)
    print(f"Built ESPN-ID crosswalk for {len(crosswalk)} players.")

    output = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "crosswalk_by_espn_id": crosswalk,
        "trending_adds": trending_adds,
        "trending_drops": trending_drops,
    }

    out_path = DATA_DIR / "sleeper_data.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved: {out_path}")
    print(f"Top trending add: {trending_adds[0]['name']} ({trending_adds[0]['count']} adds)" if trending_adds else "No trending adds found.")


if __name__ == "__main__":
    main()
