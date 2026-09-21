# SIH1644 — Mine Carbon Intelligence & Decarbonization Platform

## 1. Project Overview

A decision-support platform for Indian coal mines, built for Smart India Hackathon
problem statement SIH1644.

The platform does more than report a carbon footprint. Given a mine, an investment
budget, and a desired CO2 reduction target, it determines a **feasible,
cost-effective combination of decarbonization interventions** — or, if the target
cannot be met within budget, reports exactly why and by how much it falls short.

Core workflow: **Measure → Diagnose → Simulate → Optimize → Roadmap**

Central product message: *"We don't just calculate a mine's carbon footprint. We
help the mine decide what to do next — given its current emissions, available
budget and desired reduction target, the platform identifies a feasible and
cost-effective decarbonization pathway and explains the reasoning behind it."*

Seven pages behind authenticated access — Command Center (Executive Dashboard),
Carbon Footprint, Hotspot Analysis, Decarbonization Optimizer (hero feature),
Intervention Simulator, Net-Zero Roadmap, and Data & Methodology — plus
registration/login for role- and mine-scoped access.

## 2. Architecture

```
USER
  │
  ▼
AUTH — Flask sessions, Werkzeug password hashing (backend/auth.py)
  │      Protects pages + mine-scoped API routes; ADMIN/MINE_MANAGER/ANALYST roles.
  ▼
FRONTEND — Flask server-rendered HTML templates + vanilla JS + Chart.js
  │            (frontend/templates, frontend/static)
  │            No carbon-calculation, optimization, or auth logic lives here.
  ▼
REST API — Flask routes (backend/app.py)
  │            Validates input, enforces mine-scoping, calls business logic, shapes JSON.
  ▼
BUSINESS LOGIC
  ├── backend/carbon_engine.py   — Scope 1/2/3 emission calculations (unit-tested, pure functions)
  └── backend/optimizer.py       — exhaustive-search decarbonization optimizer (unit-tested)
  ▼
DATA LAYER — SQLite (data/mine_carbon.db), built from backend/schema.sql
             and seeded deterministically from data/*.csv by backend/seed_data.py.
             users table (backend/auth_schema.sql) is separate and non-destructive:
             reseeding emissions/intervention data never touches registered accounts.
```

Every table and every CSV row carries a `provenance` field
(`reference` / `provisional` / `synthetic_prototype`) so the UI can never present
fabricated data as measured mine data.

### Key modeling rule: Scope 1 / Scope 2 interaction

Electric haul trucks reduce diesel-related Scope 1 emissions but increase
electricity-related Scope 2 emissions (charging demand). The optimizer and
simulator always calculate the **net modeled effect** — Scope 1 reduction and
Scope 2 increase computed jointly — never two independent percentages summed.

## 3. Installation Instructions

Requires **Python 3.10+** (developed and tested on Python 3.12). No database
server is required — SQLite is used via Python's standard library.

```bash
# 1. Unzip the project, then from the project root:
cd SIH1644-CARBON-INTELLIGENCE

# 2. (Recommended) create a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt
```

## 4. Python Requirements

See `requirements.txt`:

```
Flask>=3.1,<4.0
```

`sqlite3` is used from the Python standard library — no separate install needed.

## 5. Database Seeding Command

The ZIP already includes a pre-seeded `data/mine_carbon.db` so the app runs
immediately. To rebuild it from scratch at any time (deterministic and
repeatable — it drops and recreates the database from `backend/schema.sql` and
reloads every CSV in `data/`):

```bash
python backend/seed_data.py
```

This also re-validates that database row counts match the source CSVs and that
every provenance value is valid, before printing a summary of rows loaded.

## 6. How to Start Flask

From the project root:

```bash
python backend/app.py
```

You should see Flask's startup banner confirming the server is running.

## 7. Local URL

```
http://localhost:5055/
```

(The app binds to all interfaces on port 5055; use `http://127.0.0.1:5055/` if
`localhost` does not resolve on your machine.)

## 8. Test Command

Four independent test suites — carbon engine, optimizer, API, and
authentication/authorization — run with plain Python (no pytest dependency
required):

```bash
python tests/test_carbon_engine.py
python tests/test_optimizer.py
python tests/test_api.py
python tests/test_auth.py
```

All 52 tests should pass (8 + 5 + 17 + 22). Both `test_api.py` and
`test_auth.py` re-seed the database automatically before running, so either
can be run independently of step 5.

## 9. Demo Scenario

**All pages except `/login` and `/register` require signing in.** Use the demo
accounts from section 11 below, or register your own.

The built-in default demo, ready to run on the **Decarbonization Optimizer**
page:

