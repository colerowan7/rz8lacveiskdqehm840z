"""
Fantasy Football Manager — Weekly Analysis Layer

Reads data/latest.json (produced by pull_league_data.py) and generates a
recommendation report: start/sit swaps, injury/bye alerts, waiver-wire
upgrades, and a projected matchup score.

If data/sleeper_data.json and/or data/nflverse_trends.json exist (see
fetch_sleeper.py / fetch_nflverse.py), their data enriches the report:
richer injury detail + waiver "trending add" buzz from Sleeper, and
real recent-usage numbers from nflverse to sanity-check ESPN's
projections. Both are optional — the report still works without them.

Usage:
    python scripts/analyze.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from name_match import player_key

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

BENCH_SLOTS = {"BE", "IR"}
BAD_INJURY_STATUSES = {"OUT", "DOUBTFUL", "INJURY_RESERVE"}
WARN_INJURY_STATUSES = {"QUESTIONABLE"}

# Which positions can fill each starting lineup slot.
FLEX_ELIGIBILITY = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "D/ST": {"D/ST"},
    "K": {"K"},
    "RB/WR": {"RB", "WR"},
    "WR/TE": {"WR", "TE"},
    "RB/WR/TE": {"RB", "WR", "TE"},
    "OP": {"QB", "RB", "WR", "TE"},
}

CORE_POSITIONS = ["QB", "RB", "WR", "TE", "D/ST", "K"]

SWAP_MARGIN = 0.5  # min projected-point gain to bother recommending a swap

# ESPN's own "injured reserve" designation — a bench player with this status
# is (almost always) eligible to move to a league's IR slot, which doesn't
# count against the bench limit. Other statuses (OUT, QUESTIONABLE, etc.)
# don't reliably qualify, so we only flag this one.
IR_ELIGIBLE_STATUS = "INJURY_RESERVE"


def load_data():
    path = DATA_DIR / "latest.json"
    if not path.exists():
        raise SystemExit(
            "No data/latest.json found. Run `python scripts/pull_league_data.py` first."
        )
    return json.loads(path.read_text())


def load_optional(filename):
    path = DATA_DIR / filename
    if not path.exists():
        return None
    return json.loads(path.read_text())


def proj(player):
    return player.get("projected_points") or 0


def is_unavailable(player):
    return (
        player.get("injury_status") in BAD_INJURY_STATUSES
        or player.get("on_bye_week")
    )


def sleeper_record(player, sleeper):
    """Look up a player's Sleeper record by ESPN player ID crosswalk."""
    if not sleeper or not player.get("espn_player_id"):
        return None
    return sleeper["crosswalk_by_espn_id"].get(str(player["espn_player_id"]))


def nflverse_record(player, nflverse):
    """nflverse's fantasy_points_ppr column only covers QB/RB/WR/TE — it's
    always 0 for kickers, which would read as a real (and misleading) stat
    line, so treat that as "no data" rather than "scored zero"."""
    if not nflverse:
        return None
    record = nflverse["players"].get(player_key(player["name"], player["position"]))
    if record and record["avg_fantasy_points_ppr"] == 0:
        return None
    return record


def injury_flags(roster, sleeper=None):
    """Starters who are OUT/DOUBTFUL/IR/on bye, or QUESTIONABLE — need a look before lineups lock."""
    flags = []
    for p in roster:
        if p["lineup_slot"] in BENCH_SLOTS:
            continue
        status = p.get("injury_status")
        detail = None
        sr = sleeper_record(p, sleeper)
        if sr:
            detail = sr.get("injury_notes") or sr.get("practice_participation") or sr.get("injury_body_part")
        if p.get("on_bye_week"):
            flags.append({"player": p["name"], "slot": p["lineup_slot"], "reason": "BYE_WEEK", "detail": None})
        elif status in BAD_INJURY_STATUSES or status in WARN_INJURY_STATUSES:
            flags.append({"player": p["name"], "slot": p["lineup_slot"], "reason": status, "detail": detail})
    return flags


