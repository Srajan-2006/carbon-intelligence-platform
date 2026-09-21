(function () {
  MCI.applyChartDefaults();
  const mineSelect = document.getElementById("mine-select");
  const body = document.getElementById("simulator-body");
  let interventions = [];
  let baseline = null;
  let simChart = null;
  let debounceTimer = null;

  async function init(mineId) {
    MCI.showLoading(body, "intervention library");
    try {
      const [interventionsData, baselineData] = await Promise.all([
        MCI.apiGet("/interventions"),
        MCI.apiGet(`/mine/${mineId}/baseline`),
      ]);
      interventions = interventionsData.interventions;
      baseline = baselineData.baseline_annual;
      renderShell(mineId);
      runSimulation(mineId);
    } catch (err) {
      MCI.showError(body, err);
    }
  }

  function renderShell(mineId) {
    body.innerHTML = `
      <div class="grid-2">
        <div class="card">
          <div class="card-header"><h3>Deployment Levels</h3></div>
          <div id="sliders"></div>
        </div>
        <div class="card">
          <div class="card-header"><h3>Modeled Result</h3></div>
          <div id="sim-kpis" class="kpi-grid" style="grid-template-columns:repeat(2,1fr);"></div>
          <canvas id="sim-chart" height="150"></canvas>
          <div id="sim-effects" style="margin-top:0.9rem;"></div>
        </div>
      </div>
    `;
    const slidersEl = document.getElementById("sliders");
    slidersEl.innerHTML = interventions.map(i => `
      <div class="slider-row">
        <label for="slider-${i.intervention_id}" style="margin:0;">${i.name}${i.has_interaction ? ' <span class="footnote" style="color:var(--scope2);">(S1/S2 interaction)</span>' : ''}</label>
        <input type="range" id="slider-${i.intervention_id}" data-id="${i.intervention_id}"
               min="0" max="${i.max_deployment}" step="${i.deployment_step}" value="0"
               aria-label="Deployment level for ${i.name}">
        <span class="mono" id="value-${i.intervention_id}" style="width:3.4em;text-align:right;">0%</span>
      </div>
    `).join("");

    slidersEl.querySelectorAll("input[type=range]").forEach(slider => {
      slider.addEventListener("input", () => {
        document.getElementById(`value-${slider.dataset.id}`).textContent = Math.round(parseFloat(slider.value) * 100) + "%";
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => runSimulation(mineId), 180);
      });
    });
  }

  async function runSimulation(mineId) {
    const deployments = {};
    interventions.forEach(i => {
      const el = document.getElementById(`slider-${i.intervention_id}`);
      deployments[i.intervention_id] = el ? parseFloat(el.value) : 0;
    });

    const kpiEl = document.getElementById("sim-kpis");
    try {
      const result = await MCI.apiPost("/simulate", { mine_id: mineId, deployments });
      renderResult(result);
    } catch (err) {
      MCI.showError(kpiEl, err);
    }
  }

  function renderResult(result) {
    const kpiEl = document.getElementById("sim-kpis");
    const s = result.simulated_scopes;
    const b = result.baseline_scopes;

    kpiEl.innerHTML = `
      <div class="kpi-card">
        <div class="kpi-label">Investment</div>
        <div class="kpi-value">${MCI.formatINRCompact(result.investment_inr)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Reduction</div>
        <div class="kpi-value">${MCI.formatPct(result.reduction_pct)}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">CO2e Avoided</div>
        <div class="kpi-value">${MCI.formatTonnes(result.co2e_avoided_t)}<span class="unit">t</span></div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Residual Emissions</div>
        <div class="kpi-value">${MCI.formatTonnes(result.residual_emissions_t)}<span class="unit">t</span></div>
      </div>
    `;

    const effectsEl = document.getElementById("sim-effects");
    const active = result.intervention_effects.filter(e => e.deployment_level > 0);
    effectsEl.innerHTML = active.length ? `
      <table class="data-table">
        <thead><tr><th>Intervention</th><th class="num">S1 Effect</th><th class="num">S2 Effect</th><th class="num">S3 Effect</th></tr></thead>
        <tbody>
          ${active.map(e => `<tr><td>${e.name}</td><td class="num">${MCI.formatTonnes(e.scope1_effect_t)}</td><td class="num">${MCI.formatTonnes(e.scope2_effect_t)}</td><td class="num">${MCI.formatTonnes(e.scope3_effect_t)}</td></tr>`).join("")}
        </tbody>
      </table>
      <p class="footnote">${result.disclaimer}</p>
    ` : `<p class="footnote">Move a slider to see the modeled effect. ${result.disclaimer}</p>`;

    const ctx = document.getElementById("sim-chart");
    if (simChart) simChart.destroy();
    simChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: ["Scope 1", "Scope 2", "Scope 3"],
        datasets: [
          { label: "Baseline", data: [b.scope1_tco2e, b.scope2_tco2e, b.scope3_tco2e], backgroundColor: "#5A6468" },
          { label: "Simulated", data: [s.scope1_tco2e, s.scope2_tco2e, s.scope3_tco2e], backgroundColor: "#5B9BB8" },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { position: "bottom" } },
        scales: { y: { grid: { color: "#2A3134" }, title: { display: true, text: "tCO2e" } }, x: { grid: { display: false } } },
      },
    });
  }

  MCI.populateMineSelect(mineSelect, (mineId) => init(mineId));
  init(MCI.getSelectedMine());
})();
