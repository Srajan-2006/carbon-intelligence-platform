/* ============================================================
   common.js
   Shared API access, formatting, and UI-state helpers.
   Every page-specific script relies on this module instead of
   duplicating fetch logic or number formatting.
   ============================================================ */

const MCI = (function () {

  const API = "/api";

  // ---------------- Core fetch wrappers ----------------

  async function apiGet(path) {
    let resp;
    try {
      resp = await fetch(API + path, { headers: { "Accept": "application/json" } });
    } catch (networkErr) {
      throw new ApiUnavailableError("Could not reach the backend API. Is the Flask server running?");
    }
    return handleResponse(resp);
  }

  async function apiPost(path, body) {
    let resp;
    try {
      resp = await fetch(API + path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(body || {}),
      });
    } catch (networkErr) {
      throw new ApiUnavailableError("Could not reach the backend API. Is the Flask server running?");
    }
    return handleResponse(resp);
  }

  async function handleResponse(resp) {
    let json = null;
    try {
      json = await resp.json();
    } catch (e) {
      // no JSON body
    }
    if (resp.status === 401 && !window.location.pathname.startsWith("/login") && !window.location.pathname.startsWith("/register")) {
      window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
      throw new ApiRequestError("Session expired. Redirecting to sign in.", 401, json);
    }
    if (!resp.ok) {
      const msg = (json && json.error) ? json.error : `Request failed (HTTP ${resp.status})`;
      throw new ApiRequestError(msg, resp.status, json);
    }
    return json;
  }

  class ApiRequestError extends Error {
    constructor(message, status, body) {
      super(message);
      this.name = "ApiRequestError";
      this.status = status;
      this.body = body;
    }
  }
  class ApiUnavailableError extends Error {
    constructor(message) {
      super(message);
      this.name = "ApiUnavailableError";
    }
  }

  // ---------------- Formatting ----------------

  function formatINR(value) {
    if (value === null || value === undefined || isNaN(value)) return "—";
    const n = Number(value);
    const sign = n < 0 ? "-" : "";
    const abs = Math.abs(n);
    return sign + "\u20B9" + abs.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  }

  function formatINRCompact(value) {
    if (value === null || value === undefined || isNaN(value)) return "—";
    const n = Number(value);
    const abs = Math.abs(n);
    if (abs >= 1e7) return (n / 1e7).toFixed(2) + " Cr";
    if (abs >= 1e5) return (n / 1e5).toFixed(2) + " L";
    return formatINR(n);
  }

  function formatTonnes(value, decimals) {
    if (value === null || value === undefined || isNaN(value)) return "—";
    const d = decimals === undefined ? 0 : decimals;
    return Number(value).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
  }

  function formatPct(value, decimals) {
    if (value === null || value === undefined || isNaN(value)) return "—";
    const d = decimals === undefined ? 1 : decimals;
    return Number(value).toFixed(d) + "%";
  }

  function formatPeriod(period) {
    // 'YYYY-MM' -> 'Jan 2025'
    if (!period) return "";
    const [y, m] = period.split("-");
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const idx = parseInt(m, 10) - 1;
    return (months[idx] || m) + " " + y;
  }

  // ---------------- Provenance ----------------

  const PROVENANCE_LABELS = {
    reference: "Reference / Verified",
    provisional: "Provisional",
    synthetic_prototype: "Synthetic Prototype",
  };

  function provenanceBadgeHTML(value) {
    const label = PROVENANCE_LABELS[value] || value;
    const cls = value || "synthetic_prototype";
    return `<span class="provenance-badge ${cls}">${label}</span>`;
  }

  function renderProvenanceStrip(el, provenanceValues, extraText) {
    if (!el) return;
    const values = Array.isArray(provenanceValues) ? provenanceValues : [provenanceValues];
    const badges = values.map(provenanceBadgeHTML).join(" ");
    el.innerHTML = `
      <span><strong>Data status:</strong></span>
      ${badges}
      <span>${extraText || "This dataset is fabricated for prototype demonstration and is explicitly labelled — it is not measured mine data. See Data &amp; Methodology for details."}</span>
    `;
  }

  // ---------------- UI state helpers ----------------

  function showLoading(el, message) {
    if (!el) return;
    el.innerHTML = `<div class="loading-text">Loading${message ? " " + message : ""}&hellip;</div>`;
  }

  function showEmpty(el, message) {
    if (!el) return;
    el.innerHTML = `<div class="empty-text">${message || "No data available."}</div>`;
  }

  function showError(el, err) {
    if (!el) return;
    const message = (err && err.message) ? err.message : "Something went wrong loading this data.";
    el.innerHTML = `
      <div class="status-banner not-feasible" style="font-size:0.95rem; text-transform:none; letter-spacing:normal;">
        <span class="dot"></span>
        <span>${message}</span>
      </div>`;
  }

  // ---------------- Mine selection (persisted across pages) ----------------

  function getSelectedMine() {
    return localStorage.getItem("mci_selected_mine") || "PM001";
  }
  function setSelectedMine(mineId) {
    localStorage.setItem("mci_selected_mine", mineId);
  }

  async function populateMineSelect(selectEl, onChange) {
    if (!selectEl) return;
    try {
      const [minesData, meData] = await Promise.all([apiGet("/mines"), apiGet("/auth/me")]);
      const me = meData ? meData.user : null;
      let mines = minesData.mines;

      // Mine-scoping in the UI mirrors the backend's enforcement: ADMIN sees
      // every prototype mine, MINE_MANAGER/ANALYST only ever see their own
      // assigned mine (the backend rejects any other mine_id regardless, but
      // showing only the authorized option avoids a confusing 403 in normal use).
      if (me && me.role !== "ADMIN" && me.mine_id) {
        mines = mines.filter(m => m.mine_id === me.mine_id);
        setSelectedMine(me.mine_id);
      }

      const selected = getSelectedMine();
      selectEl.innerHTML = mines.map(m =>
        `<option value="${m.mine_id}" ${m.mine_id === selected ? "selected" : ""}>${m.mine_id} — ${m.mine_name}</option>`
      ).join("");
      if (mines.length && !mines.some(m => m.mine_id === selected)) {
        setSelectedMine(mines[0].mine_id);
        selectEl.value = mines[0].mine_id;
      }
      selectEl.disabled = mines.length <= 1;

      selectEl.addEventListener("change", () => {
        setSelectedMine(selectEl.value);
        if (onChange) onChange(selectEl.value);
      });
    } catch (err) {
      selectEl.innerHTML = `<option value="PM001">PM001</option>`;
    }
  }

  // ---------------- Chart.js shared defaults ----------------

  function applyChartDefaults() {
    if (typeof Chart === "undefined") return;
    Chart.defaults.font.family = "'IBM Plex Mono', monospace";
    Chart.defaults.font.size = 11;
    Chart.defaults.color = "#9AA6A1";
    Chart.defaults.borderColor = "#2A3134";
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.boxWidth = 8;
  }

  const SCOPE_COLORS = { 1: "#D97A4A", 2: "#5B9BB8", 3: "#C7A06A" };

  return {
    apiGet, apiPost, ApiRequestError, ApiUnavailableError,
    formatINR, formatINRCompact, formatTonnes, formatPct, formatPeriod,
    provenanceBadgeHTML, renderProvenanceStrip,
    showLoading, showEmpty, showError,
    getSelectedMine, setSelectedMine, populateMineSelect,
    applyChartDefaults, SCOPE_COLORS,
  };
})();
