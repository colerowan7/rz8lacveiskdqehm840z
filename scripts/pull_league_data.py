"""
Fantasy Football Manager — ESPN League Data Pull

Pulls your league, roster, opponent, and waiver-wire data from ESPN
and saves it as structured JSON for the analysis layer / dashboard to consume.

Setup:
    1. pip install espn-api python-dotenv
    2. Create a `.env` file in the project root with:
         LEAGUE_ID=1934807293
         YEAR=2026
         ESPN_S2=your_espn_s2_cookie_value
         SWID=your_swid_cookie_value
    3. Run: python scripts/pull_league_data.py
"""

import os
import json
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from espn_api.football import League

load_dotenv()

LEAGUE_ID = int(os.environ["LEAGUE_ID"])
YEAR = int(os.environ.get("YEAR", 2026))
ESPN_S2 = os.environ["ESPN_S2"]
SWID = os.environ["SWID"]

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def player_to_dict(player, is_free_agent=False):
    """Normalize an espn_api Player/BoxPlayer object into a plain dict.

    Free agents and box-score lineup players are BoxPlayer instances, which
    carry real per-week projections (`projected_points`) and matchup context
    (`pro_opponent`, `pro_pos_rank`) that the plain Player class (used by
    team.roster) doesn't have. Always prefer passing BoxPlayer objects in
    here for rostered players so start/sit math has real numbers to use.
    """
    return {
        "name": player.name,
        "espn_player_id": getattr(player, "playerId", None),
        "position": player.position,
        "pro_team": player.proTeam,
        "injury_status": getattr(player, "injuryStatus", None),
        "percent_owned": getattr(player, "percent_owned", None),
        "percent_started": getattr(player, "percent_started", None),
        "projected_points": getattr(player, "projected_points", None),
        "points": getattr(player, "points", None),
        "pro_opponent": getattr(player, "pro_opponent", None),
        "pro_pos_rank": getattr(player, "pro_pos_rank", None),
        "on_bye_week": getattr(player, "on_bye_week", False),
        "game_date": str(getattr(player, "game_date", "")) or None,
        "lineup_slot": getattr(player, "slot_position", None)
        or (getattr(player, "lineupSlot", None) if not is_free_agent else None),
    }


# A pending trade sits in this set of non-terminal statuses until the other
# team (or the league's veto window) resolves it. ESPN's exact status
# strings for trades aren't documented, so this list is best-effort —
# deliberately treating any *unrecognized* status as "still pending" (shown
# to the user) rather than silently dropping it, since missing a real trade
# offer is worse than showing one that turns out to already be resolved.
TERMINAL_TRADE_STATUSES = {"EXECUTED", "DECLINED", "VETOED", "EXPIRED", "CANCELLED", "FAILED"}


def build_league_player_lookup(league, week):
    """Every player in every team's starting lineup or bench this week,
    keyed by ESPN player ID, as BoxPlayer objects (real weekly projections,
    matchup difficulty, etc.) — not just the two teams in your own matchup."""
    lookup = {}
    for matchup in league.box_scores(week=week):
        for lineup in (matchup.home_lineup, matchup.away_lineup):
            for p in lineup:
                lookup[p.playerId] = p
    return lookup


def fetch_pending_trades(league, my_team_id, player_lookup):
    """Trade proposals involving my team that haven't been resolved yet.
    Uses the raw mTransactions2 view — espn_api's own recent_activity()
    only surfaces already-EXECUTED transactions, not pending offers."""
    data = league.espn_request.league_get(params={"view": "mTransactions2"})
    team_name_by_id = {t.team_id: t.team_name for t in league.teams}

    trades = []
    for txn in data.get("transactions", []):
        if txn.get("type") != "TRADE" or txn.get("status") in TERMINAL_TRADE_STATUSES:
            continue
        items = [i for i in txn.get("items", []) if i.get("type") == "TRADE"]
        team_ids_involved = {i["fromTeamId"] for i in items} | {i["toTeamId"] for i in items}
        if my_team_id not in team_ids_involved:
            continue

        give, get = [], []
        for item in items:
            player = player_lookup.get(item["playerId"])
            if player is None:
                # Not in anyone's lineup this week (e.g. a bye) — fall back
                # to season-level info so the trade still shows something.
                fallback = league.player_info(playerId=item["playerId"])
                player_dict = player_to_dict(fallback) if fallback else {
                    "name": f"Player #{item['playerId']}", "espn_player_id": item["playerId"],
                }
            else:
                player_dict = player_to_dict(player)
            (give if item["fromTeamId"] == my_team_id else get).append(player_dict)

        other_team_id = next((tid for tid in team_ids_involved if tid != my_team_id), None)
        trades.append({
            "transaction_id": txn.get("id"),
            "status": txn.get("status"),
            "proposed_by": team_name_by_id.get(txn.get("teamId"), "Unknown"),
            "other_team": team_name_by_id.get(other_team_id, "Unknown"),
            "proposed_date": txn.get("proposedDate"),
            "give": give,
            "get": get,
        })
    return trades


