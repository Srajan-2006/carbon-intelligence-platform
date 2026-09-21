(function () {
  const mineId = window.MCI_MINE_ID;
  const body = document.getElementById("od-body");
  const roleBanner = document.getElementById("od-role-banner");
  const addBtn = document.getElementById("add-record-btn");
  const overlay = document.getElementById("record-form-overlay");
  const closeBtn = document.getElementById("record-form-close");
  const form = document.getElementById("record-form");
  const formTitle = document.getElementById("record-form-title");
  const formError = document.getElementById("record-form-error");
  const modeInput = document.getElementById("rf-mode");
  const recordIdInput = document.getElementById("rf-record-id");
  const yearSelect = document.getElementById("rf-year");
  const monthSelect = document.getElementById("rf-month");
  const fieldsEl = document.getElementById("rf-fields");
  const submitBtn = document.getElementById("record-form-submit");

  let currentUser = null;
  let fieldMeta = null;
  let canWrite = false;

  const QUALITY_CLASS = { GOOD: "reference", WARNING: "provisional", INCOMPLETE: "synthetic_prototype" };

  function populateYearSelect() {
    const nowYear = new Date().getFullYear();
    let opts = "";
    for (let y = nowYear + 1; y >= nowYear - 6; y--) opts += `<option value="${y}">${y}</option>`;
    yearSelect.innerHTML = opts;
  }

  function buildFieldInputs() {
    fieldsEl.innerHTML = Object.entries(fieldMeta).map(([key, meta]) => {
      const isPct = key === "renewable_electricity_share";
      const max = isPct ? ` max="100"` : "";
      return `
        <div style="margin-bottom:1em;">
          <label for="rf-${key}">${meta.label}${meta.required ? "" : " (optional)"}</label>
          <div style="display:flex; align-items:center; gap:0.6em;">
            <input id="rf-${key}" type="number" step="any" min="0"${max} ${meta.required ? "required" : ""} style="flex:1;">
            <span class="unit">${meta.unit}</span>
          </div>
        </div>
      `;
    }).join("");
  }

  async function load() {
    MCI.showLoading(body, "operational data");
    try {
      const [meData, dataResp] = await Promise.all([
        MCI.apiGet("/auth/me"),
        MCI.apiGet(`/mine/${mineId}/data`),
      ]);
      currentUser = meData.user;
      fieldMeta = dataResp.field_meta;
      canWrite = currentUser && (currentUser.role === "ADMIN" || (currentUser.role === "MINE_MANAGER" && currentUser.mine_id === mineId));

      buildFieldInputs();
      populateYearSelect();
      renderRoleBanner();
      addBtn.style.display = canWrite ? "inline-block" : "none";
      render(dataResp.records);
    } catch (err) {
      MCI.showError(body, err);
    }
  }

  function renderRoleBanner() {
    roleBanner.style.display = "flex";
    if (canWrite) {
      roleBanner.innerHTML = `<span><strong>Write access:</strong></span><span>You can add and edit monthly operational records for this mine.</span>`;
    } else {
      roleBanner.innerHTML = `<span><strong>Read-only access:</strong></span><span>Your role can view this mine's operational data but not modify it.</span>`;
    }
  }

  function auditTitle(r) {
    const parts = [];
    if (r.created_by_name) parts.push(`Entered by ${r.created_by_name}${r.created_at ? " on " + r.created_at : ""}`);
    else if (r.created_at) parts.push(`Loaded ${r.created_at}`);
    if (r.updated_by_name) parts.push(`Last edited by ${r.updated_by_name}${r.updated_at ? " on " + r.updated_at : ""}`);
    if (!parts.length) return "Original prototype dataset -- no manual entry history for this record.";
    return parts.join(" \u2014 ");
  }

  function render(records) {
    if (!records.length) {
      body.innerHTML = `<div class="card"><div class="empty-text">No monthly operational records yet for ${mineId}.${canWrite ? " Click \u201cAdd Monthly Record\u201d to enter the first one." : ""}</div></div>`;
      return;
    }
    body.innerHTML = `
      <div class="card">
        <table class="data-table">
          <thead>
            <tr>
              <th>Period</th><th class="num">Coal (t)</th><th class="num">Diesel (L)</th>
              <th class="num">Electricity (kWh)</th><th class="num">Renewable %</th>
              <th>Data Status</th><th>Source</th><th></th>
            </tr>
          </thead>
          <tbody>
            ${records.map(r => `
              <tr>
                <td class="mono" title="${auditTitle(r)}">${MCI.formatPeriod(r.period)}</td>
                <td class="num">${r.coal_production_t !== null ? MCI.formatTonnes(r.coal_production_t) : "—"}</td>
                <td class="num">${r.diesel_consumption_l !== null ? MCI.formatTonnes(r.diesel_consumption_l) : "—"}</td>
                <td class="num">${r.electricity_consumption_kwh !== null ? MCI.formatTonnes(r.electricity_consumption_kwh) : "—"}</td>
                <td class="num">${r.renewable_electricity_share_pct !== null ? r.renewable_electricity_share_pct.toFixed(1) + "%" : "—"}</td>
                <td>
                  ${MCI.provenanceBadgeHTML(r.provenance)}
                  <span class="provenance-badge ${QUALITY_CLASS[r.data_quality_status]}" title="${(r.data_quality_reasons || []).join('; ')}">${r.data_quality_status}</span>
                </td>
                <td class="footnote">${r.source_type}</td>
                <td>${canWrite ? `<button type="button" class="btn-secondary edit-record-btn" data-record='${JSON.stringify(r).replace(/'/g, "&apos;")}' style="padding:0.35em 0.8em; font-size:0.7rem;">Edit</button>` : ""}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      <p class="footnote" style="margin-top:0.8rem;">
        Data status reflects completeness/validity only (GOOD / WARNING / INCOMPLETE) — hover a badge for details. It is not a fabricated percentage score.
      </p>
    `;
    body.querySelectorAll(".edit-record-btn").forEach(btn => {
      btn.addEventListener("click", () => openEditForm(JSON.parse(btn.dataset.record.replace(/&apos;/g, "'"))));
    });
  }

  function openCreateForm() {
    form.reset();
    populateYearSelect();
    modeInput.value = "create";
    recordIdInput.value = "";
    formTitle.textContent = "Add Monthly Record";
    formError.hidden = true;
    Object.keys(fieldMeta).forEach(key => { document.getElementById(`rf-${key}`).value = ""; });
    document.getElementById("rf-provenance").value = "measured";
    document.getElementById("rf-source-type").value = "manual_entry";
    document.getElementById("rf-source-note").value = "";
    overlay.style.display = "flex";
  }

  function openEditForm(record) {
    form.reset();
    modeInput.value = "edit";
    recordIdInput.value = record.id;
    formTitle.textContent = `Edit Record — ${MCI.formatPeriod(record.period)}`;
    formError.hidden = true;
    const [y, m] = record.period.split("-");
    if (![...yearSelect.options].some(o => o.value === y)) {
      yearSelect.innerHTML += `<option value="${y}">${y}</option>`;
    }
    yearSelect.value = y;
    monthSelect.value = m;
    Object.keys(fieldMeta).forEach(key => {
      const el = document.getElementById(`rf-${key}`);
      if (key === "renewable_electricity_share") {
        el.value = record.renewable_electricity_share_pct !== null ? record.renewable_electricity_share_pct : "";
      } else {
        el.value = record[key] !== null && record[key] !== undefined ? record[key] : "";
      }
    });
    document.getElementById("rf-provenance").value = record.provenance === "measured" || record.provenance === "provisional" ? record.provenance : "measured";
    document.getElementById("rf-source-type").value = record.source_type || "manual_entry";
    document.getElementById("rf-source-note").value = record.source_note || "";
    overlay.style.display = "flex";
  }

  function closeForm() { overlay.style.display = "none"; }
  addBtn.addEventListener("click", openCreateForm);
  closeBtn.addEventListener("click", closeForm);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeForm(); });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    formError.hidden = true;
    submitBtn.disabled = true;
    submitBtn.textContent = "Saving…";

    const period = `${yearSelect.value}-${monthSelect.value}`;
    const payload = { period };
    Object.keys(fieldMeta).forEach(key => {
      const raw = document.getElementById(`rf-${key}`).value;
      payload[key] = raw === "" ? null : parseFloat(raw);
    });
    payload.provenance = document.getElementById("rf-provenance").value;
    payload.source_type = document.getElementById("rf-source-type").value;
    payload.source_note = document.getElementById("rf-source-note").value;

    try {
      let record;
      if (modeInput.value === "create") {
        const resp = await MCI.apiPost(`/mine/${mineId}/data`, payload);
        record = resp.record;
      } else {
        const recordId = recordIdInput.value;
        const resp = await fetch(`/api/mine/${mineId}/data/${recordId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const json = await resp.json();
        if (!resp.ok) throw new Error(json.error || "Update failed.");
        record = json.record;
      }
      closeForm();
      showSaveConfirmation(record);
      load();
    } catch (err) {
      formError.textContent = err.message || "Save failed.";
      formError.hidden = false;
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Save Record";
    }
  });

  function showSaveConfirmation(record) {
    const el = document.getElementById("od-save-confirmation");
    const calc = record.calculation;
    el.style.display = "block";
    el.innerHTML = `
      <div class="status-banner met" style="margin-bottom:1rem;">
        <span class="dot"></span>Data Saved &mdash; ${MCI.formatPeriod(record.period)}
      </div>
      ${calc ? `
        <div class="card" style="margin-bottom:1rem;">
          <div class="card-header"><h3>Carbon Calculation Updated</h3></div>
          <div class="grid-3">
            <div><div class="kpi-label">Scope 1</div><div class="kpi-value" style="font-size:1.1rem; color:var(--scope1);">${MCI.formatTonnes(calc.scope1_tco2e)} t</div></div>
            <div><div class="kpi-label">Scope 2</div><div class="kpi-value" style="font-size:1.1rem; color:var(--scope2);">${MCI.formatTonnes(calc.scope2_tco2e)} t</div></div>
            <div><div class="kpi-label">Scope 3</div><div class="kpi-value" style="font-size:1.1rem; color:var(--scope3);">${MCI.formatTonnes(calc.scope3_tco2e)} t</div></div>
          </div>
          <div class="grid-2" style="margin-top:0.9rem;">
            <div><div class="kpi-label">Total</div><div class="kpi-value" style="font-size:1.1rem;">${MCI.formatTonnes(calc.total_tco2e)} t</div></div>
            <div><div class="kpi-label">Carbon Intensity</div><div class="kpi-value" style="font-size:1.1rem;">${calc.intensity_tco2e_per_t !== null ? calc.intensity_tco2e_per_t.toFixed(4) : "—"} t/t coal</div></div>
          </div>
          <p class="footnote" style="margin-top:0.8rem;">Calculated by the existing carbon engine from this month's activity data. Dashboard, Carbon Footprint and Hotspot Analysis for this mine now reflect this update.</p>
        </div>
      ` : `<p class="footnote">Carbon calculation updated for this reporting period.</p>`}
    `;
  }

  load();
})();
