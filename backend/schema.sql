-- SIH1644 Mine Carbon Intelligence & Decarbonization Platform
-- Database Schema
--
-- PROVENANCE MODEL
-- Every substantive row carries a provenance tag so the UI can never present
-- synthetic prototype data as measured mine data:
--   'reference'          verified / authoritative (e.g. published emission factors)
--   'provisional'        plausible, partially sourced, not fully verified
--   'synthetic_prototype' fabricated for demonstration purposes only

-- NOTE: foreign_keys enforcement is controlled by the connecting code
-- (backend/database.py for normal app operation; backend/seed_data.py around
-- the destructive rebuild below), not by this script. A `PRAGMA foreign_keys
-- = ON;` statement used to live here, but since this script is re-run via
-- executescript() on every reseed, it was silently re-enabling FK
-- enforcement mid-script and breaking reseeds on a database that already
-- has a `users` table with a live FK to mine_master.

DROP TABLE IF EXISTS kpi_library;
DROP TABLE IF EXISTS net_zero_roadmap;
DROP TABLE IF EXISTS optimizer_runs;
DROP TABLE IF EXISTS optimizer_selected_interventions;
DROP TABLE IF EXISTS interventions;
DROP TABLE IF EXISTS emission_calculations_monthly;
DROP TABLE IF EXISTS emission_factors;
DROP TABLE IF EXISTS operations_monthly;
DROP TABLE IF EXISTS mine_master;

-- ============================================================
-- MINE MASTER
-- ============================================================
CREATE TABLE mine_master (
    mine_id             TEXT PRIMARY KEY,
    mine_name           TEXT NOT NULL,
    company             TEXT,
    state               TEXT,
    mine_type           TEXT,              -- opencast / underground
    annual_production_t REAL,              -- tonnes coal/year (reference year)
    provenance          TEXT NOT NULL CHECK (provenance IN ('reference','provisional','synthetic_prototype')),
    notes               TEXT,
    is_active           INTEGER NOT NULL DEFAULT 1,   -- Phase 6: mine management status
    created_by          INTEGER,                       -- Phase 6: users.id of creator, NULL for seeded prototype mines
    created_at          TEXT DEFAULT (datetime('now'))  -- Phase 6: lightweight audit field
);

-- ============================================================
-- OPERATIONS MONTHLY (activity data)
-- ============================================================
CREATE TABLE operations_monthly (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    mine_id                 TEXT NOT NULL REFERENCES mine_master(mine_id),
    period                  TEXT NOT NULL,      -- 'YYYY-MM'
    coal_production_t       REAL,                -- tonnes this month
    diesel_consumption_l    REAL,                -- litres
    electricity_consumption_kwh REAL,             -- kWh
    renewable_electricity_share REAL,             -- 0-1, fraction of electricity from renewables
    transport_activity_tkm  REAL,                -- tonne-km road transport (Scope 3 slice)
    commute_activity_pkm    REAL,                -- passenger-km employee commuting (Scope 3 slice)
    fugitive_methane_t      REAL,                -- tonnes CH4 (if applicable/modelled)
    -- Phase 6 adds 'measured' (user-entered/imported operational data claimed
    -- accurate but not independently verified) and 'verified' (reserved for
    -- data that has actually been checked against source records -- never
    -- assigned automatically by CSV import or manual entry).
    provenance              TEXT NOT NULL CHECK (
        provenance IN ('reference','provisional','synthetic_prototype','measured','verified')
    ),
    source_type             TEXT DEFAULT 'reference',  -- manual_entry / csv_import / api / sensor / reference
    source_note             TEXT,                       -- Phase 6: free-text traceability note
    created_by              INTEGER,                     -- Phase 6: users.id, NULL for seeded prototype data
    created_at              TEXT DEFAULT (datetime('now')),
    updated_at              TEXT,
    updated_by              INTEGER,                     -- Phase 6H: users.id of last editor, NULL if never edited
    UNIQUE(mine_id, period)
);

-- ============================================================
-- EMISSION FACTORS
-- ============================================================
CREATE TABLE emission_factors (
    factor_id    TEXT PRIMARY KEY,
    factor_name  TEXT NOT NULL,
    scope        TEXT NOT NULL CHECK (scope IN ('1','2','3')),
    gas          TEXT NOT NULL,             -- CO2e / CH4 etc.
    factor_value REAL NOT NULL,
    unit         TEXT NOT NULL,             -- e.g. kgCO2e/litre, kgCO2e/kWh, kgCO2e/tonne-km
    geography    TEXT,
    source       TEXT,                      -- citation / origin
    provenance   TEXT NOT NULL CHECK (provenance IN ('reference','provisional','synthetic_prototype'))
);