def team_to_dict(team, lineup=None):
    """lineup: optional list of BoxPlayer objects (from box_scores) with
    real weekly projections. Falls back to team.roster (season-total only,
    no weekly projections) if not provided."""
    return {
        "team_name": team.team_name,
        "owner": team.owners[0]["firstName"] + " " + team.owners[0]["lastName"]
        if getattr(team, "owners", None)
        else None,
        "wins": team.wins,
        "losses": team.losses,
        "points_for": team.points_for,
        "points_against": team.points_against,
        "standing": team.standing,
        "roster": [player_to_dict(p) for p in (lineup if lineup is not None else team.roster)],
    }


def main():
    print(f"Connecting to league {LEAGUE_ID} ({YEAR})...")
    league = League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)

    current_week = league.current_week
    print(f"Connected. Current week: {current_week}")

    # Find "my" team — will prompt once so we know which team is yours
    my_team = None
    print("\nTeams in this league:")
    for i, team in enumerate(league.teams):
        print(f"  [{i}] {team.team_name}")

    my_team_index_env = os.environ.get("MY_TEAM_INDEX")
    if my_team_index_env is not None:
        my_team = league.teams[int(my_team_index_env)]
    else:
        print("\nSet MY_TEAM_INDEX in your .env to skip this prompt next time.")
        idx = input("Which number is your team? ")
        my_team = league.teams[int(idx)]

    # Find this week's opponent + real per-week lineups (with projections)
    # for both teams. team.roster only has season-total stats, not weekly
    # projections, so we pull lineups from the box score instead. Also
    # build a league-wide player lookup from the same box scores so trade
    # proposals involving ANY team's players can be evaluated with real
    # weekly projections, not just my own roster and opponent's.
    all_box_scores = league.box_scores(week=current_week)
    player_lookup = {}
    my_matchup = None
    my_lineup = None
    opponent_lineup = None
    for matchup in all_box_scores:
        for lineup in (matchup.home_lineup, matchup.away_lineup):
            for p in lineup:
                player_lookup[p.playerId] = p
        if matchup.home_team == my_team:
            my_lineup = matchup.home_lineup
            opponent_lineup = matchup.away_lineup
            my_matchup = matchup.away_team
        elif matchup.away_team == my_team:
            my_lineup = matchup.away_lineup
            opponent_lineup = matchup.home_lineup
            my_matchup = matchup.home_team

    pending_trades = fetch_pending_trades(league, my_team.team_id, player_lookup)

    # Free agents / waiver wire — top available by position
    free_agents = []
    for pos in ["QB", "RB", "WR", "TE", "D/ST", "K"]:
        fas = league.free_agents(position=pos, size=15)
        free_agents.extend([player_to_dict(p, is_free_agent=True) for p in fas])

    # Recent activity / transactions (trades, waiver adds/drops)
    try:
        recent_activity = league.recent_activity(size=25)
        activity_log = [str(a) for a in recent_activity]
    except Exception as e:
        activity_log = [f"Could not fetch activity: {e}"]

    output = {
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "league_id": LEAGUE_ID,
        "year": YEAR,
        "current_week": current_week,
        "roster_rules": {
            "bench_slots": league.settings.position_slot_counts.get("BE", 0),
            "ir_slots": league.settings.position_slot_counts.get("IR", 0),
        },
        "my_team": team_to_dict(my_team, lineup=my_lineup),
        "opponent_team": team_to_dict(my_matchup, lineup=opponent_lineup) if my_matchup else None,
        "standings": [
            {
                "team_name": t.team_name,
                "wins": t.wins,
                "losses": t.losses,
                "points_for": t.points_for,
                "standing": t.standing,
            }
            for t in sorted(league.teams, key=lambda t: t.standing)
        ],
        "free_agents": free_agents,
        "recent_activity": activity_log,
        "pending_trades": pending_trades,
    }

    out_path = DATA_DIR / f"league_data_week{current_week}.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    latest_path = DATA_DIR / "latest.json"
    with open(latest_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved: {out_path}")
    print(f"Saved: {latest_path}")
    print(f"\nYour team: {my_team.team_name} ({my_team.wins}-{my_team.losses})")
    if my_matchup:
        print(f"This week's opponent: {my_matchup.team_name} ({my_matchup.wins}-{my_matchup.losses})")
    if pending_trades:
        print(f"\n{len(pending_trades)} pending trade(s) awaiting a decision - see the dashboard or run analyze.py.")


if __name__ == "__main__":
    main()
