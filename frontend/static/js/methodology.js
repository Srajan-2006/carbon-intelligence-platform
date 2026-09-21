(function () {
  const legendEl = document.getElementById("provenance-legend");
  const factorsEl = document.getElementById("factors-table");
  const calcEl = document.getElementById("calc-sample");
  const interventionsEl = document.getElementById("interventions-table");

  legendEl.innerHTML = `
    <table class="data-table">
      <tbody>
        <tr><td>${MCI.provenanceBadgeHTML("reference")}</td><td>Verified / authoritative (e.g. published national emission factors).</td></tr>
        <tr><td>${MCI.provenanceBadgeHTML("provisional")}</td><td>Plausible, partially sourced, not fully independently verified.</td></tr>
        <tr><td>${MCI.provenanceBadgeHTML("synthetic_prototype")}</td><td>Fabricated for prototype demonstration only — never presented as a real measurement.</td></tr>
      </tbody>
    </table>
  `;

  MCI.apiGet("/emission-factors").then(data => {
    factorsEl.innerHTML = `
      <table class="data-table">
        <thead><tr><th>Factor</th><th>Scope</th><th class="num">Value</th><th>Unit</th><th>Provenance</th><th>Source</th></tr></thead>
        <tbody>
          ${data.emission_factors.map(f => `
            <tr>
              <td>${f.factor_name}</td>
              <td><span class="scope-pill s${f.scope}">Scope ${f.scope}</span></td>
              <td class="num">${f.factor_value}</td>
              <td class="mono" style="font-size:0.78rem;">${f.unit}</td>
              <td>${MCI.provenanceBadgeHTML(f.provenance)}</td>
              <td class="footnote" style="max-width:280px;">${f.source}</td>
            </tr>`).join("")}
        </tbody>
      </table>
    `;
  }).catch(err => MCI.showError(factorsEl, err));

  MCI.apiGet("/mine/PM001/calculation-sample").then(sample => {
    const d = sample.calculation_detail;
    const a = sample.activity;
    if (!d) { MCI.showEmpty(calcEl, "Sample calculation unavailable."); return; }
    calcEl.innerHTML = `
      <p class="footnote">PM001, period ${MCI.formatPeriod(sample.period)} — ${MCI.provenanceBadgeHTML(sample.provenance)}</p>
      <table class="data-table">
        <thead><tr><th>Component</th><th>Activity</th><th>Factor</th><th class="num">Result (tCO2e)</th></tr></thead>
        <tbody>
          <tr><td>Diesel combustion</td><td class="mono">${MCI.formatTonnes(a.diesel_consumption_l)} L</td><td class="mono">${d.factors_used.EF_DIESEL_COMB} kgCO2e/L</td><td class="num">${MCI.formatTonnes(d.scope1.diesel_combustion_tco2e, 2)}</td></tr>
          <tr><td>Fugitive methane</td><td class="mono">${a.fugitive_methane_t} tCH4</td><td class="mono">${d.factors_used.EF_CH4_FUGITIVE} kgCO2e/kgCH4</td><td class="num">${MCI.formatTonnes(d.scope1.fugitive_methane_tco2e, 2)}</td></tr>
          <tr><td>Grid electricity</td><td class="mono">${MCI.formatTonnes(d.scope2.grid_electricity_kwh)} kWh net</td><td class="mono">${d.factors_used.EF_GRID_ELEC} kgCO2e/kWh</td><td class="num">${MCI.formatTonnes(d.scope2.grid_electricity_tco2e, 2)}</td></tr>
          <tr><td>Road transport</td><td class="mono">${MCI.formatTonnes(a.transport_activity_tkm)} tkm</td><td class="mono">${d.factors_used.EF_ROAD_TRANSPORT} kgCO2e/tkm</td><td class="num">${MCI.formatTonnes(d.scope3.transport_tco2e, 2)}</td></tr>
          <tr><td>Employee commuting</td><td class="mono">${MCI.formatTonnes(a.commute_activity_pkm)} pkm</td><td class="mono">${d.factors_used.EF_EMPLOYEE_COMMUTE} kgCO2e/pkm</td><td class="num">${MCI.formatTonnes(d.scope3.commute_tco2e, 2)}</td></tr>
          <tr><td><strong>Total</strong></td><td></td><td></td><td class="num"><strong>${MCI.formatTonnes(sample.result.total_tco2e, 2)}</strong></td></tr>
        </tbody>
      </table>
    `;
  }).catch(err => MCI.showError(calcEl, err));

  MCI.apiGet("/interventions").then(data => {
    interventionsEl.innerHTML = `
      <table class="data-table">
        <thead><tr><th>Intervention</th><th>Scope</th><th class="num">Cost (full deployment)</th><th>Provenance</th><th>Assumptions</th></tr></thead>
        <tbody>
          ${data.interventions.map(i => `
            <tr>
              <td>${i.name}${i.has_interaction ? ' <span class="footnote" style="color:var(--scope2);">(S1/S2 interaction)</span>' : ''}</td>
              <td>Scope ${i.target_scope}</td>
              <td class="num">${MCI.formatINRCompact(i.cost_per_unit_deployment_inr)}</td>
              <td>${MCI.provenanceBadgeHTML(i.provenance)}</td>
              <td class="footnote" style="max-width:340px;">${i.assumptions}</td>
            </tr>`).join("")}
        </tbody>
      </table>
    `;
  }).catch(err => MCI.showError(interventionsEl, err));
})();