-- ============================================================
-- EMISSION CALCULATIONS MONTHLY (derived, traceable)
-- ============================================================
CREATE TABLE emission_calculations_monthly (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mine_id         TEXT NOT NULL REFERENCES mine_master(mine_id),
    period          TEXT NOT NULL,
    scope1_tco2e    REAL NOT NULL,
    scope2_tco2e    REAL NOT NULL,
    scope3_tco2e    REAL NOT NULL,
    total_tco2e     REAL NOT NULL,
    intensity_tco2e_per_t REAL,             -- total / coal_production_t
    calc_detail_json TEXT,                  -- activity x factor breakdown, for provenance/audit
    provenance      TEXT NOT NULL CHECK (
        provenance IN ('reference','provisional','synthetic_prototype','measured','verified')
    ),
    UNIQUE(mine_id, period)
);

-- ============================================================
-- INTERVENTIONS (library)
-- ============================================================
CREATE TABLE interventions (
    intervention_id      TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    description           TEXT,
    target_scope          TEXT NOT NULL,     -- e.g. '1', '2', '1+2' (interacting)
    control_variable       TEXT NOT NULL,     -- what the deployment % represents
    min_deployment         REAL NOT NULL,     -- fraction 0-1
    max_deployment         REAL NOT NULL,     -- fraction 0-1
    deployment_step         REAL NOT NULL DEFAULT 0.25,
    cost_per_unit_deployment_inr REAL NOT NULL, -- INR cost to move deployment 0 -> 1 (i.e. full rollout cost)
    scope1_reduction_at_full REAL DEFAULT 0,   -- fractional reduction of mine's Scope1 baseline at full (100%) deployment, BEFORE interaction
    scope2_delta_at_full     REAL DEFAULT 0,   -- fractional CHANGE to Scope2 baseline at full deployment (+ increase / - decrease), interaction term
    scope3_reduction_at_full REAL DEFAULT 0,
    has_interaction          INTEGER NOT NULL DEFAULT 0, -- 1 if this intervention has a modeled Scope1/Scope2 interaction
    assumptions               TEXT,
    feasibility_notes          TEXT,
    provenance                TEXT NOT NULL CHECK (provenance IN ('reference','provisional','synthetic_prototype'))
);

-- ============================================================
-- OPTIMIZER RUNS (audit trail of decision-support queries)
-- ============================================================
CREATE TABLE optimizer_runs (
    run_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    mine_id           TEXT NOT NULL REFERENCES mine_master(mine_id),
    budget_inr        REAL NOT NULL,
    target_reduction_pct REAL NOT NULL,
    status            TEXT NOT NULL,          -- TARGET_MET / TARGET_NOT_FEASIBLE_WITHIN_BUDGET
    recommended_investment_inr REAL,
    achieved_reduction_pct REAL,
    co2e_avoided_t     REAL,
    residual_emissions_t REAL,
    cost_per_tco2e_inr  REAL,
    baseline_scope1_t   REAL,
    baseline_scope2_t   REAL,
    baseline_scope3_t   REAL,
    optimized_scope1_t  REAL,
    optimized_scope2_t  REAL,
    optimized_scope3_t  REAL,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE optimizer_selected_interventions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES optimizer_runs(run_id),
    intervention_id TEXT NOT NULL REFERENCES interventions(intervention_id),
    deployment_level REAL NOT NULL,
    investment_inr    REAL NOT NULL,
    scope1_effect_t    REAL,
    scope2_effect_t    REAL,
    scope3_effect_t    REAL,
    reason              TEXT
);

-- ============================================================
-- NET-ZERO ROADMAP (planning horizon)
-- ============================================================
CREATE TABLE net_zero_roadmap (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    mine_id              TEXT NOT NULL REFERENCES mine_master(mine_id),
    year                 INTEGER NOT NULL,
    milestone            TEXT NOT NULL,
    intervention_summary  TEXT,
    investment_inr        REAL,
    expected_reduction_pct REAL,      -- incremental, this milestone
    cumulative_reduction_pct REAL,
    remaining_emissions_t  REAL,
    provenance             TEXT NOT NULL CHECK (provenance IN ('reference','provisional','synthetic_prototype'))
);

-- ============================================================
-- KPI LIBRARY (decision-supporting metrics only)
-- ============================================================
CREATE TABLE kpi_library (
    kpi_id       TEXT PRIMARY KEY,
    kpi_name     TEXT NOT NULL,
    description  TEXT,
    unit         TEXT,
    decision_support_purpose TEXT   -- why this KPI matters for a decision
);
