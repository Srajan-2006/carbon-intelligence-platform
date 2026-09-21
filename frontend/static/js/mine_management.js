(function () {
  const body = document.getElementById("mm-body");
  const roleBanner = document.getElementById("mm-role-banner");
  const addBtn = document.getElementById("add-mine-btn");
  const overlay = document.getElementById("mine-form-overlay");
  const closeBtn = document.getElementById("mine-form-close");
  const form = document.getElementById("mine-form");
  const formTitle = document.getElementById("mine-form-title");
  const formError = document.getElementById("mine-form-error");
  const modeInput = document.getElementById("mf-mode");
  const mineIdInput = document.getElementById("mf-mine-id");
  const mineIdHint = document.getElementById("mf-mine-id-hint");
  const activeRow = document.getElementById("mf-active-row");
  const submitBtn = document.getElementById("mine-form-submit");

  let currentUser = null;

  function statusBadge(isActive) {
    return isActive
      ? `<span class="provenance-badge reference">Active</span>`
      : `<span class="provenance-badge provisional" style="color:var(--bad); background:var(--bad-bg);">Inactive</span>`;
  }

  function dataStatusBadge(status, count) {
    if (status === "HAS_DATA") {
      return `<span class="footnote" style="color:var(--good);">${count} monthly record${count === 1 ? "" : "s"}</span>`;
    }
    return `<span class="footnote" style="color:var(--ink-faint);">No operational data yet</span>`;
  }

  const QUALITY_CLASS = { GOOD: "reference", WARNING: "provisional", INCOMPLETE: "synthetic_prototype" };

  function qualityBadge(mine) {
    const status = mine.data_quality_status;
    const reasons = (mine.data_quality_reasons || []).join(" \u2014 ");
    const cls = QUALITY_CLASS[status] || "synthetic_prototype";
    return `<span class="provenance-badge ${cls}" title="${reasons.replace(/"/g, '&quot;')}">${status}</span>`;
  }

  function canEdit(mine) {
    if (!currentUser) return false;
    if (currentUser.role === "ADMIN") return true;
    if (currentUser.role === "MINE_MANAGER") return currentUser.mine_id === mine.mine_id;
    return false;
  }

  async function load() {
    MCI.showLoading(body, "mine records");
    try {
      const meData = await MCI.apiGet("/auth/me");
      currentUser = meData.user;

      const data = await MCI.apiGet("/mine-management");
      renderRoleBanner();
      render(data.mines);
    } catch (err) {
      MCI.showError(body, err);
    }
  }

  function renderRoleBanner() {
    roleBanner.style.display = "flex";
    if (currentUser.role === "ADMIN") {
      roleBanner.innerHTML = `<span><strong>Administrator access:</strong></span><span>Viewing all mines. You can create new mines and edit any mine.</span>`;
    } else if (currentUser.role === "MINE_MANAGER") {
      roleBanner.innerHTML = `<span><strong>Mine Manager access:</strong></span><span>You can edit your assigned mine (${currentUser.mine_id}). New mine creation is an administrator action.</span>`;
    } else {
      roleBanner.innerHTML = `<span><strong>Read-only access:</strong></span><span>Analysts can view mine details but cannot create or edit mines.</span>`;
    }
  }

  function accessBadges(mine) {
    if (!mine.assigned_users || !mine.assigned_users.length) {
      return `<span class="footnote" style="color:var(--ink-faint);">Unassigned</span>`;
    }
    return mine.assigned_users.map(u =>
      `<span class="footnote" style="display:block;">${u.name} <span style="color:var(--ink-faint);">(${u.role})</span></span>`
    ).join("");
  }

  function auditTitle(mine) {
    const parts = [];
    if (mine.created_by_name) parts.push(`Created by ${mine.created_by_name}${mine.created_at ? " on " + mine.created_at : ""}`);
    if (mine.updated_by_name) parts.push(`Last updated by ${mine.updated_by_name}${mine.updated_at ? " on " + mine.updated_at : ""}`);
    return parts.join(" \u2014 ");
  }

  function render(mines) {
    if (!mines.length) {
      MCI.showEmpty(body, "No mines accessible to your account yet.");
      return;
    }
    body.innerHTML = `
      <div class="card">
        <table class="data-table">
          <thead>
            <tr>
              <th>Code</th><th>Name</th><th>Location</th><th>Type</th>
              <th>Status</th><th>Identity Data</th><th>Emissions Data</th><th>Data Quality</th><th>Access</th><th></th>
            </tr>
          </thead>
          <tbody>
            ${mines.map(m => `
              <tr>
                <td class="mono">${m.mine_id}</td>
                <td title="${auditTitle(m)}">${m.mine_name}${m.provenance === "synthetic_prototype" ? ' <span class="footnote">(demo)</span>' : ""}</td>
                <td>${m.state || "—"}</td>
                <td>${m.mine_type || "—"}</td>
                <td>${statusBadge(m.is_active)}</td>
                <td>${MCI.provenanceBadgeHTML(m.provenance)}</td>
                <td>${dataStatusBadge(m.data_status, m.record_count)}</td>
                <td>${qualityBadge(m)}</td>
                <td>${accessBadges(m)}</td>
                <td>
                  <a href="/mine/${m.mine_id}/data" class="footnote" style="text-decoration:none; color:var(--scope2); font-weight:600;">Manage Data &rarr;</a>
                  ${canEdit(m) ? ` &middot; <button type="button" class="btn-secondary edit-mine-btn" data-mine='${JSON.stringify(m).replace(/'/g, "&apos;")}' style="padding:0.35em 0.8em; font-size:0.7rem;">Edit</button>` : ""}
                </td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
      <p class="footnote" style="margin-top:0.8rem;">
        ${MCI.provenanceBadgeHTML("synthetic_prototype")} mines (PM001/PM002/PM003) are the original demonstration dataset and remain available for testing.
        Mines you create here start with no operational data -- add monthly records or import a CSV from that mine's page (coming next).
        Access shows which Mine Manager / Analyst accounts are currently assigned to each mine.
      </p>
    `;
    body.querySelectorAll(".edit-mine-btn").forEach(btn => {
      btn.addEventListener("click", () => openEditForm(JSON.parse(btn.dataset.mine.replace(/&apos;/g, "'"))));
    });
  }

  function openCreateForm() {
    form.reset();
    modeInput.value = "create";
    formTitle.textContent = "Add Mine";
    mineIdInput.disabled = false;
    mineIdInput.value = "";
    mineIdHint.style.display = "block";
    activeRow.style.display = "none";
    formError.hidden = true;
    overlay.style.display = "flex";
  }

  function openEditForm(mine) {
    form.reset();
    modeInput.value = "edit";
    formTitle.textContent = `Edit Mine — ${mine.mine_id}`;
    mineIdInput.disabled = true;
    mineIdInput.value = mine.mine_id;
    mineIdHint.style.display = "none";
    document.getElementById("mf-mine-name").value = mine.mine_name || "";
    document.getElementById("mf-state").value = mine.state || "";
    document.getElementById("mf-mine-type").value = mine.mine_type || "";
    document.getElementById("mf-company").value = mine.company || "";
    document.getElementById("mf-production").value = mine.annual_production_t || "";
    document.getElementById("mf-notes").value = mine.notes || "";
    const provSelect = document.getElementById("mf-provenance");
    if ([...provSelect.options].some(o => o.value === mine.provenance)) {
      provSelect.value = mine.provenance;
    }
    document.getElementById("mf-active").checked = !!mine.is_active;
    activeRow.style.display = "block";
    formError.hidden = true;
    overlay.style.display = "flex";
  }

  function closeForm() {
    overlay.style.display = "none";
  }

  if (addBtn) addBtn.addEventListener("click", openCreateForm);
  closeBtn.addEventListener("click", closeForm);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeForm(); });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    formError.hidden = true;
    submitBtn.disabled = true;
    submitBtn.textContent = "Saving…";

    const payload = {
      mine_name: document.getElementById("mf-mine-name").value,
      state: document.getElementById("mf-state").value,
      mine_type: document.getElementById("mf-mine-type").value,
      company: document.getElementById("mf-company").value,
      annual_production_t: document.getElementById("mf-production").value || null,
      provenance: document.getElementById("mf-provenance").value,
      notes: document.getElementById("mf-notes").value,
    };

    try {
      if (modeInput.value === "create") {
        payload.mine_id = mineIdInput.value;
        await MCI.apiPost("/mines", payload);
      } else {
        payload.is_active = document.getElementById("mf-active").checked;
        const mineId = mineIdInput.value;
        const resp = await fetch(`/api/mine/${encodeURIComponent(mineId)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const json = await resp.json();
        if (!resp.ok) throw new Error(json.error || "Update failed.");
      }
      closeForm();
      load();
    } catch (err) {
      formError.textContent = err.message || "Save failed.";
      formError.hidden = false;
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Save Mine";
    }
  });

  load();
})();