def start_sit_recommendations(roster):
    """Suggest bench -> starter swaps where the bench player is a clear
    upgrade (higher projection, or the starter is unavailable)."""
    starters = [p for p in roster if p["lineup_slot"] not in BENCH_SLOTS]
    bench = [p for p in roster if p["lineup_slot"] == "BE"]
    used_bench_names = set()

    recommendations = []
    # Look at the weakest starters first so the best bench upgrade goes to
    # the slot that needs it most.
    for starter in sorted(starters, key=proj):
        slot = starter["lineup_slot"]
        eligible_positions = FLEX_ELIGIBILITY.get(slot, {starter["position"]})
        candidates = [
            b for b in bench
            if b["name"] not in used_bench_names and b["position"] in eligible_positions
        ]
        if not candidates:
            continue
        best = max(candidates, key=proj)
        gain = proj(best) - proj(starter)
        if is_unavailable(starter) or gain >= SWAP_MARGIN:
            reason = (
                f"{starter['name']} is {'on bye' if starter.get('on_bye_week') else starter.get('injury_status')}"
                if is_unavailable(starter)
                else f"+{gain:.1f} projected pts"
            )
            recommendations.append({
                "slot": slot,
                "sit": starter["name"],
                "sit_projected": proj(starter),
                "start": best["name"],
                "start_projected": proj(best),
                "reason": reason,
            })
            used_bench_names.add(best["name"])
    return recommendations


def weakest_eligible_starter(roster, position):
    """The starter a free agent at `position` would actually have to beat
    to crack the starting lineup this week (accounts for FLEX/OP slots).
    None means nothing at that position is starting at all."""
    candidates = [
        p for p in roster
        if p["lineup_slot"] not in BENCH_SLOTS
        and position in FLEX_ELIGIBILITY.get(p["lineup_slot"], {p["position"]})
    ]
    return min(candidates, key=proj, default=None)


def waiver_targets(free_agents, roster, nflverse=None, capacity=None, top_n=3):
    """For each position, compare available free agents against your
    weakest rostered player at that position (starter or bench) — this is
    a value comparison, NOT a forced 1-for-1 drop. Whether you'd actually
    need to drop anyone depends on open bench spots (see `capacity`)."""
    by_position = {}
    for p in roster:
        if p["lineup_slot"] == "IR":
            continue
        by_position.setdefault(p["position"], []).append(p)

    targets = {}
    for pos in CORE_POSITIONS:
        mine = by_position.get(pos, [])
        weakest = min(mine, key=proj, default=None)
        baseline = proj(weakest) if weakest else 0
        weakest_starter = weakest_eligible_starter(roster, pos)
        fa_pool = [f for f in free_agents if f["position"] == pos]
        upgrades = sorted(
            (f for f in fa_pool if proj(f) > baseline),
            key=proj,
            reverse=True,
        )[:top_n]
        if upgrades:
            entries = []
            for f in upgrades:
                nv = nflverse_record(f, nflverse)
                gain = round(proj(f) - baseline, 1)
                would_start = weakest_starter is None or proj(f) > proj(weakest_starter)
                entries.append({
                    "name": f["name"],
                    "pro_team": f["pro_team"],
                    "projected_points": proj(f),
                    "percent_owned": f.get("percent_owned"),
                    "beats_your_weakest_by": gain,
                    "weakest_player": weakest["name"] if weakest else None,
                    "would_start_this_week": would_start,
                    "reason": waiver_reason(f, pos, weakest, gain, nv, capacity, weakest_starter, would_start),
                    "recent_form": {
                        "avg_fantasy_points_ppr": nv["avg_fantasy_points_ppr"],
                        "games_sample": nv["games_sample"],
                    } if nv else None,
                })
            targets[pos] = entries
    return targets


