# Mine Carbon Intelligence & Decarbonization Decision-Support Platform

A prototype decision-support platform for carbon accounting, emissions hotspot analysis, decarbonization simulation, and investment optimization for coal/open-cast mining operations.

The platform connects emissions measurement to operational hotspots, intervention simulation, budget-constrained optimization, and multi-year roadmap modeling.

## Project Overview

Mine Carbon Intelligence combines:

- Scope 1, Scope 2, and selected Scope 3 emissions calculations
- Carbon-intensity tracking
- Emissions hotspot analysis
- Decarbonization intervention modeling
- Budget-constrained optimization
- Intervention simulation
- Multi-year net-zero roadmap modeling
- Mine and operational-data management
- CSV data import and validation
- Data provenance and quality indicators
- Role-based authentication and mine-level authorization
- Auditability for operational-data changes
- Automated backend and API tests

## Architecture

```text
User
  |
  v
Flask Web Application
  |
  +-- Server-rendered UI
  |   Jinja2 + JavaScript + Chart.js
  |
  +-- REST API
  |   Flask routes
  |
  +-- Business Logic
      |
      +-- Carbon Engine
      |   carbon_engine.py
      |
      +-- Optimizer
          optimizer.py
      |
      v
    SQLite / CSV Data
```

## Carbon Accounting Model

### Scope 1

Direct emissions modeled from diesel combustion and fugitive methane.

### Scope 2

Indirect emissions from purchased electricity, adjusted for modeled renewable electricity share.

### Scope 3

Selected prototype categories currently include road transport and employee commuting.

Scope 3 coverage is partial and should not be interpreted as a complete Scope 3 inventory.

### Carbon Intensity

```text
Carbon Intensity = Total CO2e / Coal Production
```

The modeled emissions calculations are based on activity data and configured emission factors.

## Decarbonization Optimizer

The optimizer evaluates discrete intervention deployment levels and searches for a minimum-cost combination that satisfies a requested emissions-reduction target within a specified budget.

The prototype includes modeled interventions such as:

- Electric haul trucks
- Renewable electricity
- Energy-efficiency measures
- Methane-related interventions
- Other operational decarbonization measures

The model accounts for interactions between interventions. For example, electrifying haul trucks can reduce Scope 1 diesel emissions while increasing electricity demand in Scope 2.

Optimizer outputs include:

- Feasibility status
- Recommended investment
- Modeled emissions reduction
- CO2e avoided
- Residual emissions
- Cost per tCO2e avoided
- Selected interventions

These are model outputs based on prototype assumptions, not guarantees of real-world project performance.

## Intervention Simulator

The simulator allows intervention assumptions to be adjusted and produces modeled emissions outcomes for scenario exploration.

Simulation results depend on baseline activity data, emission factors, intervention assumptions, deployment levels, and interaction effects.

## Net-Zero Roadmap

The roadmap module provides a multi-year modeled emissions-reduction pathway including baseline emissions, cumulative reduction, residual emissions, and year-by-year trajectory.

Roadmap outputs are planning scenarios and do not represent a verified corporate net-zero commitment.

## Mine and Operational Data Management

The platform supports structured onboarding of mine data.

### Mine Management

Authorized users can create and edit mines, view mine details, assign mine managers, and manage mine status and operational attributes.

### Monthly Operational Data

The system stores monthly operational inputs used by the carbon engine, including relevant diesel, electricity, coal production, renewable electricity share, methane, road transport, and commuting activity.

Validation prevents invalid values and duplicate monthly records.

## CSV Import

The CSV workflow is:

```text
Upload -> Parse -> Validate -> Preview -> Confirm -> Import -> Recalculate -> Result
```

Validation includes required headers, missing values, invalid dates, invalid numbers, negative activity values, duplicate periods, and schema mismatches.

Failed imports are rejected without partially corrupting the operational dataset.

## Data Provenance and Quality

The platform distinguishes prototype and operational data using provenance states such as:

- synthetic_prototype
- provisional
- measured

Data-quality checks can identify missing required activity fields, incomplete monthly coverage, continuity issues, and missing source information.

Quality states include:

- GOOD
- WARNING
- INCOMPLETE

Prototype results must not be interpreted as independently verified mine emissions.

## Auditability

Operational records support user attribution for data changes where available.

The system tracks who created a record, who last updated it, and relevant timestamps.

Legacy synthetic records are not assigned fabricated historical attribution.

## Authentication and Authorization

The application includes role-based authentication with the following roles:

- ADMIN
- MINE_MANAGER
- ANALYST

