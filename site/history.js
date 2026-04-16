/**
 * RoachFinder 3.0 — History Page Logic
 * Fetches data/history.json (prior seasons) and data/season_record.json (current)
 * Renders season summary tables + expandable per-week accordions.
 */

document.addEventListener("DOMContentLoaded", async function () {
  const container = document.getElementById("history-content");

  const [history, seasonRecord] = await Promise.all([
    fetchJSON("data/history.json"),
    fetchJSON("data/season_record.json"),
  ]);

  let html = "";

  // ── Current Season (from season_record.json) ──
  html += renderSeason(
    "2026-27",
    "2026-2027",
    seasonRecord ? seasonRecord.cumulative : null,
    seasonRecord ? buildWeekSummariesFromRecord(seasonRecord) : {},
    true
  );

  // ── Prior Seasons (from history.json, newest first) ──
  if (history && history.seasons) {
    const reversed = [...history.seasons].reverse();
    for (const season of reversed) {
      html += renderSeason(
        season.label,
        season.label_long,
        season.summary,
        season.weeks || {},
        false
      );
    }
  }

  container.innerHTML = html;

  // Wire up accordion clicks
  document.querySelectorAll(".accordion-header").forEach(function (hdr) {
    hdr.addEventListener("click", function () {
      this.classList.toggle("open");
      const body = this.nextElementSibling;
      if (body) body.classList.toggle("open");
    });
  });
});

/**
 * Build per-week summaries from the season_record.json weeks data
 * so it matches the history.json weeks format.
 */
function buildWeekSummariesFromRecord(record) {
  const weeks = {};
  if (!record || !record.weeks) return weeks;

  for (const [weekNum, weekData] of Object.entries(record.weeks)) {
    let wins = 0, losses = 0, pushes = 0;
    for (const game of weekData.games || []) {
      if (game.result === "win") wins++;
      else if (game.result === "loss") losses++;
      else if (game.result === "push") pushes++;
    }
    const total = wins + losses;
    weeks[weekNum] = {
      wins: wins,
      losses: losses,
      pushes: pushes,
      win_pct: total > 0 ? parseFloat(((wins / total) * 100).toFixed(2)) : 0,
    };
  }
  return weeks;
}

/**
 * Render a full season block: heading, summary table, accordion with weeks.
 */
function renderSeason(label, labelLong, summary, weeks, isCurrent) {
  let s = "";

  if (isCurrent) {
    s += `<p class="section-subtitle">${label} Season &middot; Current</p>`;
    s += `<h1 class="section-title hero">${labelLong} NFL Season</h1>`;
  } else {
    s += `<div class="eyebrow-row"><span class="section-eyebrow">${labelLong} Season</span></div>`;
  }

  // Summary table
  if (summary) {
    s += `<table class="season-table">`;
    s += `<thead><tr>
      <th>Category</th>
      <th class="wins">Wins</th>
      <th class="losses">Losses</th>
      <th class="overall">Overall</th>
    </tr></thead>`;
    s += `<tbody>`;
    s += summaryRow("All Spreads", summary.all_spreads);
    s += summaryRow("Above Median", summary.above_median);
    s += summaryRow("Top 5", summary.top_5);
    s += `</tbody></table>`;
  }

  // Accordion with per-week results
  const weekNums = Object.keys(weeks)
    .map(Number)
    .sort((a, b) => a - b);

  if (weekNums.length > 0) {
    s += `<div class="accordion">`;
    s += `<div class="accordion-header">`;
    s += `<span>Season Results &amp; Statistics</span>`;
    s += `<span class="arrow">&#9660;</span>`;
    s += `</div>`;
    s += `<div class="accordion-body">`;

    // Week quick-jump buttons
    s += `<div class="week-buttons">`;
    for (let w = 2; w <= 16; w++) {
      s += `<button class="week-btn" onclick="document.getElementById('week-${label}-${w}')?.scrollIntoView({behavior:'smooth'})">${w}</button>`;
    }
    s += `</div>`;

    // Per-week details
    for (const wn of weekNums) {
      const wk = weeks[wn];
      const pctColor = wk.win_pct >= 50 ? "var(--accent-hi)" : "var(--red-hi)";
      s += `<div id="week-${label}-${wn}" style="margin:14px 0;padding:18px 20px;background:var(--bg-1);border-radius:8px;border:1px solid var(--line)">`;
      s += `  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px">`;
      s += `    <h4 style="margin:0">Week ${wn}</h4>`;
      s += `    <span style="font-variant-numeric:tabular-nums;font-weight:700;color:${pctColor}">${wk.win_pct}%</span>`;
      s += `  </div>`;
      s += `  <div style="display:flex;gap:8px;flex-wrap:wrap">`;
      s += `    <span class="game-detail">W <strong style="color:var(--accent-hi)">${wk.wins}</strong></span>`;
      s += `    <span class="game-detail">L <strong style="color:var(--red-hi)">${wk.losses}</strong></span>`;
      s += `    <span class="game-detail">Push <strong>${wk.pushes || 0}</strong></span>`;
      s += `  </div>`;
      if (wk.results_url) {
        s += `  <p style="margin-top:12px;font-size:0.88rem"><a href="${wk.results_url}" target="_blank" rel="noopener">View Matchup Results &rarr;</a></p>`;
      }
      s += `</div>`;
    }

    s += `</div></div>`; // end accordion-body, accordion
  }

  s += `<hr class="hr-divider">`;
  return s;
}

function summaryRow(label, cat) {
  if (!cat) return "";
  const total = cat.wins + cat.losses;
  const pct = cat.win_pct !== undefined ? cat.win_pct : (total > 0 ? ((cat.wins / total) * 100).toFixed(3) : "0.000");
  return `<tr>
    <td>${label}</td>
    <td class="win-val">${cat.wins}</td>
    <td class="loss-val">${cat.losses}</td>
    <td>${pct}%</td>
  </tr>`;
}
