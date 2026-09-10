"""
Fantasy Football Manager — AI Judgment Layer (optional)

Everything in analyze.py is pure arithmetic: compare projected points,
check roster rules, done. That's reliable for the obvious calls, but a
spreadsheet can't weigh the things that actually decide close ones — how
much stock to put in a QUESTIONABLE tag, whether a brutal or cushy matchup
(pro_pos_rank, pulled from ESPN but never otherwise used) should tip a
near-even start/sit, or whether real recent production (nflverse) should
outweigh a stale-looking projection.

This script finds the genuinely CLOSE calls in this week's report — small
point margins, ambiguous injury status — and sends just those to Claude
for real judgment, then writes the verdicts back onto
data/report_latest.json. It's additive and optional: run
`python scripts/analyze.py` alone and you get a complete, useful report
with no API key required. This step only sharpens the calls that were
already ambiguous.

Requires ANTHROPIC_API_KEY in your .env (get one at console.anthropic.com
— this makes real, billed API calls, a handful of cents per run).

Usage:
    python scripts/ai_insights.py
"""

import json
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from analyze import proj
from name_match import player_key

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MODEL = "claude-opus-5"

# Below this point-margin, treat a call as genuinely ambiguous and worth
# real judgment. Above it, the arithmetic is already obviously correct —
# asking an LLM to confirm "12 beats 3" wastes a call and adds no value.
CLOSE_MARGIN = 3.0

