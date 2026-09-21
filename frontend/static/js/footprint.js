(function () {
  MCI.applyChartDefaults();
  const mineSelect = document.getElementById("mine-select");
  const body = document.getElementById("footprint-body");
  const provStrip = document.getElementById("provenance-strip");
  let stackChart = null;

  async function load(mineId) {
    MCI.showLoading(body, "footprint data");
    try {
      const [baseline, sample] = await Promise.all([
        MCI.apiGet(`/mine/${mineId}/baseline`),
        MCI.apiGet(`/mine/${mineId}/calculation-sample`).catch(() => null),
      ]);
      render(mineId, baseline, sample);
      MCI.renderProvenanceStrip(provStrip, baseline.data_provenance);
    } catch (err) {
      MCI.showError(body, err);
    }
  }

  function calcRow(label, formula, result) {
    return `<tr><td>${label}</td><td class="mono">${formula}</td><td class="num">${MCI.formatTonnes(result, 2)} tCO2e</td></tr>`;
  }

  function render(mineId, baseline, sample) {
    const b = baseline.baseline_annual;

    let sampleHTML = `<p class="footnote">Worked-example calculation unavailable.</p>`;
    if (sample && sample.calculation_detail) {
      const d = sample.calculation_detail;
      const a = sample.activity;
      sampleHTML = `
        <table class="data-table">
          <thead><tr><th>Component</th><th>Activity &times; Factor</th><th class="num">Result</th></tr></thead>
          <tbody>
            ${calcRow("Diesel combustion", `${MCI.formatTonnes(a.diesel_consumption_l)} L &times; ${d.factors_used.EF_DIESEL_COMB} kgCO2e/L &divide; 1000`, d.scope1.diesel_combustion_tco2e)}
            ${calcRow("Fugitive methane", `${a.fugitive_methane_t} tCH4 &times; ${d.factors_used.EF_CH4_FUGITIVE} kgCO2e/kgCH4`, d.scope1.fugitive_methane_tco2e)}
            ${calcRow("Grid electricity", `${MCI.formatTonnes(d.scope2.grid_electricity_kwh)} kWh (net of ${MCI.formatPct(d.scope2.renewable_share_applied*100)} renewable) &times; ${d.factors_used.EF_GRID_ELEC} kgCO2e/kWh`, d.scope2.grid_electricity_tco2e)}
            ${calcRow("Road transport", `${MCI.formatTonnes(a.transport_activity_tkm)} tkm &times; ${d.factors_used.EF_ROAD_TRANSPORT} kgCO2e/tkm`, d.scope3.transport_tco2e)}
            ${calcRow("Employee commuting", `${MCI.formatTonnes(a.commute_activity_pkm)} pkm &times; ${d.factors_used.EF_EMPLOYEE_COMMUTE} kgCO2e/pkm`, d.scope3.commute_tco2e)}
          </tbody>
        </table>
        <p class="footnote">Worked example for period ${MCI.formatPeriod(sample.period)}. ${MCI.provenanceBadgeHTML(sample.provenance)} — this activity data is fabricated for prototype demonstration.</p>
      `;
    }

    body.innerHTML = `
      <div class="grid-3">
        <div class="card">
          <div class="kpi-label">Scope 1</div>
          <div class="kpi-value" style="color:var(--scope1)">${MCI.formatTonnes(b.scope1_tco2e)}<span class="unit">tCO2e</span></div>
          <p class="footnote">Direct emissions: diesel combustion in mobile/stationary equipment + fugitive methane (GWP100-converted).</p>
        </div>
        <div class="card">
          <div class="kpi-label">Scope 2</div>
          <div class="kpi-value" style="color:var(--scope2)">${MCI.formatTonnes(b.scope2_tco2e)}<span class="unit">tCO2e</span></div>
          <p class="footnote">Purchased grid electricity, net of any on-site/contracted renewable share.</p>
        </div>
        <div class="card">
          <div class="kpi-label">Scope 3 (Selected)</div>
          <div class="kpi-value" style="color:var(--scope3)">${MCI.formatTonnes(b.scope3_tco2e)}<span class="unit">tCO2e</span></div>
          <p class="footnote">Outbound road transport + employee commuting. Other Scope 3 categories are not yet modeled.</p>
        </div>
      </div>

      <div class="grid-2" style="margin-top:1rem;">
        <div class="card">
          <div class="card-header"><h3>Total Footprint &amp; Intensity</h3></div>
          <table class="data-table">
            <tbody>
              <tr><td>Total footprint (Scope 1 + 2 + 3)</td><td class="num">${MCI.formatTonnes(b.total_tco2e)} tCO2e/yr</td></tr>
              <tr><td>Coal production</td><td class="num">${MCI.formatTonnes(b.coal_production_t)} t/yr</td></tr>
              <tr><td>Carbon intensity</td><td class="num">${b.intensity_tco2e_per_t !== null ? b.intensity_tco2e_per_t.toFixed(4) : "—"} tCO2e/t coal</td></tr>
            </tbody>
          </table>
          <p class="footnote" style="margin-top:0.8rem;">Intensity = Total tCO2e &divide; tonnes coal produced. Enables comparison across mines of different scale.</p>
        </div>
        <div class="card">
          <div class="card-header"><h3>Monthly Scope Breakdown</h3></div>
          <canvas id="stack-chart" height="140"></canvas>
        </div>
      </div>

      <div class="card" style="margin-top:1rem;">
        <div class="card-header"><h3>How This Is Calculated: Activity &times; Emission Factor</h3></div>
        ${sampleHTML}
      </div>
    `;

    const ctx = document.getElementById("stack-chart");
    if (stackChart) stackChart.destroy();
    stackChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: baseline.monthly_trend.map(m => MCI.formatPeriod(m.period)),
        datasets: [
          { label: "Scope 1", data: baseline.monthly_trend.map(m => m.scope1_tco2e), backgroundColor: MCI.SCOPE_COLORS[1] },
          { label: "Scope 2", data: baseline.monthly_trend.map(m => m.scope2_tco2e), backgroundColor: MCI.SCOPE_COLORS[2] },
          { label: "Scope 3", data: baseline.monthly_trend.map(m => m.scope3_tco2e), backgroundColor: MCI.SCOPE_COLORS[3] },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { position: "bottom" } },
        scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, grid: { color: "#2A3134" } } },
      },
    });
  }

  MCI.populateMineSelect(mineSelect, (mineId) => load(mineId));
  load(MCI.getSelectedMine());
})();