| Input              | Value        |
|---------------------|--------------|
| Mine                | PM001        |
| Investment budget   | ₹10 crore    |
| Target reduction    | 30%          |

Suggested 2–3 minute walkthrough:

1. **Sign in** as the demo Mine Manager or Analyst (mine-scoped to PM001), or
   the demo Admin (sees all mines).
2. **Command Center** — the redesigned Executive Dashboard: hero KPIs (total
   emissions, carbon intensity, modeled reduction, target progress), the
   emissions trend chart, Scope 1/2/3 intelligence, ranked hotspots, a
   **Decision Intelligence** panel that runs the live optimizer against the
   default ₹10 crore / 30% scenario, a target-progress bar, a roadmap
   preview, and quick actions — all pulled from the same APIs as every other
   page, nothing hardcoded.
3. **Hotspot Analysis** — see where emissions concentrate in more detail
   (diesel haulage is the largest source).
4. **Decarbonization Optimizer** — enter PM001 / ₹10 crore / 30%, click Optimize.
5. Observe: the optimizer independently computes a minimum-cost feasible package
   (around ₹75–80 lakh, ~30–31% reduction, selecting idle-time reduction,
   telematics, haul-route optimization, and electric haul trucks) — **these
   figures are computed live by the backend on every run, not hard-coded.**
6. Review the before-vs-after Scope 1/2/3 comparison and the electric-haul-truck
   interaction explanation.
7. **Net-Zero Roadmap** — see the same interventions placed on a multi-year pathway.
8. **Data & Methodology** — for technical reviewers, showing the emission-factor
   table, a worked activity × factor calculation, and the provenance/limitations
   disclosure described below.

To see the optimizer correctly report infeasibility (never a false success),
try an unrealistically small budget (e.g. ₹5,000) or an unrealistically high
target (e.g. 95%) — it will return `TARGET_NOT_FEASIBLE_WITHIN_BUDGET` with the
best achievable reduction and the remaining gap.

To see mine-level authorization in action: sign in as the demo Mine Manager
(scoped to PM001) and try changing the URL to `/api/mine/PM002/baseline` — the
backend returns `403 Forbidden`, not PM002's data. Sign in as the demo Admin
instead and every mine is accessible.

## 10. Authentication & Authorization

### Architecture

