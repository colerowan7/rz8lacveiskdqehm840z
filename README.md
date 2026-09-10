# Fantasy Football Manager — DTEC Cobra Kai

Free, no-subscription tooling to pull your ESPN league data and get
smart, well-informed recommendations each week. You stay in control —
this reads data and gives advice; you make the actual roster moves in
the ESPN app.

## Setup (one-time)

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Get your ESPN cookies (needed because this is a private league):
   - Log into fantasy.espn.com in Chrome
   - Open DevTools (F12) → Application tab → Cookies → `https://fantasy.espn.com`
   - Copy the values for `espn_s2` and `SWID`

3. Copy `.env.example` to `.env` and fill in:
   ```
   LEAGUE_ID=1934807293
   YEAR=2026
   ESPN_S2=<paste your espn_s2 value>
   SWID=<paste your SWID value>
   ```

4. Run the data pull:
   ```
   python scripts/pull_league_data.py
   ```
   First run will ask which team in the list is yours — note the number
   and add it to `.env` as `MY_TEAM_INDEX` to skip that prompt going forward.

## What it pulls

- Your full roster (starters + bench, injury status, projections)
- This week's opponent's roster
- League standings
- Top available free agents / waiver wire by position
- Recent league transactions (trades, adds, drops)

All saved to `data/latest.json` — this is the file the analysis layer
and dashboard will read from.

## Supplementary data sources (optional but recommended)

ESPN's own projections are decent but not the whole picture. Two more
free, no-auth-required sources sharpen the analysis:

```
python scripts/fetch_sleeper.py
python scripts/fetch_nflverse.py
```

- **Sleeper** (`fetch_sleeper.py`) — richer injury detail (practice
  participation, body part, notes) and "trending adds" — how many
  Sleeper leagues picked up a player in the last 24h, a much faster
  waiver-buzz signal than ESPN's slow-moving ownership %. Saves
  `data/sleeper_data.json`.
- **nflverse** (`fetch_nflverse.py`) — real usage stats (targets,
  carries, target share) from [nflverse-data](https://github.com/nflverse/nflverse-data)
  to sanity-check ESPN's projections against actual recent production.
  Early in a season (before there's current-year data) it falls back
  to full prior-season per-game averages; once games are on the board
  it switches to a trailing 3-week recent-form window automatically.
  Saves `data/nflverse_trends.json`.

Both are optional — `analyze.py` runs fine without them, just with
less context. Re-run them periodically (Sleeper's trending data is
only useful if it's fresh; nflverse's weekly file updates after each
week's games).

## Analysis

`scripts/analyze.py` reads `data/latest.json` (plus `sleeper_data.json`
/ `nflverse_trends.json` if present) and generates a weekly
recommendation report: start/sit swaps, injury/bye alerts (enriched
with Sleeper detail when available), waiver-wire upgrades by position
(annotated with nflverse recent-form ppg when available), Sleeper
trending adds, and a projected score for your matchup.

```
python scripts/analyze.py
```

Saves `data/report_week{N}.json` and `data/report_latest.json` (which
the dashboard picks up automatically). Run this right after
`pull_league_data.py` each week.

## AI judgment layer (optional, costs a few cents per run)

`analyze.py` is pure arithmetic — it compares projected points and
roster rules. That's reliable for obvious calls, but it can't weigh
things a spreadsheet can't: how much stock to put in a QUESTIONABLE
tag, whether a brutal/cushy matchup should tip a near-even start/sit,
or whether recent real production should outweigh a stale projection.

`scripts/ai_insights.py` finds only the genuinely *close* calls in the
report (small point margins, ambiguous injury status) and sends those
to Claude for real judgment — not the obvious ones, so it stays cheap
and doesn't waste calls confirming what the math already got right.

Setup:
```
ANTHROPIC_API_KEY=<your key from console.anthropic.com>
```
Add that to `.env`, then:
```
python scripts/ai_insights.py
```

This makes real, billed API calls (typically a few cents per week —
only the close calls get sent, usually a handful of players). It's
entirely optional: skip it and `analyze.py`'s report is still complete
and useful, just without the extra judgment layer on the ambiguous
cases. Verdicts get written back into `data/report_latest.json` and
show up in the dashboard as violet "AI AGREES" / "AI OVERRIDE" notes.

## Dashboard

A local HTML dashboard visualizes `data/latest.json` and
`data/report_latest.json`: recommendations, your roster
(starters/bench/IR), this week's opponent, league standings, and
waiver-wire free agents by position.

```
python scripts/serve_dashboard.py
```

This starts a local server and opens the dashboard in your browser at
`http://localhost:8765/frontend/index.html`. (It has to be served over
HTTP, not opened as a plain file, so the page can fetch the JSON data.)

## Live dashboard (phone-accessible, always-on)

The dashboard is also published as a static site, kept up to date
automatically, so you can check it from your phone without your
computer needing to be on:

**https://colerowan7.github.io/rz8lacveiskdqehm840z/frontend/index.html**

Bookmark it or add it to your phone's home screen. The link is
intentionally an unguessable random string (not your GitHub username
or anything descriptive) and has a `noindex` tag so search engines
won't pick it up — but note it's still a public URL with no login: don't
share it, and treat it the same as you would any other "unlisted, not
secret" link.

How it stays live:
- **`.github/workflows/update-dashboard.yml`** runs every 6 hours
  (and on-demand via the Actions tab or GitHub mobile app — "Run
  workflow"): pulls fresh ESPN/Sleeper/nflverse data, re-runs
  `analyze.py`, and publishes the result. Free — no billed API calls.
- **`.github/workflows/ai-insights.yml`** is manual-trigger **only**
  (never scheduled) since it makes real, billed Claude API calls. Run
  it from the Actions tab whenever you want a fresh AI judgment pass
  before setting your lineup.
- Your ESPN cookies, league ID, and Anthropic API key live as
  encrypted GitHub Actions secrets (Settings → Secrets and variables →
  Actions on the repo) — never committed to the repo itself.

To redeploy after code changes: just `git push`. GitHub Pages rebuilds
automatically from the `master` branch.

## Weekly routine (running locally instead)

```
python scripts/pull_league_data.py
python scripts/fetch_sleeper.py
python scripts/fetch_nflverse.py
python scripts/analyze.py
python scripts/ai_insights.py   # optional, needs ANTHROPIC_API_KEY
python scripts/serve_dashboard.py
```

## Next steps (not built yet)

- [ ] FantasyPros public rankings (scraped) — expert-consensus
      rankings as a third opinion alongside ESPN's projections
- [ ] Trade suggestions (currently out of scope — start/sit and
      waivers only)