def waiver_reason(free_agent, position, weakest, gain, nflverse_record_, capacity=None,
                   weakest_starter=None, would_start=None):
    """Plain-English explanation for why this free agent is worth a look.
    Explicitly value-only for the roster-spot comparison (does not claim
    you'd have to drop `weakest`) — but separately calls out whether
    they'd actually start this week, since a roster add that stays on
    the bench scores you nothing."""
    if weakest:
        sentence = (
            f"Projected for {proj(free_agent):.1f} pts this week - "
            f"{gain:+.1f} more than your weakest rostered {position}, "
            f"{weakest['name']} ({proj(weakest):.1f} proj)."
        )
    else:
        sentence = f"You don't currently roster a {position} - projected for {proj(free_agent):.1f} pts this week."
    if nflverse_record_:
        sentence += (
            f" Actually averaged {nflverse_record_['avg_fantasy_points_ppr']:.1f} ppg "
            f"over their last {nflverse_record_['games_sample']} games, for context."
        )
    if capacity and capacity["bench_open"] > 0:
        sentence += f" You have {capacity['bench_open']} open bench spot(s), so you wouldn't need to drop anyone."

    if weakest_starter is not None:
        # weakest_starter's own position may differ from `position` (e.g. a
        # TE occupying the RB/WR/TE flex slot) — label it by what it
        # actually is, not by the position we're evaluating against it.
        starter_label = (
            f"your starting {position} {weakest_starter['name']}"
            if weakest_starter["position"] == position
            else f"{weakest_starter['name']} ({weakest_starter['position']}), currently in your {weakest_starter['lineup_slot']} flex spot"
        )
        if would_start:
            sentence += (
                f" This would actually start over {starter_label} "
                f"({proj(weakest_starter):.1f} proj) - real points, not just bench depth."
            )
        else:
            sentence += (
                f" Note: that's still below {starter_label} "
                f"({proj(weakest_starter):.1f} proj), so they'd sit on your bench scoring nothing "
                f"unless something changes - this is a depth add / stash, not an immediate lineup upgrade."
            )
    return sentence


def trending_on_waivers(free_agents, sleeper, top_n=8):
    """Free agents that Sleeper users are actively adding right now —
    a faster buzz signal than ESPN's slow-moving percent_owned."""
    if not sleeper or not sleeper.get("trending_adds"):
        return []
    trending_by_espn_id = {
        str(t["espn_player_id"]): t["count"]
        for t in sleeper["trending_adds"]
        if t.get("espn_player_id")
    }
    hits = []
    for f in free_agents:
        count = trending_by_espn_id.get(str(f.get("espn_player_id")))
        if count:
            hits.append({
                "name": f["name"],
                "position": f["position"],
                "pro_team": f["pro_team"],
                "projected_points": proj(f),
                "sleeper_adds_24h": count,
            })
    return sorted(hits, key=lambda h: h["sleeper_adds_24h"], reverse=True)[:top_n]


def roster_capacity(roster, roster_rules):
    """How much room is actually on the bench/IR right now. This matters
    for waiver suggestions: 'this free agent beats your weakest RB' does
    NOT mean you're forced to drop that RB — if you have an open bench
    spot, you can add without dropping anyone at all."""
    bench_slots = roster_rules.get("bench_slots", 0)
    ir_slots = roster_rules.get("ir_slots", 0)
    bench_filled = sum(1 for p in roster if p["lineup_slot"] == "BE")
    ir_filled = sum(1 for p in roster if p["lineup_slot"] == "IR")
    ir_eligible_on_bench = [
        p["name"] for p in roster
        if p["lineup_slot"] == "BE" and p.get("injury_status") == IR_ELIGIBLE_STATUS
    ]
    return {
        "bench_slots": bench_slots,
        "bench_filled": bench_filled,
        "bench_open": bench_slots - bench_filled,
        "ir_slots": ir_slots,
        "ir_filled": ir_filled,
        "ir_open": ir_slots - ir_filled,
        "ir_eligible_on_bench": ir_eligible_on_bench,
    }


def matchup_projection(my_roster, opponent_roster):
    my_starters = [p for p in my_roster if p["lineup_slot"] not in BENCH_SLOTS]
    my_total = sum(proj(p) for p in my_starters)

    if not opponent_roster:
        return {"my_projected": round(my_total, 1), "opponent_projected": None, "margin": None}

    opp_starters = [p for p in opponent_roster if p["lineup_slot"] not in BENCH_SLOTS]
    opp_total = sum(proj(p) for p in opp_starters)
    return {
        "my_projected": round(my_total, 1),
        "opponent_projected": round(opp_total, 1),
        "margin": round(my_total - opp_total, 1),
    }