Session-based authentication using Flask's signed-cookie sessions and
Werkzeug's password hashing (`backend/auth.py`). No plaintext password is
ever stored — only a salted hash (`scrypt`, Werkzeug's current default).

- **Page routes** (`/`, `/footprint`, `/hotspots`, `/optimizer`, `/simulator`,
  `/roadmap`, `/methodology`) require login; unauthenticated visitors are
  redirected to `/login?next=<original path>`.
- **Mine-scoped API routes** (`/api/mine/<id>/baseline`, `.../hotspots`,
  `.../roadmap`, `.../calculation-sample`, `POST /api/optimize`,
  `POST /api/simulate`) require login AND enforce mine-level authorization —
  see Roles below. Centralized in one helper (`auth.require_mine_access`), not
  duplicated per route.
- **Reference-data API routes** (`/api/mines`, `/api/interventions`,
  `/api/emission-factors`, `/api/health`) stay public/unauthenticated: they
  contain no user-sensitive information and `/api/mines` is needed to
  populate the registration form before a user has an account.

### Roles

| Role           | Mine access                          | Typical use                          |
|----------------|---------------------------------------|----------------------------------------|
| `ADMIN`        | All prototype mines                   | System-wide oversight (dev-seeded only, not self-registrable) |
| `MINE_MANAGER` | Their one assigned mine only          | Mine-level decision-making             |
| `ANALYST`      | Their one assigned mine only          | Analysis, simulation, optimization for their mine |

Self-registration (`/register`, `POST /api/auth/register`) only ever accepts
`MINE_MANAGER` or `ANALYST` — the role field is validated server-side against
an allowlist, so a user cannot grant themselves `ADMIN` by editing the request
body. `ADMIN` accounts are provisioned only via the development seed script
below.

A `MINE_MANAGER`/`ANALYST` cannot access another mine's data by changing a
`mine_id` in a URL or request body — the backend checks this on every
mine-scoped request regardless of what the frontend shows, returning `403`.

### Development / Demo Account Setup

```bash
python backend/create_demo_users.py
```

Creates three throwaway accounts (`admin@demo.mci.local`,
`manager@demo.mci.local` / PM001, `analyst@demo.mci.local` / PM001) with
randomly generated passwords **printed once to the terminal** — never
hardcoded in source, never logged to a file. Safe to re-run: existing demo
accounts are left untouched, not overwritten or duplicated.

For a live presentation where you want memorable, deterministic passwords,
set environment variables before running it once:

```bash
MCI_DEMO_ADMIN_PASSWORD=... MCI_DEMO_MANAGER_PASSWORD=... MCI_DEMO_ANALYST_PASSWORD=... \
  python backend/create_demo_users.py
```

To reset demo accounts, delete their rows from the `users` table directly
(`sqlite3 data/mine_carbon.db "DELETE FROM users WHERE email LIKE '%@demo.mci.local';"`)
and re-run the script.

### Security Limitations (Prototype)

This is prototype-grade security, appropriate for an SIH demonstration, **not
production-hardened identity management**:

- The Flask `secret_key` falls back to a randomly generated, locally
  persisted file (`data/.flask_secret_key`) if the `FLASK_SECRET_KEY`
  environment variable isn't set. Fine for a single-machine demo; set the
  environment variable explicitly for anything beyond that.
- No CSRF token is implemented. The app's auth endpoints are JSON-only
  (fetch-based, not classic HTML `<form>` POSTs), which meaningfully reduces
  classic CSRF risk, but a dedicated CSRF token is the more complete
  mitigation and is not yet present.
- No rate limiting on login attempts (no brute-force throttling).
- No password reset / email verification flow.
- No HTTPS enforcement at the application layer (expected to be handled by a
  reverse proxy in any real deployment).
- Session cookies are `HttpOnly` and `SameSite=Lax`, but not marked `Secure`
  (which requires HTTPS to function correctly, out of scope for local demo).

Production deployment would need all of the above addressed, plus a properly
managed secret, before handling real credentials or real mine data.

## 11. Important Synthetic-Data Disclaimer

**This is a prototype. All mine-level operational data (PM001, PM002, PM003) is
synthetic prototype data, fabricated to demonstrate the platform's architecture
and decision-support workflow. It is not a measurement of any real coal mine.**

Every table and API response carries an explicit `provenance` value:

- **`reference`** — verified/authoritative (e.g. published national emission
  factors such as the IPCC default diesel-combustion factor).
- **`provisional`** — plausible, partially sourced, not independently verified.
- **`synthetic_prototype`** — fabricated for this prototype only.

Intervention costs, deployment bounds, and impact fractions are illustrative
assumptions, not engineering-validated figures. Scope 3 coverage is partial
(road transport and employee commuting only). The optimizer uses exhaustive
search appropriate to this prototype's scale (a handful of interventions, a
few discrete deployment levels each) rather than production-grade mathematical
programming. **No number in this application should be presented as a
guarantee of real-world savings.** Production deployment would require
replacing the synthetic operational-data layer with verified mine data,
meters, and engineering studies, while retaining the carbon engine,
intervention model, optimizer, and UI architecture unchanged.

**This prototype uses synthetic/provisional data for demonstration.
Production deployment requires verified mine operational data, validated
intervention assumptions, secure identity management, and appropriate
engineering/MRV validation.** The architecture — carbon engine, intervention
model, optimizer, roadmap, and now authentication — is designed so verified
mine data and hardened identity management can later replace the prototype
layers without rewriting the decision-support pipeline itself.

---

## Project Structure Reference

```
backend/
  app.py               Flask REST API + page routes + auth wiring (no calculation logic)
  auth.py               Authentication/authorization: hashing, sessions, decorators, mine-scoping
  auth_schema.sql        Non-destructive `users` table schema (never dropped by reseeding)
  carbon_engine.py       Scope 1/2/3 emission calculations (unit-tested)
  create_demo_users.py    Development/demo account seed script (hashed, not hardcoded)
  database.py            SQLite connection helper (FK enforcement ON for normal operation)
  optimizer.py             Decarbonization optimizer — exhaustive search (unit-tested)
  schema.sql                Emissions/intervention schema (rebuilt deterministically on reseed)
  seed_data.py               Deterministic, repeatable database seeding + validation;
                              preserves the users table across reseeds
data/
  *.csv                  Source data (mine master, operations, emission factors,
                          interventions, roadmap, KPI library) — all provenance-tagged
  mine_carbon.db          Pre-seeded SQLite database (regenerate with seed_data.py)
  .flask_secret_key        Dev-only generated session secret (see Security Limitations)
frontend/
  templates/              9 Jinja2 templates: base.html shell + 7 app pages + login/register
  static/css/               style.css (design token system) + auth.css (auth pages)
  static/js/                  common.js (shared API/formatting/mine-scoping helpers),
                               auth.js (login/register forms), one script per app page
tests/
  test_carbon_engine.py    8 tests
  test_optimizer.py         5 tests
  test_api.py                17 tests (incl. auth-protection checks on existing endpoints)
  test_auth.py                 22 tests (registration, login, sessions, roles, mine
                                authorization, reseed-survival)
requirements.txt
README.md
```
