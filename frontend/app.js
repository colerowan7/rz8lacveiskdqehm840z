const SLOT_ORDER = ["QB", "RB", "RB/WR", "WR", "WR/TE", "TE", "FLEX", "RB/WR/TE", "OP", "D/ST", "K", "BE", "IR"];

const CATEGORY_LABEL = {
  start_sit: "LINEUP",
  injury_watch: "INJURY WATCH",
  waiver: "WAIVER WIRE",
  trending: "TRENDING",
};

function aiVerdictHtml(v) {
  if (!v) return "";
  const tag = v.agree_with_default ? "AI AGREES" : "AI OVERRIDE";
  return `
    <div class="ai-verdict">
      <span class="ai-tag">${tag}</span><span class="ai-confidence">${v.confidence} confidence</span>
      <div class="ai-reasoning"><b>${v.verdict}</b> &mdash; ${v.reasoning}</div>
    </div>`;
}

function slotRank(slot) {
  const i = SLOT_ORDER.indexOf(slot);
  return i === -1 ? SLOT_ORDER.length : i;
}

function fmtNum(n) {
  if (n === null || n === undefined) return "–";
  return Number(n).toFixed(1);
}

function injuryBadge(status) {
  if (!status || status === "ACTIVE") return "";
  const cls = status === "OUT" || status === "DOUBTFUL" || status === "IR" ? "bad"
    : status === "QUESTIONABLE" ? "warn"
    : "good";
  return `<span class="badge ${cls}">${status}</span>`;
}

function playerRow(p, { showSlot } = { showSlot: true }) {
  return `
    <tr>
      ${showSlot ? `<td><span class="slot-badge">${p.lineup_slot || p.position}</span></td>` : ""}
      <td>
        <div class="player-name">${p.name}</div>
        <div class="player-meta">${p.position} &middot; ${p.pro_team || "FA"}${p.pro_opponent ? ` vs ${p.pro_opponent}` : ""}</div>
      </td>
      <td>${injuryBadge(p.injury_status)}</td>
      <td class="num">${fmtNum(p.projected_points)}</td>
      <td class="num">${fmtNum(p.points)}</td>
    </tr>`;
}