def build_top_actions(injury_flags_, start_sit_, waiver_targets_, trending_adds_, max_items=6):
    """Rank every recommendation across categories into one prioritized
    feed, so the highest-impact thing to do this week surfaces first
    instead of being buried in whichever card happens to be scrolled to."""
    actions = []
    URGENT_STATUSES = {"OUT", "DOUBTFUL", "INJURY_RESERVE", "BYE_WEEK"}

    # ref_id lets a later, optional pass (ai_insights.py) attach an AI
    # verdict back onto the exact report entry this action came from.
    for i, r in enumerate(start_sit_):
        urgent = any(s in r["reason"] for s in URGENT_STATUSES)
        actions.append({
            "category": "start_sit",
            "urgent": urgent,
            "impact": abs(round(r["start_projected"] - r["sit_projected"], 1)),
            "headline": f"Start {r['start']} over {r['sit']}",
            "detail": r["reason"],
            "ref_id": f"swap_{i}",
        })

    already_actioned = {r["sit"] for r in start_sit_}
    for i, f in enumerate(injury_flags_):
        if f["player"] in already_actioned:
            continue  # a swap above already covers this player
        actions.append({
            "category": "injury_watch",
            "urgent": f["reason"] in URGENT_STATUSES,
            "impact": 3,
            "headline": f"{f['player']} ({f['slot']}): {f['reason']}",
            "detail": f["detail"] or "No clear bench replacement was found - worth checking before kickoff.",
            "ref_id": f"injury_{i}",
        })

    for pos, players in waiver_targets_.items():
        starters_only = [p for p in players if p["would_start_this_week"]]
        if starters_only:
            best = starters_only[0]
            actions.append({
                "category": "waiver",
                "urgent": False,
                "impact": best["beats_your_weakest_by"],
                "headline": f"Add {best['name']} ({pos}) - would start immediately",
                "detail": best["reason"],
                "ref_id": f"waiver_{pos}_{players.index(best)}",
            })

    if trending_adds_:
        t = trending_adds_[0]
        actions.append({
            "category": "trending",
            "urgent": False,
            "impact": 0.5,
            "headline": f"{t['name']} ({t['position']}) is trending on Sleeper",
            "detail": f"{t['sleeper_adds_24h']:,} adds in the last 24h - possibly worth a speculative add.",
            "ref_id": None,
        })

    actions.sort(key=lambda a: (a["urgent"], a["impact"]), reverse=True)
    return actions[:max_items]


def build_report(data, sleeper=None, nflverse=None):
    my_roster = data["my_team"]["roster"]
    opponent = data.get("opponent_team")
    opponent_roster = opponent["roster"] if opponent else []
    capacity = roster_capacity(my_roster, data.get("roster_rules", {}))

    injury_flags_ = injury_flags(my_roster, sleeper)
    start_sit_ = start_sit_recommendations(my_roster)
    waiver_targets_ = waiver_targets(data["free_agents"], my_roster, nflverse, capacity)
    trending_adds_ = trending_on_waivers(data["free_agents"], sleeper)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "week": data["current_week"],
        "my_team": data["my_team"]["team_name"],
        "opponent_team": opponent["team_name"] if opponent else None,
        "sources": {
            "sleeper": sleeper is not None,
            "nflverse": nflverse["mode"] if nflverse else None,
        },
        "roster_capacity": capacity,
        "matchup_projection": matchup_projection(my_roster, opponent_roster),
        "top_actions": build_top_actions(injury_flags_, start_sit_, waiver_targets_, trending_adds_),
        "injury_flags": injury_flags_,
        "start_sit": start_sit_,
        "waiver_targets": waiver_targets_,
        "trending_adds": trending_adds_,
    }


