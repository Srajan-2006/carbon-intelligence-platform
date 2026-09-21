(function () {
  const mineId = window.MCI_MINE_ID;
  const roleBanner = document.getElementById("ci-role-banner");
  const uploadForm = document.getElementById("upload-form");
  const fileInput = document.getElementById("ci-file-input");
  const validateBtn = document.getElementById("ci-validate-btn");
  const uploadError = document.getElementById("ci-upload-error");
  const previewSection = document.getElementById("ci-preview-section");
  const summaryKpis = document.getElementById("ci-summary-kpis");
  const previewTable = document.getElementById("ci-preview-table");
  const confirmStatus = document.getElementById("ci-confirm-status");
  const confirmBtn = document.getElementById("ci-confirm-btn");
  const cancelBtn = document.getElementById("ci-cancel-btn");
  const resultSection = document.getElementById("ci-result-section");
  const resultBody = document.getElementById("ci-result-body");

  let selectedFile = null;
  let currentUser = null;
  let canWrite = false;

  async function init() {
    try {
      const me = await MCI.apiGet("/auth/me");
      currentUser = me.user;
      canWrite = currentUser && (currentUser.role === "ADMIN" || (currentUser.role === "MINE_MANAGER" && currentUser.mine_id === mineId));
      roleBanner.style.display = "flex";
      if (canWrite) {
        roleBanner.innerHTML = `<span><strong>Write access:</strong></span><span>You can import CSV data for this mine.</span>`;
      } else {
        roleBanner.innerHTML = `<span><strong>Read-only access:</strong></span><span>Your role cannot import data. Contact an administrator or the assigned mine manager.</span>`;
        validateBtn.disabled = true;
        fileInput.disabled = true;
      }
    } catch (err) {
      // fall through, server-side auth still enforced on actual submit
    }
  }

  async function uploadFile(mode, file) {
    const formData = new FormData();
    formData.append("file", file);
    const resp = await fetch(`/api/mine/${mineId}/data/import/${mode}`, {
      method: "POST",
      body: formData,
    });
    const json = await resp.json();
    if (!resp.ok) {
      const err = new Error(json.error || "Request failed.");
      err.body = json;
      throw err;
    }
    return json;
  }

  uploadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    uploadError.hidden = true;
    resultSection.style.display = "none";
    const file = fileInput.files[0];
    if (!file) {
      uploadError.textContent = "Choose a CSV file first.";
      uploadError.hidden = false;
      return;
    }
    selectedFile = file;
    validateBtn.disabled = true;
    validateBtn.textContent = "Validating…";
    try {
      const report = await uploadFile("preview", file);
      renderPreview(report);
    } catch (err) {
      uploadError.textContent = err.message;
      uploadError.hidden = false;
      previewSection.style.display = "none";
    } finally {
      validateBtn.disabled = false;
      validateBtn.textContent = "Upload & Validate";
    }
  });

  function renderPreview(report) {
    previewSection.style.display = "block";
    summaryKpis.innerHTML = `
      <div class="kpi-card"><div class="kpi-label">Total Rows</div><div class="kpi-value">${report.total_rows}</div></div>
      <div class="kpi-card"><div class="kpi-label">Valid Rows</div><div class="kpi-value" style="color:var(--good);">${report.valid_rows}</div></div>
      <div class="kpi-card"><div class="kpi-label">Invalid Rows</div><div class="kpi-value" style="color:var(--bad);">${report.invalid_rows}</div></div>
      <div class="kpi-card"><div class="kpi-label">Rows With Warnings</div><div class="kpi-value" style="color:var(--warn);">${report.warning_rows}</div></div>
    `;


    previewTable.innerHTML = `
      <table class="data-table">
        <thead><tr><th>Row</th><th>Period</th><th>Status</th><th>Detail</th></tr></thead>
        <tbody>
          ${report.rows.map(r => `
            <tr>
              <td>${r.row}</td>
              <td class="mono">${r.period || "—"}</td>
              <td>${r.status === "valid"
                ? `<span class="provenance-badge reference">Valid</span>`
                : `<span class="provenance-badge provisional" style="color:var(--bad); background:var(--bad-bg);">Error</span>`}</td>
              <td class="footnote">${r.error || (r.warnings && r.warnings.length ? r.warnings.join("; ") : "No issues")}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;

    if (report.can_import && canWrite) {
      confirmStatus.innerHTML = `<p style="margin:0; color:var(--good);">All rows are valid. Nothing has been imported yet — click Confirm Import to write these ${report.valid_rows} row(s) to the database.</p>`;
      confirmBtn.disabled = false;
    } else if (!canWrite) {
      confirmStatus.innerHTML = `<p style="margin:0; color:var(--bad);">Your role does not have permission to import data.</p>`;
      confirmBtn.disabled = true;
    } else {
      confirmStatus.innerHTML = `<p style="margin:0; color:var(--bad);">${report.invalid_rows} row(s) failed validation. Fix the errors above and re-upload — zero rows will be imported until every row is valid.</p>`;
      confirmBtn.disabled = true;
    }
  }

  confirmBtn.addEventListener("click", async () => {
    if (!selectedFile) return;
    confirmBtn.disabled = true;
    confirmBtn.textContent = "Importing…";
    try {
      const result = await uploadFile("confirm", selectedFile);
      previewSection.style.display = "none";
      resultSection.style.display = "block";
      resultBody.innerHTML = `
        <table class="data-table">
          <tbody>
            <tr><td>Rows imported</td><td class="num">${result.rows_imported}</td></tr>
            <tr><td>Emission calculations updated</td><td class="num">${result.calculations_updated}</td></tr>
            <tr><td>Periods</td><td class="num">${result.periods_imported.join(", ")}</td></tr>
          </tbody>
        </table>
        ${result.calculations && result.calculations.length ? `
          <div style="margin-top:1rem;">
            <h3 style="margin-bottom:0.6rem;">Calculated Emissions Per Period</h3>
            <table class="data-table">
              <thead><tr><th>Period</th><th class="num">Scope 1 (t)</th><th class="num">Scope 2 (t)</th><th class="num">Scope 3 (t)</th><th class="num">Total (t)</th><th class="num">Intensity (t/t coal)</th></tr></thead>
              <tbody>
                ${result.calculations.map(c => `
                  <tr>
                    <td class="mono">${MCI.formatPeriod(c.period)}</td>
                    <td class="num" style="color:var(--scope1);">${MCI.formatTonnes(c.scope1_tco2e, 2)}</td>
                    <td class="num" style="color:var(--scope2);">${MCI.formatTonnes(c.scope2_tco2e, 2)}</td>
                    <td class="num" style="color:var(--scope3);">${MCI.formatTonnes(c.scope3_tco2e, 2)}</td>
                    <td class="num">${MCI.formatTonnes(c.total_tco2e, 2)}</td>
                    <td class="num">${c.intensity_tco2e_per_t !== null && c.intensity_tco2e_per_t !== undefined ? c.intensity_tco2e_per_t.toFixed(4) : "—"}</td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        ` : ""}
        <p class="footnote" style="margin-top:0.8rem;">Recalculated via the existing carbon engine — the dashboard, hotspots, simulator and optimizer for this mine now reflect this data automatically.</p>
        <a class="btn" href="/mine/${mineId}/data" style="display:inline-block; margin-top:0.8rem;">View Operational Data &rarr;</a>
      `;
    } catch (err) {
      confirmStatus.innerHTML = `<p style="margin:0; color:var(--bad);">Import failed: ${err.message}</p>`;
    } finally {
      confirmBtn.disabled = false;
      confirmBtn.textContent = "Confirm Import";
    }
  });

  cancelBtn.addEventListener("click", () => {
    previewSection.style.display = "none";
    selectedFile = null;
    fileInput.value = "";
  });

  init();
})();