The authorization model supports session-based authentication, password hashing, mine-scoped access, protected API routes, and cross-mine access restrictions.

Passwords are not stored in plaintext.

## User Interface

Primary modules include:

1. Command Center
2. Carbon Footprint
3. Hotspot Analysis
4. Decarbonization Optimizer
5. Intervention Simulator
6. Net-Zero Roadmap
7. Data & Methodology
8. Mine Management
9. Operational Data
10. CSV Import

The interface uses Chart.js for visualization and keeps calculation logic in the backend.

## Technology Stack

- Python
- Flask
- SQLite
- Werkzeug password hashing
- HTML / CSS / JavaScript
- Jinja2
- Chart.js
- pytest

## Project Structure

```text
carbon-intelligence-platform/
|-- backend/
|   |-- app.py
|   |-- auth.py
|   |-- carbon_engine.py
|   |-- database.py
|   |-- optimizer.py
|   |-- operational_data.py
|   |-- seed_data.py
|   |-- schema.sql
|   `-- ...
|
|-- frontend/
|   |-- templates/
|   `-- static/
|       |-- css/
|       `-- js/
|
|-- data/
|-- tests/
|-- README.md
|-- requirements.txt
`-- .gitignore
```

## Installation

### Requirements

- Python 3.10+
- pip
- Windows, Linux, or macOS

### Clone

```bash
git clone https://github.com/Srajan-2006/carbon-intelligence-platform.git
cd carbon-intelligence-platform
```

### Create Virtual Environment

Windows PowerShell:

```powershell
python -m venv venv
venv\Scripts\activate
```

### Install Dependencies

```bash
python -m pip install -r requirements.txt
```

## Running the Application

From the project root with the virtual environment activated:

```bash
python backend/app.py
```

Open the local development address shown by Flask.

## Prototype Data

Example demonstration mines include PM001, PM002, and PM003.

These records are intended for software testing, UI demonstration, API testing, optimization demonstrations, and development workflows.

They should not be presented as verified emissions data from real mines.

## Testing

The Phase 6H checkpoint contains 187 automated tests covering the major backend and data-management workflows.

Run the complete test suite with:

```bash
python -m pytest -q
```

The suite covers carbon-engine calculations, optimizer behavior, APIs, authentication, authorization, migrations, mine management, operational data, CSV import, data quality, and auditability.

## API Overview

Representative endpoints include:

```text
GET  /api/health
GET  /api/mines
GET  /api/mine/<id>/baseline
GET  /api/mine/<id>/hotspots
GET  /api/interventions
POST /api/optimize
POST /api/simulate
GET  /api/mine/<id>/roadmap
GET  /api/emission-factors
GET  /api/mine/<id>/calculation-sample
```

Authentication endpoints include:

```text
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
```

## Security Considerations

This is a development and research prototype.

Before production deployment, additional hardening would be required, including production secret management, HTTPS, CSRF protection, secure cookie configuration, rate limiting, centralized logging, database backup and recovery, stronger password policies, production database infrastructure, formal security testing, and deployment isolation.

The repository does not contain production credentials.

## Research and Production Path

Potential next steps include:

1. Connect measured mine activity data
2. Establish documented emission-factor sources
3. Add factor versioning
4. Expand Scope 3 coverage
5. Add uncertainty analysis
6. Add sensitivity analysis
7. Validate intervention assumptions against engineering studies
8. Integrate renewable-energy and electricity data
9. Add fleet and equipment telemetry
10. Add stronger financial modeling
11. Add approval workflows
12. Introduce production-grade database infrastructure
13. Add external audit and export capabilities
14. Validate results against recognized GHG-accounting methodologies

## Limitations

The current system is a prototype.

Important limitations include:

- Demonstration data is synthetic or provisional
- Scope 3 coverage is partial
- Emission factors are not yet a complete production factor library
- Intervention assumptions are modeled
- Financial results are scenario outputs rather than investment advice
- Roadmap outputs are planning scenarios
- Modeled reductions require engineering and operational validation before real-world use

## Project Status

Current milestone: **Phase 6H - Auditability Checkpoint**

The project currently includes carbon accounting, hotspot analysis, decarbonization optimization, intervention simulation, net-zero roadmap modeling, mine management, operational data entry, CSV import, data provenance, data-quality checks, authentication, authorization, auditability, and automated testing.

## License

License information can be added here before public distribution.

## Author

**Srajan**

Mine Carbon Intelligence / Carbon Intelligence and Decarbonization Decision-Support Platform
