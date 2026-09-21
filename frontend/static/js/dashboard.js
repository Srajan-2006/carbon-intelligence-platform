(function () {
  MCI.applyChartDefaults();

  const mineSelect = document.getElementById("mine-select");
  const metaEl = document.getElementById("cmd-header-meta");
  const body = document.getElementById("cmd-body");
  const provStrip = document.getElementById("provenance-strip");

  let trendChart = null;

  // Default decision-intelligence scenario -- matches the platform's
  // documented demo scenario (₹10 crore budget, 30% target). Configurable
  // scenarios live on the full Optimizer page; this is a sensible default so
  // the command center answers "can we hit target?" within seconds of load.
  const DEFAULT_BUDGET_INR = 100_000_000;
  const DEFAULT_TARGET_PCT = 30;

  function countUp(el, endValue, decimals, suffix) {
    const duration = 700;
    const start = performance.now();
    const startValue = 0;
    function frame(now) {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const current = startValue + (endValue - startValue) * eased;
      el.textContent = current.toLocaleString("en-IN", { maximumFractionDigits: decimals, minimumFractionDigits: decimals }) + (suffix || "");
      if (t < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  function impactTag(pct) {
    if (pct >= 30) return '<span class="impact-tag high">High Impact</span>';
    if (pct >= 10) return '<span class="impact-tag medium">Medium Impact</span>';
    return '<span class="impact-tag low">Lower Impact</span>';
  }

  async function load(mineId) {
    MCI.showLoading(body, "command center data");
    try {
      const [baseline, hotspots, roadmapData, meData] = await Promise.all([
        MCI.apiGet(`/mine/${mineId}/baseline`),
        MCI.apiGet(`/mine/${mineId}/hotspots`),
        MCI.apiGet(`/mine/${mineId}/roadmap`).catch(() => ({ roadmap: [] })),
        MCI.apiGet(`/auth/me`).catch(() => ({ user: null })),
      ]);

      metaEl.innerHTML = `Selected mine: <strong style="color:var(--ink);">${baseline.mine.mine_name} (${baseline.mine.mine_id})</strong> &middot; ${baseline.mine.mine_type} &middot; ${baseline.mine.state} &middot; ${MCI.formatTonnes(baseline.mine.annual_production_t)} t/yr rated production`;
      MCI.renderProvenanceStrip(provStrip, baseline.data_provenance);

      renderSkeleton();
      renderHeroKpis(baseline.baseline_annual);
      renderTrend(baseline.monthly_trend);
      renderScopeIntelligence(baseline.baseline_annual);
      renderHotspots(hotspots.hotspots);
      renderRoadmapPreview(roadmapData.roadmap);
      renderQuickActions(mineId);

      // Decision Intelligence: run the live optimizer with the default
      // scenario. This is a real backend call, not a hardcoded result.
      runDecisionIntelligence(mineId, baseline.baseline_annual, hotspots.hotspots);
    } catch (err) {
      MCI.showError(body, err);
    }
  }

  function renderSkeleton() {
    body.innerHTML = `
      <div id="hero-kpi-grid" class="hero-kpi-grid"></div>

      <div class="cmd-section-title"><span class="cmd-section-num">01</span>Emissions Trend &amp; Scope Breakdown</div>
      <div class="dash-analytics-grid">
        <div class="card"><canvas id="trend-chart" height="90"></canvas></div>
        <div class="card">
          <div id="scope-intel" class="scope-breakdown-list"></div>
        </div>
      </div>

      <div class="grid-2" style="margin-top:1.6rem;">
        <div>
          <div class="cmd-section-title" style="margin-top:0;"><span class="cmd-section-num">02</span>Top Emission Hotspots</div>
          <div class="card">
            <div id="hotspot-intel" class="hotspot-rank-list"></div>
            <a class="footnote" href="${window.MCI_URLS.hotspots}" style="display:block;margin-top:0.9rem;">View Full Hotspot Analysis &rarr;</a>
          </div>
        </div>
        <div>
          <div class="cmd-section-title" style="margin-top:0;"><span class="cmd-section-num">03</span>Net-Zero Roadmap Preview</div>
          <div class="card">
            <div id="roadmap-preview" class="roadmap-preview-list"></div>
            <a class="footnote" href="${window.MCI_URLS.roadmap}" style="display:block;margin-top:0.9rem;">View Full Roadmap &rarr;</a>
          </div>
        </div>
      </div>

      <div class="cmd-section-title"><span class="cmd-section-num">04</span>Decarbonization Target</div>
      <div id="decarb-target-card" class="decarb-target-card">
        <div class="loading-text">Computing modeled scenario&hellip;</div>
      </div>

      <div class="cmd-section-title"><span class="cmd-section-num">05</span>Decision Intelligence &middot; What Matters Now</div>
      <div id="decision-summary-strip" class="decision-summary-strip"></div>
      <div id="decision-panel" class="decision-panel">
        <div class="decision-panel-body"><div class="loading-text">Running optimizer for the default scenario (&#8377;10 crore / 30% target)&hellip;</div></div>
      </div>

      <div class="cmd-section-title"><span class="cmd-section-num">06</span>Quick Actions</div>
      <div id="quick-actions" class="quick-actions-grid"></div>
    `;
  }

  function renderHeroKpis(b) {
    const el = document.getElementById("hero-kpi-grid");
    el.innerHTML = `
      <div class="hero-kpi-card">
        <div class="hero-kpi-label">Total Emissions</div>
        <div class="hero-kpi-value"><span id="kpi-total">0</span><span class="unit">tCO2e/yr</span></div>
        <div class="hero-kpi-sub">Scope 1 + 2 + 3 (selected)</div>
      </div>
      <div class="hero-kpi-card">
        <div class="hero-kpi-label">Carbon Intensity</div>
        <div class="hero-kpi-value"><span id="kpi-intensity">0</span><span class="unit">t/t coal</span></div>
        <div class="hero-kpi-sub">${MCI.formatTonnes(b.coal_production_t)} t coal produced</div>
      </div>
      <div class="hero-kpi-card accent-good" id="kpi-reduction-card">
        <div class="hero-kpi-label">Modeled Reduction (Optimizer)</div>
        <div class="hero-kpi-value"><span id="kpi-reduction">&mdash;</span></div>
        <div class="hero-kpi-sub">Default scenario, computed live below</div>
      </div>
      <div class="hero-kpi-card" id="kpi-progress-card">
        <div class="hero-kpi-label">Target Progress</div>
        <div class="hero-kpi-value"><span id="kpi-progress">&mdash;</span></div>
        <div class="hero-kpi-sub">vs. ${DEFAULT_TARGET_PCT}% target</div>
      </div>
    `;
    countUp(document.getElementById("kpi-total"), b.total_tco2e, 0);
    countUp(document.getElementById("kpi-intensity"), b.intensity_tco2e_per_t || 0, 3);
  }

  function renderTrend(monthly) {
    const ctx = document.getElementById("trend-chart");
    if (trendChart) trendChart.destroy();
    trendChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: monthly.map(m => MCI.formatPeriod(m.period)),
        datasets: [
          { label: "Scope 1", data: monthly.map(m => m.scope1_tco2e), borderColor: MCI.SCOPE_COLORS[1], backgroundColor: MCI.SCOPE_COLORS[1], tension: 0.15, pointRadius: 2 },
          { label: "Scope 2", data: monthly.map(m => m.scope2_tco2e), borderColor: MCI.SCOPE_COLORS[2], backgroundColor: MCI.SCOPE_COLORS[2], tension: 0.15, pointRadius: 2 },
          { label: "Scope 3", data: monthly.map(m => m.scope3_tco2e), borderColor: MCI.SCOPE_COLORS[3], backgroundColor: MCI.SCOPE_COLORS[3], tension: 0.15, pointRadius: 2 },
          { label: "Total", data: monthly.map(m => m.total_tco2e), borderColor: "#E7ECEA", borderDash: [4, 3], pointRadius: 0, borderWidth: 1.5 },
        ],
      },
      options: {
        responsive: true,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom" }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${MCI.formatTonnes(c.parsed.y)} tCO2e` } } },
        scales: { y: { title: { display: true, text: "tCO2e" }, grid: { color: "#2A3134" } }, x: { grid: { display: false } } },
      },
    });
  }

  function renderScopeIntelligence(b) {
    const el = document.getElementById("scope-intel");
    const total = b.total_tco2e || 1;
    const scopes = [
      { n: 1, label: "Scope 1 — Diesel / Methane", value: b.scope1_tco2e, color: "var(--scope1)" },
      { n: 2, label: "Scope 2 — Purchased Electricity", value: b.scope2_tco2e, color: "var(--scope2)" },
      { n: 3, label: "Scope 3 — Transport / Commuting", value: b.scope3_tco2e, color: "var(--scope3)" },
    ];
    const maxScope = scopes.reduce((a, s) => s.value > a.value ? s : a, scopes[0]);
    el.innerHTML = scopes.map(s => {
      const pct = (s.value / total) * 100;
      const isDominant = s.n === maxScope.n;
      return `
        <div class="scope-bar-row${isDominant ? ' dominant' : ''}">
          <div class="scope-bar-row-head">
            <span class="scope-bar-row-label" style="color:${isDominant ? s.color : 'var(--ink)'};">${s.label}</span>
            <span class="scope-bar-row-value" style="color:${s.color};">${MCI.formatTonnes(s.value)}</span>
          </div>
          <div class="scope-bar-track"><div class="scope-bar-fill" style="width:${pct}%; background:${s.color};"></div></div>
          <div class="scope-bar-row-pct">${MCI.formatPct(pct)} of total footprint</div>
        </div>`;
    }).join("");
  }

  function renderHotspots(hotspots) {
    const el = document.getElementById("hotspot-intel");
    const maxPct = Math.max(...hotspots.map(h => h.pct_of_total), 1);
    el.innerHTML = hotspots.slice(0, 4).map(h => `
      <div class="hotspot-rank-row">
        <div class="hotspot-rank-num">#${String(h.rank).padStart(2, "0")}</div>
        <div>
          <div class="hotspot-rank-name">${h.source}</div>
          <span class="scope-pill s${h.scope}">Scope ${h.scope}</span>
        </div>
        <div class="hotspot-rank-value">${MCI.formatTonnes(h.tco2e)} t<br><span class="footnote">${MCI.formatPct(h.pct_of_total)}</span></div>
        ${impactTag(h.pct_of_total)}
        <div class="hotspot-rank-bar-track"><div class="hotspot-rank-bar-fill" style="width:${(h.pct_of_total / maxPct) * 100}%; background:var(--scope${h.scope});"></div></div>
      </div>
    `).join("");
  }

  function renderRoadmapPreview(roadmap) {
    const el = document.getElementById("roadmap-preview");
    if (!roadmap.length) {
      MCI.showEmpty(el, "No roadmap available for this mine.");
      return;
    }
    el.innerHTML = roadmap.map(m => `
      <div class="roadmap-preview-row">
        <div class="roadmap-preview-year">${m.year}</div>
        <div>${m.milestone}</div>
        <div class="mono" style="font-size:0.78rem; text-align:right;">${MCI.formatPct(m.cumulative_reduction_pct)} cum.</div>
      </div>
    `).join("");
  }

  function renderQuickActions(mineId) {
    const el = document.getElementById("quick-actions");
    const actions = [
      { url: window.MCI_URLS.footprint, label: "View Footprint", sub: "Scope 1/2/3 detail" },
      { url: window.MCI_URLS.hotspots, label: "Analyze Hotspots", sub: "Ranked emission sources" },
      { url: window.MCI_URLS.optimizer, label: "Run Optimizer", sub: "Custom budget & target" },
      { url: window.MCI_URLS.simulator, label: "Simulate Intervention", sub: "Manual scenario testing" },
      { url: window.MCI_URLS.roadmap, label: "View Roadmap", sub: "Full pathway view" },
      { url: `/mine/${mineId}/data`, label: "Manage Data", sub: "Operational records & CSV import" },
    ];
    el.innerHTML = actions.map(a => `
      <a class="quick-action-btn" href="${a.url}">${a.label}<div class="qa-sub">${a.sub}</div></a>
    `).join("");
  }

  async function runDecisionIntelligence(mineId, baseline, hotspotList) {
    const panel = document.getElementById("decision-panel");
    const targetCard = document.getElementById("decarb-target-card");
    try {
      const result = await MCI.apiPost("/optimize", {
        mine_id: mineId, budget_inr: DEFAULT_BUDGET_INR, target_reduction_pct: DEFAULT_TARGET_PCT,
      });
      renderDecarbTargetCard(result);
      renderDecisionSummaryStrip(result, hotspotList);
      renderDecisionPanel(result);
      updateHeroReductionKpis(result);
    } catch (err) {
      const msg = `<div class="empty-text">Could not run the optimizer: ${err.message}. <a href="${window.MCI_URLS.optimizer}">Open the full Optimizer &rarr;</a></div>`;
      targetCard.innerHTML = msg;
      panel.innerHTML = `<div class="decision-panel-body">${msg}</div>`;
    }
  }

  function renderDecarbTargetCard(result) {
    const targetCard = document.getElementById("decarb-target-card");
    const met = result.status === "TARGET_MET";
    const progressPct = Math.min(100, (result.achieved_reduction_pct / result.target_reduction_pct) * 100);
    const fillColor = met ? "var(--good)" : "var(--bad)";
    const statusClass = met ? "met" : "not-feasible";
    const statusLabel = met ? "Target Met" : "Target Not Feasible Within Budget";

    targetCard.innerHTML = `
      <div class="decarb-target-head">
        <div>
          <div class="kpi-label">Target</div>
          <div class="kpi-value" style="font-size:1.3rem;">${MCI.formatPct(result.target_reduction_pct, 0)} reduction &middot; ${MCI.formatINRCompact(result.budget_inr)} budget</div>
        </div>
        <div class="status-banner ${statusClass}" style="margin:0; font-size:0.9rem; padding:0.55rem 0.9rem;"><span class="dot"></span>${statusLabel}</div>
      </div>
      <div class="target-progress-track">
        <div class="target-progress-fill" style="width:${progressPct}%; background:${fillColor};"></div>
      </div>
      <div class="target-progress-labels">
        <span>0%</span>
        <span>${MCI.formatPct(result.achieved_reduction_pct)} modeled reduction</span>
        <span>${MCI.formatPct(result.target_reduction_pct, 0)} target</span>
      </div>
      <p class="decarb-target-scenario" style="margin-top:0.8rem;">Modeled by the decarbonization optimizer against the default scenario. ${met ? "" : `Gap to target: ${MCI.formatPct(result.gap_to_target_pct)}.`} <a href="${window.MCI_URLS.optimizer}">Explore other scenarios &rarr;</a></p>
    `;
  }

  function renderDecisionSummaryStrip(result, hotspotList) {
    const strip = document.getElementById("decision-summary-strip");
    const met = result.status === "TARGET_MET";
    const primaryHotspot = hotspotList && hotspotList.length ? hotspotList[0].source : "—";
    const nextDecision = met
      ? "Review and approve the recommended package"
      : "Increase budget or revise target on the Optimizer page";

    strip.innerHTML = `
      <div class="decision-summary-item ${met ? 'status-good' : 'status-bad'}">
        <div class="decision-summary-label">Target Status</div>
        <div class="decision-summary-value" style="color:${met ? 'var(--good)' : 'var(--bad)'};">${met ? "Target Met" : "Not Feasible"}</div>
      </div>
      <div class="decision-summary-item">
        <div class="decision-summary-label">Modeled Reduction</div>
        <div class="decision-summary-value mono">${MCI.formatPct(result.achieved_reduction_pct)}</div>
      </div>
      <div class="decision-summary-item">
        <div class="decision-summary-label">Primary Hotspot</div>
        <div class="decision-summary-value">${primaryHotspot}</div>
      </div>
      <div class="decision-summary-item">
        <div class="decision-summary-label">Next Decision</div>
        <div class="decision-summary-value" style="font-size:0.82rem;">${nextDecision}</div>
      </div>
    `;
  }

  function updateHeroReductionKpis(result) {
    const reductionEl = document.getElementById("kpi-reduction");
    const progressEl = document.getElementById("kpi-progress");
    const reductionCard = document.getElementById("kpi-reduction-card");
    const progressCard = document.getElementById("kpi-progress-card");
    const met = result.status === "TARGET_MET";

    countUp(reductionEl, result.achieved_reduction_pct, 1, "%");
    const progressPct = Math.min(100, (result.achieved_reduction_pct / DEFAULT_TARGET_PCT) * 100);
    countUp(progressEl, progressPct, 0, "%");

    reductionCard.className = "hero-kpi-card " + (met ? "accent-good" : "accent-warn");
    progressCard.className = "hero-kpi-card " + (met ? "accent-good" : "accent-warn");
  }

  function renderDecisionPanel(result) {
    const panel = document.getElementById("decision-panel");
    const met = result.status === "TARGET_MET";
    const statusClass = met ? "met" : "not-feasible";
    const statusLabel = met ? "Target Met" : "Target Not Feasible Within Budget";

    const packageHTML = result.selected_interventions.length ? `
      <div class="tag-list" style="margin-top:0.8rem;">
        ${result.selected_interventions.map(s => `<span class="scope-pill s${s.has_interaction ? 2 : 1}" style="background:var(--surface-alt); color:var(--ink);">${s.name}</span>`).join("")}
      </div>
    ` : `<p class="footnote" style="margin-top:0.6rem;">No interventions could be deployed within this budget.</p>`;

    panel.innerHTML = `
      <div class="decision-panel-header">
        <div>
          <div class="kpi-label">Recommended Package</div>
          <div style="font-family:var(--font-mono); font-size:0.85rem;">Default scenario &middot; Budget ${MCI.formatINRCompact(result.budget_inr)} &middot; Target ${MCI.formatPct(result.target_reduction_pct, 0)}</div>
        </div>
        <div class="status-banner ${statusClass}" style="margin:0; font-size:0.95rem; padding:0.6rem 1rem;"><span class="dot"></span>${statusLabel}</div>
      </div>
      <div class="decision-panel-body">
        ${packageHTML}
        <div class="grid-3" style="margin-top:1rem;">
          <div><div class="kpi-label">Investment</div><div class="kpi-value" style="font-size:1.15rem;">${MCI.formatINRCompact(result.recommended_investment_inr)}</div></div>
          <div><div class="kpi-label">CO2e Avoided</div><div class="kpi-value" style="font-size:1.15rem;">${MCI.formatTonnes(result.co2e_avoided_t)} t</div></div>
          <div><div class="kpi-label">Cost / tCO2e</div><div class="kpi-value" style="font-size:1.15rem;">${result.cost_per_tco2e_inr !== null ? MCI.formatINR(result.cost_per_tco2e_inr) : "—"}</div></div>
        </div>
        <a class="btn" href="${window.MCI_URLS.optimizer}" style="margin-top:1.2rem; display:inline-block;">Open Full Optimizer &rarr;</a>
      </div>
    `;
  }

  MCI.populateMineSelect(mineSelect, (mineId) => load(mineId));
  load(MCI.getSelectedMine());
})();