def print_report(report):
    print(f"\n=== Week {report['week']} Report: {report['my_team']} ===\n")

    mp = report["matchup_projection"]
    if mp["opponent_projected"] is not None:
        lean = "favored" if mp["margin"] > 0 else "underdog" if mp["margin"] < 0 else "even"
        print(
            f"Projected matchup vs {report['opponent_team']}: "
            f"{mp['my_projected']} - {mp['opponent_projected']} ({lean}, {mp['margin']:+.1f})\n"
        )
    else:
        print(f"Projected starters total: {mp['my_projected']} pts (no opponent found)\n")

    cap = report["roster_capacity"]
    print(f"Roster: bench {cap['bench_filled']}/{cap['bench_slots']} full, IR {cap['ir_filled']}/{cap['ir_slots']} used.")
    if cap["bench_open"] > 0:
        print(f"  -> You have {cap['bench_open']} open bench spot(s) - you can add a waiver player without dropping anyone.")
    elif cap["ir_eligible_on_bench"]:
        names = ", ".join(cap["ir_eligible_on_bench"])
        print(f"  -> Bench is full, but {names} on your bench qualifies for IR - moving them there would free a bench spot without a real drop.")
    else:
        print("  -> Bench is full - adding a waiver player means dropping someone.")
    print()

    if report["top_actions"]:
        print("TOP ACTIONS THIS WEEK:")
        for i, a in enumerate(report["top_actions"], 1):
            flag = " [URGENT]" if a["urgent"] else ""
            print(f"  {i}. {a['headline']}{flag}")
            print(f"     {a['detail']}")
        print()

    if report["injury_flags"]:
        print("Injury / bye alerts (starters):")
        for f in report["injury_flags"]:
            detail = f" ({f['detail']})" if f.get("detail") else ""
            print(f"  - [{f['slot']}] {f['player']}: {f['reason']}{detail}")
        print()
    else:
        print("No injury/bye concerns among your starters.\n")

    if report["start_sit"]:
        print("Suggested start/sit swaps:")
        for r in report["start_sit"]:
            print(
                f"  - [{r['slot']}] START {r['start']} ({r['start_projected']}) "
                f"over {r['sit']} ({r['sit_projected']}) - {r['reason']}"
            )
        print()
    else:
        print("No start/sit swaps recommended - your lineup looks optimal.\n")

    if report["waiver_targets"]:
        print("Waiver wire upgrades available:")
        for pos, players in report["waiver_targets"].items():
            print(f"  {pos}:")
            for p in players:
                owned = f" ({p['percent_owned']:.0f}% owned)" if p.get("percent_owned") is not None else ""
                print(f"    - {p['name']}{owned}")
                print(f"        {p['reason']}")
        print()
    else:
        print("No clear waiver-wire upgrades found for your starting positions.\n")

    if report["trending_adds"]:
        print("Trending adds on Sleeper (last 24h, not necessarily an upgrade - just buzz):")
        for t in report["trending_adds"]:
            print(f"  - {t['name']} ({t['position']}, {t['pro_team']}): {t['sleeper_adds_24h']:,} adds")
        print()

    sources = report["sources"]
    active = ["ESPN"]
    if sources["sleeper"]:
        active.append("Sleeper")
    if sources["nflverse"]:
        active.append(f"nflverse ({sources['nflverse']})")
    print(f"Data sources used: {', '.join(active)}")


def main():
    data = load_data()
    sleeper = load_optional("sleeper_data.json")
    nflverse = load_optional("nflverse_trends.json")
    if not sleeper:
        print("(No data/sleeper_data.json - run `python scripts/fetch_sleeper.py` for richer injury info + waiver buzz.)")
    if not nflverse:
        print("(No data/nflverse_trends.json - run `python scripts/fetch_nflverse.py` for real usage stats on waiver targets.)")

    report = build_report(data, sleeper, nflverse)
    print_report(report)

    out_path = DATA_DIR / f"report_week{report['week']}.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    latest_path = DATA_DIR / "report_latest.json"
    with open(latest_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Saved: {out_path}")
    print(f"Saved: {latest_path}")


if __name__ == "__main__":
    main()
