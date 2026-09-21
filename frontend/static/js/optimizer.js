(function () {
  MCI.applyChartDefaults();
  const mineSelect = document.getElementById("opt-mine");
  const form = document.getElementById("optimizer-form");
  const budgetInput = document.getElementById("opt-budget");
  const targetInput = document.getElementById("opt-target");
  const budgetReadable = document.getElementById("opt-budget-readable");
  const submitBtn = document.getElementById("opt-submit");
  const resultEl = document.getElementById("optimizer-result");
  let compareChart = null;

  function updateBudgetReadable() {
    const v = parseFloat(budgetInput.value);
    budgetReadable.textContent = isNaN(v) ? "" : `= ${MCI.formatINRCompact(v)}  (default demo: PM001, ₹10 crore, 30% target)`;
  }
  budgetInput.addEventListener("input", updateBudgetReadable);
  updateBudgetReadable();

  MCI.populateMineSelect(mineSelect);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const mineId = mineSelect.value || MCI.getSelectedMine();
    const budget = parseFloat(budgetInput.value);
    const target = parseFloat(targetInput.value);

    submitBtn.disabled = true;
    submitBtn.textContent = "Optimizing…";
    MCI.showLoading(resultEl, "feasible intervention combinations — this runs a real search over the intervention library");

    try {
      const result = await MCI.apiPost("/optimize", { mine_id: mineId, budget_inr: budget, target_reduction_pct: target });
      render(result);
    } catch (err) {
      MCI.showError(resultEl, err);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Optimize";
    }
  });

  function interventionRow(s, idx) {
    const interactionNote = s.has_interaction
      ? `<div class="footnote" style="color:var(--scope2);margin-top:0.3em;">Net effect: Scope 1 &darr; ${MCI.formatTonnes(-s.scope1_effect_t)} t, Scope 2 &uarr; ${MCI.formatTonnes(s.scope2_effect_t)} t (interaction modeled jointly)</div>`
      : "";
    return `
      <div class="intervention-card">
        <div class="name"><span class="opt-intervention-num">#${String(idx + 1).padStart(2, "0")}</span>${s.name}</div>
        <div class="meta">Deployment: ${MCI.formatPct(s.deployment_level * 100, 0)} &middot; Investment: ${MCI.formatINR(s.investment_inr)} (${MCI.formatINRCompact(s.investment_inr)})</div>
        <div class="meta" style="margin-top:0.4em;">
          Scope 1 effect: ${MCI.formatTonnes(s.scope1_effect_t)} t &middot;
          Scope 2 effect: ${MCI.formatTonnes(s.scope2_effect_t)} t &middot;
          Scope 3 effect: ${MCI.formatTonnes(s.scope3_effect_t)} t
        </div>
        ${interactionNote}
      </div>
    `;
  }

  function scenarioSummaryStrip(result) {
    const met = result.status === "TARGET_MET";
    return `
      <div class="decision-summary-strip">
        <div class="decision-summary-item ${met ? 'status-good' : 'status-bad'}">
          <div class="decision-summary-label">Status</div>
          <div class="decision-summary-value" style="color:${met ? 'var(--good)' : 'var(--bad)'};">${met ? "Target Met" : "Not Feasible"}</div>
        </div>
        <div class="decision-summary-item">
          <div class="decision-summary-label">Mine</div>
          <div class="decision-summary-value mono">${result.mine_id || "—"}</div>
        </div>
        <div class="decision-summary-item">
          <div class="decision-summary-label">Budget</div>
          <div class="decision-summary-value mono">${MCI.formatINRCompact(result.budget_inr)}</div>
        </div>
        <div class="decision-summary-item">
          <div class="decision-summary-label">Target</div>
          <div class="decision-summary-value mono">${MCI.formatPct(result.target_reduction_pct, 0)}</div>
        </div>
      </div>
    `;
  }

  function render(result) {
    const met = result.status === "TARGET_MET";
    const baseline = result.mine_baseline;
    const optimized = result.optimized_scopes;

    const statusHTML = met
      ? `<div class="status-banner met"><span class="dot"></span>Target Met</div>`
      : `<div class="status-banner not-feasible"><span class="dot"></span>Target Not Feasible Within Budget</div>`;

    const gapHTML = met ? "" : `
      <div class="opt-kpi-card accent-bad">
        <div class="opt-kpi-label">Gap To Target</div>
        <div class="opt-kpi-value" style="color:var(--bad)">${MCI.formatPct(result.gap_to_target_pct)}</div>
        <div class="opt-kpi-sub">Shortfall vs. requested target</div>
      </div>`;

    const evInteraction = result.selected_interventions.find(s => s.has_interaction);
    const evExplainHTML = evInteraction ? `
      <div class="explain-box" style="margin-top:1rem;">
        <strong>Electric haul truck interaction:</strong> electrification reduces diesel-related Scope 1 emissions but increases purchased-electricity Scope 2 demand for charging. The figures above are the modeled <em>net</em> effect (Scope 1 avoided minus Scope 2 added) — not two independent percentages added together.
      </div>` : "";

    resultEl.innerHTML = `
      ${statusHTML}
      ${scenarioSummaryStrip(result)}
      <div class="opt-kpi-grid">
        <div class="opt-kpi-card ${met ? 'accent-good' : ''}">
          <div class="opt-kpi-label">Recommended Investment</div>
          <div class="opt-kpi-value">${MCI.formatINRCompact(result.recommended_investment_inr)}</div>
          <div class="opt-kpi-sub">${MCI.formatINR(result.recommended_investment_inr)}</div>
        </div>
        <div class="opt-kpi-card ${met ? 'accent-good' : ''}">
          <div class="opt-kpi-label">Modeled Reduction</div>
          <div class="opt-kpi-value">${MCI.formatPct(result.achieved_reduction_pct)}</div>
          <div class="opt-kpi-sub">Target: ${MCI.formatPct(result.target_reduction_pct, 0)}</div>
        </div>
        <div class="opt-kpi-card">
          <div class="opt-kpi-label">CO2e Avoided</div>
          <div class="opt-kpi-value">${MCI.formatTonnes(result.co2e_avoided_t)}<span class="unit">t</span></div>
        </div>
        <div class="opt-kpi-card">
          <div class="opt-kpi-label">Residual Emissions</div>
          <div class="opt-kpi-value">${MCI.formatTonnes(result.residual_emissions_t)}<span class="unit">t</span></div>
        </div>
        <div class="opt-kpi-card">
          <div class="opt-kpi-label">Cost / tCO2e Reduced</div>
          <div class="opt-kpi-value">${result.cost_per_tco2e_inr !== null ? MCI.formatINR(result.cost_per_tco2e_inr) : "—"}</div>
        </div>
        ${gapHTML}
      </div>

      <div class="grid-2">
        <div class="card">
          <div class="card-header"><h3>Selected Interventions</h3></div>
          <div class="stack">
            ${result.selected_interventions.length ? result.selected_interventions.map(interventionRow).join("") : '<div class="empty-text">No interventions could be deployed within this budget.</div>'}
          </div>
          ${evExplainHTML}
        </div>
        <div class="card">
          <div class="card-header"><h3>Before vs. After (Scope 1 / 2 / 3)</h3></div>
          <canvas id="compare-chart" height="180"></canvas>
          <table class="data-table" style="margin-top:0.8rem;">
            <thead><tr><th></th><th class="num">Baseline</th><th class="num">Optimized</th></tr></thead>
            <tbody>
              <tr><td><span class="scope-pill s1">Scope 1</span></td><td class="num">${MCI.formatTonnes(baseline.scope1_tco2e)}</td><td class="num">${MCI.formatTonnes(optimized.scope1_tco2e)}</td></tr>
              <tr><td><span class="scope-pill s2">Scope 2</span></td><td class="num">${MCI.formatTonnes(baseline.scope2_tco2e)}</td><td class="num">${MCI.formatTonnes(optimized.scope2_tco2e)}</td></tr>
              <tr><td><span class="scope-pill s3">Scope 3</span></td><td class="num">${MCI.formatTonnes(baseline.scope3_tco2e)}</td><td class="num">${MCI.formatTonnes(optimized.scope3_tco2e)}</td></tr>
              <tr><td><strong>Total</strong></td><td class="num"><strong>${MCI.formatTonnes(baseline.total_tco2e)}</strong></td><td class="num"><strong>${MCI.formatTonnes(optimized.total_tco2e)}</strong></td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card" style="margin-top:1rem;">
        <div class="card-header"><h3>Why This Package</h3></div>
        <p>${result.explanation}</p>
        <p class="footnote">${MCI.provenanceBadgeHTML((result.data_provenance || ["synthetic_prototype"])[0])} Modeled result under prototype assumptions — investment and impact figures are illustrative, not a guarantee of real-world savings. Optimizer run #${result.run_id}, logged for audit.</p>
      </div>
    `;

    const ctx = document.getElementById("compare-chart");
    if (compareChart) compareChart.destroy();
    compareChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: ["Scope 1", "Scope 2", "Scope 3"],
        datasets: [
          { label: "Baseline", data: [baseline.scope1_tco2e, baseline.scope2_tco2e, baseline.scope3_tco2e], backgroundColor: "#5A6468" },
          { label: "Optimized", data: [optimized.scope1_tco2e, optimized.scope2_tco2e, optimized.scope3_tco2e], backgroundColor: "#3FA06E" },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { position: "bottom" } },
        scales: { y: { grid: { color: "#2A3134" }, title: { display: true, text: "tCO2e" } }, x: { grid: { display: false } } },
      },
    });
  }
})();
