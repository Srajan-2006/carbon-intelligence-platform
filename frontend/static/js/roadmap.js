(function () {
  MCI.applyChartDefaults();
  const mineSelect = document.getElementById("mine-select");
  const body = document.getElementById("roadmap-body");
  const provStrip = document.getElementById("roadmap-provenance");
  let cumChart = null;

  async function load(mineId) {
    MCI.showLoading(body, "roadmap");
    try {
      const data = await MCI.apiGet(`/mine/${mineId}/roadmap`);
      render(mineId, data.roadmap);
      const provValues = [...new Set(data.roadmap.map(r => r.provenance))];
      MCI.renderProvenanceStrip(provStrip, provValues, "Roadmap milestones are prototype planning assumptions, not verified project commitments.");
    } catch (err) {
      MCI.showError(body, err);
    }
  }

  function render(mineId, milestones) {
    body.innerHTML = `
      <div class="card">
        <div class="card-header"><h3>Cumulative Reduction Pathway</h3></div>
        <canvas id="cum-chart" height="110"></canvas>
      </div>
      <div class="stack" style="margin-top:1rem;">
        ${milestones.map((m, idx) => `
          <div class="card" style="display:grid;grid-template-columns:90px 1fr auto;gap:1rem;align-items:start;">
            <div>
              <div class="kpi-value" style="font-size:1.4rem;">${m.year}</div>
              <div class="footnote">Milestone ${idx + 1} of ${milestones.length}</div>
            </div>
            <div>
              <div class="name" style="font-weight:600;margin-bottom:0.2em;">${m.milestone}</div>
              <p style="margin:0;">${m.intervention_summary}</p>
            </div>
            <div style="text-align:right;">
              <div class="mono" style="font-size:0.95rem;">${MCI.formatINRCompact(m.investment_inr)}</div>
              <div class="footnote">+${MCI.formatPct(m.expected_reduction_pct)} this stage</div>
              <div class="footnote">${MCI.formatPct(m.cumulative_reduction_pct)} cumulative</div>
              <div class="footnote">${MCI.formatTonnes(m.remaining_emissions_t)} t remaining</div>
            </div>
          </div>
        `).join("")}
      </div>
      <p class="footnote" style="margin-top:1rem;">${MCI.provenanceBadgeHTML("synthetic_prototype")} Roadmap years, milestones and figures are illustrative prototype planning assumptions and should be replaced with verified engineering studies before real-world commitment.</p>
    `;

    const ctx = document.getElementById("cum-chart");
    if (cumChart) cumChart.destroy();
    cumChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: milestones.map(m => m.year),
        datasets: [{
          label: "Cumulative reduction (%)",
          data: milestones.map(m => m.cumulative_reduction_pct),
          borderColor: "#3FA06E",
          backgroundColor: "rgba(63,160,110,0.14)",
          fill: true,
          tension: 0.2,
          pointRadius: 3,
        }],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { title: { display: true, text: "% cumulative reduction" }, grid: { color: "#2A3134" } }, x: { grid: { display: false } } },
      },
    });
  }

  MCI.populateMineSelect(mineSelect, (mineId) => load(mineId));
  load(MCI.getSelectedMine());
})();