function rosterTable(roster) {
  const sorted = [...roster].sort((a, b) => slotRank(a.lineup_slot) - slotRank(b.lineup_slot));
  const starters = sorted.filter(p => p.lineup_slot !== "BE" && p.lineup_slot !== "IR");
  const bench = sorted.filter(p => p.lineup_slot === "BE");
  const ir = sorted.filter(p => p.lineup_slot === "IR");

  let rows = starters.map(p => playerRow(p)).join("");
  if (bench.length) {
    rows += `<tr class="section-row"><td colspan="5">Bench</td></tr>`;
    rows += bench.map(p => playerRow(p)).join("");
  }
  if (ir.length) {
    rows += `<tr class="section-row"><td colspan="5">IR</td></tr>`;
    rows += ir.map(p => playerRow(p)).join("");
  }

  return `
    <table>
      <thead>
        <tr>
          <th title="Where this player is lined up this week">Slot</th>
          <th>Player</th>
          <th title="Injury designation, if any">Status</th>
          <th class="num" title="Projected points for this week">Proj</th>
          <th class="num" title="Points scored so far — 0 before games start">Actual</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function standingsTable(standings, myTeamName) {
  const rows = standings.map(t => `
    <tr class="${t.team_name === myTeamName ? "me-row" : ""}">
      <td class="team-cell"><span class="rank">${t.standing}</span>${t.team_name}</td>
      <td class="num">${t.wins}-${t.losses}</td>
      <td class="num">${fmtNum(t.points_for)}</td>
    </tr>`).join("");
  return `
    <table class="standings-table">
      <thead><tr><th>Team</th><th class="num">Record</th><th class="num">PF</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function freeAgentTabs(freeAgents) {
  const byPos = {};
  for (const p of freeAgents) {
    byPos[p.position] = byPos[p.position] || [];
    byPos[p.position].push(p);
  }
  const positions = Object.keys(byPos);
  positions.forEach(pos => byPos[pos].sort((a, b) => (b.projected_points || 0) - (a.projected_points || 0)));

  const tabs = positions.map((pos, i) =>
    `<button class="tab-btn ${i === 0 ? "active" : ""}" data-pos="${pos}">${pos}</button>`
  ).join("");

  const panels = positions.map((pos, i) => {
    const rows = byPos[pos].slice(0, 10).map(p => playerRow(p, { showSlot: false })).join("");
    return `
      <div class="fa-panel ${i === 0 ? "active" : ""}" data-panel="${pos}">
        <table>
          <thead>
            <tr>
              <th>Player</th>
              <th title="Injury designation, if any">Status</th>
              <th class="num" title="Projected points for this week">Proj</th>
              <th class="num" title="Points scored so far — 0 before games start">Actual</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }).join("");

  return `<div class="tabs">${tabs}</div>${panels}`;
}

function wireFreeAgentTabs(root) {
  root.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      root.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      root.querySelectorAll(".fa-panel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      root.querySelector(`.fa-panel[data-panel="${btn.dataset.pos}"]`).classList.add("active");
    });
  });
}

function activityList(activity) {
  if (!activity || activity.length === 0) {
    return `<p class="empty-note">No recent activity.</p>`;
  }
  return `<ul class="activity-list">${activity.map(a => `<li>${a}</li>`).join("")}</ul>`;
}

function timeAgo(iso) {
  const then = new Date(iso).getTime();
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

/* ===================== Top bar ===================== */

function topBar(data) {
  return `
    <div class="topbar">
      <div class="topbar-inner">
        <div>
          <h1>${data.my_team.team_name}</h1>
          <div class="subtitle">League ${data.league_id} &middot; ${data.year} season &middot; updated ${timeAgo(data.pulled_at)}</div>
        </div>
        <div class="topbar-stats">
          <div class="stat-pill">Record <b>${data.my_team.wins}-${data.my_team.losses}</b></div>
          <div class="stat-pill">Standing <b>#${data.my_team.standing}</b></div>
        </div>
      </div>
    </div>`;
}

/* ===================== Hero matchup ===================== */

function capacityLine(report) {
  const cap = report && report.roster_capacity;
  if (!cap) return "";
  let line = `Roster: <b>${cap.bench_filled}/${cap.bench_slots}</b> bench full, <b>${cap.ir_filled}/${cap.ir_slots}</b> IR used. `;
  if (cap.bench_open > 0) {
    line += `You have ${cap.bench_open} open bench spot(s) &mdash; add a waiver player without dropping anyone.`;
  } else if (cap.ir_eligible_on_bench.length) {
    line += `Bench is full, but <b>${cap.ir_eligible_on_bench.join(", ")}</b> qualifies for IR &mdash; move them there to free a spot.`;
  } else {
    line += `Bench is full &mdash; adding a waiver player means dropping someone.`;
  }
  return line;
}

function heroMatchup(data, report) {
  const me = data.my_team;
  const opp = data.opponent_team;
  const mp = report ? report.matchup_projection : null;
  const myScore = mp ? mp.my_projected : null;
  const oppScore = mp && mp.opponent_projected !== null && mp.opponent_projected !== undefined ? mp.opponent_projected : null;

  let barFillPct = 50;
  let leanText = "Run <code>python scripts/analyze.py</code> for a projection.";
  if (myScore !== null && oppScore !== null) {
    const total = myScore + oppScore;
    barFillPct = total > 0 ? Math.round((myScore / total) * 100) : 50;
    const margin = mp.margin;
    leanText = margin > 0
      ? `Favored by <b>${margin.toFixed(1)}</b> pts`
      : margin < 0
      ? `Underdog by <b>${Math.abs(margin).toFixed(1)}</b> pts`
      : `Dead even`;
  }

  const capLine = capacityLine(report);

  return `
    <div class="wrap hero">
      <div class="hero-week">WEEK ${data.current_week}</div>
      <div class="hero-matchup">
        <div class="hero-team me">
          <div class="hero-team-name">${me.team_name}</div>
          <div class="hero-score">${myScore !== null ? myScore : "–"}</div>
          <div class="hero-team-record">${me.wins}-${me.losses} &middot; #${me.standing}</div>
        </div>
        <div class="hero-mid">
          <div class="hero-vs-label">PROJECTED SCORE</div>
          <div class="hero-bar-track"><div class="hero-bar-fill" style="width:${barFillPct}%"></div></div>
          <div class="hero-lean">${leanText}</div>
        </div>
        ${opp ? `
        <div class="hero-team opponent">
          <div class="hero-team-name">${opp.team_name}</div>
          <div class="hero-score">${oppScore !== null ? oppScore : "–"}</div>
          <div class="hero-team-record">${opp.wins}-${opp.losses} &middot; #${opp.standing}</div>
        </div>` : `<div class="hero-team opponent"><div class="hero-team-name">No matchup found</div></div>`}
      </div>
      ${capLine ? `<div class="hero-capacity">${capLine}</div>` : ""}
    </div>`;
}

/* ===================== Top actions feed ===================== */

function actionSeverity(a) {
  if (a.category === "trending") return "info";
  if (a.urgent) return "high";
  if (a.category === "injury_watch") return "medium";
  return "good";
}

function actionImpactPill(a) {
  if (a.urgent) return `<span class="impact-pill bad">URGENT</span>`;
  if (a.category === "trending") return `<span class="impact-pill info">BUZZ</span>`;
  return `<span class="impact-pill good">+${a.impact} pts</span>`;
}

function topActionsSection(report) {
  let body;
  if (!report) {
    body = `<div class="action-empty">No report yet. Run <code>python scripts/analyze.py</code> to generate this week's recommendations.</div>`;
  } else if (!report.top_actions || !report.top_actions.length) {
    body = `<div class="action-empty">Nothing urgent this week &mdash; your lineup looks solid and no clear waiver upgrades were found.</div>`;
  } else {
    body = `
      <div class="action-feed">
        ${report.top_actions.map((a, i) => `
          <div class="action-card sev-${actionSeverity(a)}">
            <div class="action-rank">${i + 1}</div>
            <div class="action-body">
              <div class="action-eyebrow">${CATEGORY_LABEL[a.category] || a.category}</div>
              <div class="action-headline">${a.headline} ${actionImpactPill(a)}</div>
              <div class="action-detail">${a.detail}</div>
              ${aiVerdictHtml(a.ai_verdict)}
            </div>
          </div>`).join("")}
      </div>`;
  }

  return `
    <div class="wrap">
      <div class="section-heading"><h2>Top Actions This Week</h2></div>
      <p class="section-sub">New to fantasy? This is the short version &mdash; ranked by how much it actually matters. Everything else below is supporting detail. You still make the moves yourself in the ESPN app.</p>
      ${body}
    </div>`;
}

/* ===================== Tabbed detail section ===================== */

function injuryAndSwapBlock(report) {
  if (!report) return "";
  const injuryHtml = report.injury_flags.length
    ? report.injury_flags.map(f => `<li>[${f.slot}] ${f.player}: <span class="badge ${f.reason === "QUESTIONABLE" ? "warn" : "bad"}">${f.reason}</span>${f.detail ? ` <span class="player-meta">${f.detail}</span>` : ""}${aiVerdictHtml(f.ai_verdict)}</li>`).join("")
    : `<li class="empty-note">No injury/bye concerns among your starters.</li>`;

  const swapHtml = report.start_sit.length
    ? report.start_sit.map(r => `<li>[${r.slot}] Start <b>${r.start}</b> (${r.start_projected}) over ${r.sit} (${r.sit_projected}) &mdash; ${r.reason}${aiVerdictHtml(r.ai_verdict)}</li>`).join("")
    : `<li class="empty-note">No swaps recommended &mdash; lineup looks optimal.</li>`;

  return `
    <div class="panel-card">
      <h3 class="panel-title">Start/Sit &amp; Injury Watch</h3>
      <p class="rec-help">The full breakdown behind the top actions above &mdash; every injury/bye concern and every suggested lineup swap for this roster, not just the highest-impact one.</p>
      <div class="rec-grid">
        <div>
          <h4>Injury / Bye Alerts</h4>
          <ul class="rec-list">${injuryHtml}</ul>
        </div>
        <div>
          <h4>Start/Sit Swaps</h4>
          <ul class="rec-list">${swapHtml}</ul>
        </div>
      </div>
    </div>`;
}

function waiverPanel(data, report) {
  if (!report) {
    return `
      <div class="panel-card">
        <p class="empty-note">No report yet. Run <code>python scripts/analyze.py</code> for waiver-wire recommendations.</p>
      </div>`;
  }

  const waiverEntries = Object.entries(report.waiver_targets);
  const waiverHtml = waiverEntries.length
    ? waiverEntries.map(([pos, players]) => `
        <div class="waiver-pos-block">
          <h4 class="waiver-pos-label"><span class="slot-badge">${pos}</span></h4>
          <ul class="rec-list">
            ${players.map(p => `
              <li>
                <div><b>${p.name}</b> <span class="player-meta">(${p.pro_team}${p.percent_owned != null ? `, ${p.percent_owned.toFixed(0)}% owned` : ""})</span> <span class="badge ${p.would_start_this_week ? "good" : "warn"}">${p.would_start_this_week ? "WOULD START" : "BENCH ONLY"}</span></div>
                <div class="player-meta">${p.reason}</div>
                ${aiVerdictHtml(p.ai_verdict)}
              </li>`).join("")}
          </ul>
        </div>`).join("")
    : `<p class="empty-note">No clear waiver-wire upgrades found.</p>`;

  const trendingHtml = (report.trending_adds && report.trending_adds.length)
    ? `<div class="waiver-group">${report.trending_adds.map(t => `<span class="waiver-chip">${t.name} (${t.position}, ${t.pro_team}) &middot; ${t.sleeper_adds_24h.toLocaleString()} adds/24h</span>`).join("")}</div>`
    : "";

  const sourcesLine = report.sources
    ? `ESPN (your league)${report.sources.sleeper ? " + Sleeper (injury detail & waiver trends)" : ""}${report.sources.nflverse ? " + nflverse (real season stats)" : ""}${report.ai_reviewed_count ? ` + Claude AI (${report.ai_reviewed_count} close call${report.ai_reviewed_count === 1 ? "" : "s"} reviewed)` : ""}`
    : "ESPN (your league)";

  return `
    <div class="panel-card">
      <h3 class="panel-title">Waiver Wire Upgrades</h3>
      <p class="rec-help">Players nobody in your league owns who project to outscore your weakest rostered player at that spot &mdash; a value comparison, not a forced swap. <b>WOULD START</b> means they'd actually crack your starting lineup this week (real points); <b>BENCH ONLY</b> means they'd sit on your bench for now (a depth add / stash). Add via your league's waiver process in the ESPN app.</p>
      ${waiverHtml}
      ${trendingHtml ? `
      <h4>Trending Adds (Sleeper, last 24h)</h4>
      <p class="rec-help">Players a lot of managers on Sleeper (a different fantasy app, used here just for this signal) picked up in the last day &mdash; often means something just happened before ESPN's projections caught up.</p>
      ${trendingHtml}` : ""}
      <p class="sources-footer">Sources: ${sourcesLine}</p>
    </div>`;
}

function sectionTabsHtml(data, report) {
  const tabs = [
    { id: "roster", label: "My Roster" },
    { id: "opponent", label: data.opponent_team ? "Opponent" : "Opponent" },
    { id: "waivers", label: "Waivers" },
    { id: "standings", label: "Standings" },
    { id: "activity", label: "Activity" },
  ];
  const nav = tabs.map((t, i) =>
    `<button class="section-tab-btn ${i === 0 ? "active" : ""}" data-tab="${t.id}">${t.label}</button>`
  ).join("");

  const rosterPanel = `
    <div class="tab-panel active" data-panel="roster">
      ${injuryAndSwapBlock(report)}
      <div class="panel-card" style="margin-top:14px;">
        <h3 class="panel-title">My Roster <span class="count">${data.my_team.roster.length} players</span></h3>
        <p class="rec-help">Only the top section counts toward your score this week &mdash; "Bench" and "IR" players sit out no matter how well they play in real life. <b>Slot</b> is where they're lined up (single positions play only there; "RB/WR/TE" is your flex spot, open to any of those three). <b>Status</b> flags injuries: OUT/DOUBTFUL usually means they won't play, QUESTIONABLE is a game-time call.</p>
        ${rosterTable(data.my_team.roster)}
      </div>
    </div>`;

  const opponentPanel = `
    <div class="tab-panel" data-panel="opponent">
      ${data.opponent_team ? `
      <div class="panel-card">
        <h3 class="panel-title">${data.opponent_team.team_name} <span class="count">this week's opponent</span></h3>
        <p class="rec-help">Same layout as your roster &mdash; only their non-bench players (top section) count against you in this matchup.</p>
        ${rosterTable(data.opponent_team.roster)}
      </div>` : `<div class="panel-card"><p class="empty-note">No matchup found for week ${data.current_week}.</p></div>`}
    </div>`;

  const waiversPanel = `
    <div class="tab-panel" data-panel="waivers">
      ${waiverPanel(data, report)}
      <div class="panel-card" style="margin-top:14px;" id="fa-card">
        <h3 class="panel-title">Browse All Free Agents <span class="count">${data.free_agents.length} available</span></h3>
        <p class="rec-help">Everyone available, not just the ones flagged as upgrades above. Tabs group by position, ranked by projected points.</p>
        ${freeAgentTabs(data.free_agents)}
      </div>
    </div>`;

  const standingsPanel = `
    <div class="tab-panel" data-panel="standings">
      <div class="panel-card">
        <h3 class="panel-title">Standings</h3>
        ${standingsTable(data.standings, data.my_team.team_name)}
      </div>
    </div>`;

  const activityPanel = `
    <div class="tab-panel" data-panel="activity">
      <div class="panel-card">
        <h3 class="panel-title">Recent Activity</h3>
        ${activityList(data.recent_activity)}
      </div>
    </div>`;

  return `
    <div class="wrap">
      <div class="section-heading"><h2>Details</h2></div>
      <div class="section-tabs">${nav}</div>
      ${rosterPanel}${opponentPanel}${waiversPanel}${standingsPanel}${activityPanel}
    </div>`;
}

function wireSectionTabs(root) {
  root.querySelectorAll(".section-tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      root.querySelectorAll(".section-tab-btn").forEach(b => b.classList.remove("active"));
      root.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      root.querySelector(`.tab-panel[data-panel="${btn.dataset.tab}"]`).classList.add("active");
    });
  });
}

/* ===================== Render ===================== */

function render(data, report) {
  const app = document.getElementById("app");
  app.innerHTML = `
    ${topBar(data)}
    ${heroMatchup(data, report)}
    ${topActionsSection(report)}
    ${sectionTabsHtml(data, report)}
  `;
  wireSectionTabs(app);
  const faCard = document.getElementById("fa-card");
  if (faCard) wireFreeAgentTabs(faCard);
}

async function fetchJsonIfPresent(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`HTTP ${res.status} loading ${url}`);
  return res.json();
}

async function init() {
  const app = document.getElementById("app");
  try {
    // Relative, not absolute — works both at http://localhost:8765/frontend/
    // and at https://<user>.github.io/<repo>/frontend/ (a subpath, not domain root).
    const data = await fetchJsonIfPresent("../data/latest.json");
    if (!data) throw new Error("HTTP 404 loading data/latest.json");
    const report = await fetchJsonIfPresent("../data/report_latest.json");
    render(data, report);
  } catch (err) {
    app.innerHTML = `<p class="error">Couldn't load data/latest.json (${err.message}).<br>Run <code>python scripts/pull_league_data.py</code>, then make sure you're viewing this page through the local server (see README), not by opening the file directly.</p>`;
  }
}

init();