SCHEMA = {
    "type": "object",
    "properties": {
        "judgment_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "agree_with_default": {"type": "boolean"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "verdict": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                "required": ["id", "agree_with_default", "confidence", "verdict", "reasoning"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["judgment_calls"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are a sharp, experienced fantasy football analyst helping a beginner "
    "make close lineup and waiver decisions. You'll be given several 'close calls' "
    "- situations where simple point-projection math is ambiguous (small margins, "
    "questionable injury tags). For EACH one, decide whether to agree with the "
    "default/suggested action stated in its context, citing the specific matchup "
    "difficulty, injury detail, or recent-production number that drove your call. "
    "Keep reasoning to 1-2 plain-English sentences a beginner can follow, no jargon. "
    "Be decisive - pick a side even when it's close, and say so honestly when you "
    "genuinely have no edge over the raw numbers (that's still a valid, "
    "low-confidence answer). Never hedge with 'it depends' as your entire answer."
)


def find_by_name(players, name):
    return next((p for p in players if p["name"] == name), None)


def sleeper_note(p, sleeper):
    if not sleeper or not p or not p.get("espn_player_id"):
        return None
    rec = sleeper["crosswalk_by_espn_id"].get(str(p["espn_player_id"]))
    if not rec:
        return None
    return rec.get("injury_notes") or rec.get("practice_participation") or rec.get("injury_body_part")


def nflverse_note(p, nflverse):
    if not nflverse or not p:
        return None
    rec = nflverse["players"].get(player_key(p["name"], p["position"]))
    if not rec or rec["avg_fantasy_points_ppr"] == 0:
        return None
    return (
        f"Actually averaged {rec['avg_fantasy_points_ppr']:.1f} ppg over their last "
        f"{rec['games_sample']} games ({nflverse['mode']}, {nflverse['season_used']} data)."
    )


def player_block(p, label, sleeper, nflverse):
    if not p:
        return f"{label}: (no data found)"
    lines = [f"{label}: {p['name']} ({p['position']}, {p.get('pro_team')})",
             f"  Projected points this week: {proj(p):.1f}"]
    if p.get("injury_status") and p["injury_status"] != "ACTIVE":
        lines.append(f"  Injury status: {p['injury_status']}")
    note = sleeper_note(p, sleeper)
    if note:
        lines.append(f"  Injury note: {note}")
    if p.get("pro_opponent"):
        lines.append(f"  This week's opponent: {p['pro_opponent']}")
    rank = p.get("pro_pos_rank")
    if rank:
        lines.append(f"  Opponent's rank vs {p['position']}: {rank} (lower number = tougher matchup for this player)")
    form = nflverse_note(p, nflverse)
    if form:
        lines.append(f"  {form}")
    return "\n".join(lines)


def build_close_calls(data, report, sleeper, nflverse):
    roster = data["my_team"]["roster"]
    free_agents = data["free_agents"]
    calls = []

    for i, r in enumerate(report["start_sit"]):
        margin = abs(r["start_projected"] - r["sit_projected"])
        if margin >= CLOSE_MARGIN:
            continue
        start_p = find_by_name(roster, r["start"])
        sit_p = find_by_name(roster, r["sit"])
        context = "\n".join([
            f"Lineup slot: {r['slot']}",
            f"The point-projection formula suggests: START {r['start']} over {r['sit']} "
            f"(margin: {margin:.1f} pts). Reason given: {r['reason']}",
            player_block(start_p, "Proposed starter", sleeper, nflverse),
            player_block(sit_p, "Current starter", sleeper, nflverse),
        ])
        calls.append({"id": f"swap_{i}", "category": "start_sit", "context": context})

    for i, f in enumerate(report["injury_flags"]):
        if f["reason"] != "QUESTIONABLE":
            continue
        p = find_by_name(roster, f["player"])
        context = "\n".join([
            f"Starter tagged QUESTIONABLE: {f['player']} ({f['slot']})",
            "Default assumption: keep them in your starting lineup as scheduled.",
            player_block(p, "Player", sleeper, nflverse),
        ])
        calls.append({"id": f"injury_{i}", "category": "injury_watch", "context": context})

    for pos, players in report["waiver_targets"].items():
        for j, wp in enumerate(players):
            if not wp["would_start_this_week"] or wp["beats_your_weakest_by"] >= CLOSE_MARGIN:
                continue
            fa = find_by_name(free_agents, wp["name"])
            context = "\n".join([
                f"Waiver candidate: {wp['name']} ({pos}) - the formula says this would start "
                f"immediately, beating your weakest {pos} by only {wp['beats_your_weakest_by']:.1f} pts.",
                f"Reason given: {wp['reason']}",
                player_block(fa, "Candidate", sleeper, nflverse),
            ])
            calls.append({"id": f"waiver_{pos}_{j}", "category": "waiver", "context": context})

    return calls


def get_verdicts(client, calls):
    if not calls:
        return {}
    user_content = "Close calls to evaluate this week:\n\n" + "\n\n---\n\n".join(
        f"[id: {c['id']}]\n{c['context']}" for c in calls
    )
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        )
    except anthropic.AuthenticationError:
        raise SystemExit(
            "Anthropic rejected that API key (401). Real Anthropic keys look like "
            "'sk-ant-api03-...' - double check the value in .env against the one "
            "shown at console.anthropic.com > Settings > API Keys."
        )
    except anthropic.RateLimitError as e:
        retry_after = e.response.headers.get("retry-after", "a bit")
        raise SystemExit(f"Rate limited by Anthropic - try again in {retry_after}s.")
    except anthropic.APIStatusError as e:
        raise SystemExit(f"Anthropic API error ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise SystemExit("Couldn't reach the Anthropic API - check your internet connection.")

    text = next(b.text for b in response.content if b.type == "text")
    parsed = json.loads(text)
    return {v["id"]: v for v in parsed["judgment_calls"]}


def merge_verdicts(report, calls, verdicts):
    by_id = {c["id"]: c for c in calls}
    for cid, v in verdicts.items():
        call = by_id.get(cid)
        if not call:
            continue
        entry = {
            "agree_with_default": v["agree_with_default"],
            "confidence": v["confidence"],
            "verdict": v["verdict"],
            "reasoning": v["reasoning"],
        }
        if call["category"] == "start_sit":
            idx = int(cid.split("_")[1])
            report["start_sit"][idx]["ai_verdict"] = entry
        elif call["category"] == "injury_watch":
            idx = int(cid.split("_")[1])
            report["injury_flags"][idx]["ai_verdict"] = entry
        elif call["category"] == "waiver":
            _, pos, idx = cid.split("_")
            report["waiver_targets"][pos][int(idx)]["ai_verdict"] = entry

    for action in report.get("top_actions", []):
        v = verdicts.get(action.get("ref_id"))
        if v:
            action["ai_verdict"] = {
                "agree_with_default": v["agree_with_default"],
                "confidence": v["confidence"],
                "verdict": v["verdict"],
                "reasoning": v["reasoning"],
            }

    report["ai_reviewed_count"] = len(verdicts)
    return report


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "No ANTHROPIC_API_KEY found in .env. Get one at console.anthropic.com, "
            "add ANTHROPIC_API_KEY=... to your .env, then re-run this script. "
            "(This step is optional - analyze.py's report is complete without it.)"
        )

    latest_path = DATA_DIR / "latest.json"
    report_path = DATA_DIR / "report_latest.json"
    if not latest_path.exists() or not report_path.exists():
        raise SystemExit(
            "Missing data/latest.json or data/report_latest.json. Run "
            "pull_league_data.py then analyze.py first."
        )

    data = json.loads(latest_path.read_text())
    report = json.loads(report_path.read_text())
    sleeper = json.loads((DATA_DIR / "sleeper_data.json").read_text()) if (DATA_DIR / "sleeper_data.json").exists() else None
    nflverse = json.loads((DATA_DIR / "nflverse_trends.json").read_text()) if (DATA_DIR / "nflverse_trends.json").exists() else None

    calls = build_close_calls(data, report, sleeper, nflverse)
    if not calls:
        print("No close calls this week - every recommendation was already clear-cut. Nothing sent to Claude.")
        return

    print(f"Found {len(calls)} close call(s) this week. Asking Claude ({MODEL}) for judgment...")
    client = anthropic.Anthropic()
    verdicts = get_verdicts(client, calls)
    report = merge_verdicts(report, calls, verdicts)

    week = report["week"]
    with open(DATA_DIR / f"report_week{week}.json", "w") as f:
        json.dump(report, f, indent=2)
    with open(DATA_DIR / "report_latest.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nReviewed {len(verdicts)} close call(s):")
    for cid, v in verdicts.items():
        flag = "AGREES" if v["agree_with_default"] else "OVERRIDE"
        print(f"  [{flag}, {v['confidence']} confidence] {v['verdict']}")
        print(f"      {v['reasoning']}")
    print("\nSaved AI verdicts into data/report_latest.json.")


if __name__ == "__main__":
    main()
