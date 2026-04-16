/**
 * RoachFinder 3.0 — Current Week Page Logic
 * Fetches data/current_week.json and renders the week's picks.
 */

document.addEventListener("DOMContentLoaded", async function () {
    const container = document.getElementById("current-week-content");
    const data = await fetchJSON("data/current_week.json");

    if (!data || !data.games || data.games.length === 0) {
        container.innerHTML =
            '<p class="section-subtitle">2026 – 2027 Season</p>' +
            '<h1 class="section-title hero">Current Week</h1>' +
            '<div class="about-section" style="max-width:620px;margin:40px auto;text-align:center">' +
            '  <h3>No picks available yet.</h3>' +
            '  <p>Run <code class="mono">python run_week.py</code> to generate this week&rsquo;s predictions.</p>' +
            '</div>';
        return;
    }

    const week = data.week;
    const medianCF = data.rolling_median_cf;
    const games = data.games; // sorted by CF desc from predictor

    let html = "";

    // ── Hero heading ──
    html += `<p class="section-subtitle">2026 – 2027 Season</p>`;
    html += `<h1 class="section-title hero">Week ${week}</h1>`;

    html += `<div style="text-align:center;margin-bottom:32px">`;
    html += `  <span class="section-eyebrow gold">Rolling Median CF &middot; ${Number(medianCF).toFixed(3)}</span>`;
    html += `</div>`;

    // ── Confidence Spectrum ──
    html += `<div class="eyebrow-row"><span class="section-eyebrow">Confidence Spectrum</span></div>`;
    html += `<div class="spectrum-container">`;

    const maxCF = games[0].confidence_factor;
    const minCF = games[games.length - 1].confidence_factor;
    const range = maxCF - minCF || 1;

    for (const g of games) {
        const pct = (g.confidence_factor - minCF) / range;
        const widthPct = Math.max(pct * 100, 8);
        const hue = pct * 120; // 0=red, 120=green

        const label = g.winning_pick_label;
        const cfDisplay = g.confidence_factor.toFixed(1);

        html += `<div class="spectrum-bar-wrapper">`;
        html += `<div class="spectrum-bar" style="width:${widthPct}%;background:hsl(${hue},65%,52%)">`;
        if (widthPct >= 25) {
            html += `<span>${label}</span><span>${cfDisplay}</span>`;
            html += `</div></div>`;
        } else {
            html += `<span></span><span>${cfDisplay}</span>`;
            html += `</div><span class="spectrum-label-outside">${label}</span>`;
            html += `</div>`;
        }
    }
    html += `</div>`;

    // ── Top 5 Picks ──
    html += `<div class="eyebrow-row"><span class="section-eyebrow gold">Top 5 Picks</span></div>`;
    html += `<div class="pick-boxes">`;
    for (let i = 0; i < Math.min(5, games.length); i++) {
        html += `<div class="pick-box numbered">`;
        html += `  <div class="rank">Rank #${i + 1}</div>`;
        html += `  <div>${games[i].winning_pick_label}</div>`;
        html += `</div>`;
    }
    html += `</div>`;

    // ── Above Median ──
    html += `<div class="eyebrow-row"><span class="section-eyebrow blue">&ge; Rolling Median CF</span></div>`;
    html += `<div class="pick-boxes">`;
    for (const g of games) {
        if (g.confidence_factor >= medianCF) {
            html += `<div class="pick-box above-med">${g.winning_pick_label}</div>`;
        }
    }
    html += `</div>`;

    // ── Game Cards ──
    html += `<div class="eyebrow-row"><span class="section-eyebrow">All Matchups</span></div>`;

    for (const g of games) {
        html += `<div class="game-card">`;

        // Info section
        html += `<div class="game-card-section info">`;
        html += `  <div class="game-card-title">${g.away_team_short} @ ${g.home_team_short}</div>`;
        html += `  <div style="text-align:center">`;
        html += `    <span class="game-detail">Stadium <strong>${g.stadium}</strong></span>`;
        html += `    <span class="game-detail">Time <strong>${g.game_time}</strong></span>`;
        html += `    <span class="game-detail">Cheapest Ticket <strong>${g.cheapest_ticket}</strong></span>`;
        html += `  </div>`;
        html += `</div>`;

        // Sportsbook section
        html += `<div class="game-card-section sportsbook">`;
        html += `  <div style="text-align:center">`;
        html += `    <span class="game-detail">O/U <strong>${g.over_under}</strong></span>`;
        html += `    <span class="game-detail">Spread <strong>${g.favored_team_full || g.favored_team} ${g.spread_amount}</strong></span>`;
        html += `  </div>`;
        html += `</div>`;

        // Algorithm Pick section
        html += `<div class="game-card-section pick">`;
        html += `  <div style="text-align:center">`;
        html += `    <span class="game-detail">Winner <strong>${g.pick_winner}</strong></span>`;
        html += `    <span class="game-detail">Loser <strong>${g.pick_loser}</strong></span>`;
        html += `    <span class="game-detail">CF <strong>${g.confidence_factor.toFixed(4)}</strong></span>`;
        html += `  </div>`;
        html += `  <div class="winning-pick">${g.winning_pick_label}</div>`;
        html += `</div>`;

        html += `</div>`; // end game-card
    }

    container.innerHTML = html;
});
