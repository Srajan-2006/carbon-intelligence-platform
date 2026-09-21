(function () {
  MCI.applyChartDefaults();
  const mineSelect = document.getElementById("mine-select");
  const body = document.getElementById("hotspots-body");
  let barChart = null;

  const SCOPE_COLOR_BY_NUM = { "1": MCI.SCOPE_COLORS[1], "2": MCI.SCOPE_COLORS[2], "3": MCI.SCOPE_COLORS[3] };

  async function load(mineId) {
    MCI.showLoading(body, "hotspot data");
    try {
      const hotspots = await MCI.apiGet(`/mine/${mineId}/hotspots`);
      render(mineId, hotspots);
    } catch (err) {
      MCI.showError(body, err);
    }
  }

  function render(mineId, data) {
    const sources = data.hotspots;
    body.innerHTML = `
      <div class="grid-2">
        <div class="card">
          <div class="card-header"><h3>Ranked Emission Sources</h3></div>
          <canvas id="hotspot-bar" height="200"></canvas>
        </div>
        <div class="card">
          <div class="card-header"><h3>Source Detail</h3></div>
          <table class="data-table">
            <thead><tr><th>#</th><th>Source</th><th>Scope</th><th class="num">tCO2e/yr</th><th class="num">% of Total</th></tr></thead>
            <tbody>
              ${sources.map(h => `
                <tr>
                  <td>${h.rank}</td>
                  <td>${h.source}</td>
                  <td><span class="scope-pill s${h.scope}">Scope ${h.scope}</span></td>
                  <td class="num">${MCI.formatTonnes(h.tco2e)}</td>
                  <td class="num">${MCI.formatPct(h.pct_of_total)}</td>
                </tr>`).join("")}
            </tbody>
          </table>
          <p class="footnote" style="margin-top:0.6rem;">Total: ${MCI.formatTonnes(data.total_tco2e)} tCO2e/yr, attributed by the same activity &times; emission-factor calculation used throughout the platform.</p>
        </div>
      </div>
      <div class="card" style="margin-top:1rem;">
        <div class="card-header"><h3>Where To Focus First</h3></div>
        <p>${sources[0].source} is the largest single source at ${MCI.formatPct(sources[0].pct_of_total)} of total emissions (${MCI.formatTonnes(sources[0].tco2e)} tCO2e/yr). The Optimizer evaluates which combination of interventions most cost-effectively addresses these sources within a stated budget.</p>
        <a class="btn" href="${window.MCI_URLS.optimizer}">Open Optimizer &rarr;</a>
      </div>
    `;

    const ctx = document.getElementById("hotspot-bar");
    if (barChart) barChart.destroy();
    barChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: sources.map(s => s.source),
        datasets: [{
          data: sources.map(s => s.tco2e),
          backgroundColor: sources.map(s => SCOPE_COLOR_BY_NUM[s.scope]),
          borderRadius: 2,
        }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => `${MCI.formatTonnes(ctx.parsed.x)} tCO2e` } } },
        scales: { x: { grid: { color: "#2A3134" }, title: { display: true, text: "tCO2e/yr" } }, y: { grid: { display: false } } },
      },
    });
  }

  MCI.populateMineSelect(mineSelect, (mineId) => load(mineId));
  load(MCI.getSelectedMine());
})();
