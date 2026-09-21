"""
carbon_engine.py

Pure carbon-accounting logic for the Mine Carbon Intelligence platform.

Design principle: this module has NO Flask/DB imports. It takes plain
dictionaries/numbers in and returns plain dictionaries out, so it can be
unit-tested in isolation and so the backend can call it without coupling
calculation logic to request handling (separation of frontend/backend
AND separation of "business logic" from "web plumbing").

FORMULA (do not change silently -- see project rules):
    Scope 1 (tCO2e) = diesel_litres * EF_DIESEL_COMB(kgCO2e/l) / 1000
                       + fugitive_methane_t * EF_CH4_FUGITIVE(kgCO2e/kgCH4)   [t->kg handled below]
    Scope 2 (tCO2e) = electricity_kwh * (1 - renewable_share) * EF_GRID_ELEC(kgCO2e/kWh) / 1000
    Scope 3 (tCO2e) = transport_tkm * EF_ROAD_TRANSPORT(kgCO2e/tkm) / 1000
                       + commute_pkm * EF_EMPLOYEE_COMMUTE(kgCO2e/pkm) / 1000
    Total   = Scope1 + Scope2 + Scope3
    Intensity (tCO2e/t coal) = Total / coal_production_t
"""

KG_PER_TONNE = 1000.0


def calculate_scope1(diesel_litres, fugitive_methane_t, ef_diesel_kg_per_l, ef_ch4_kg_per_kg):
    """Scope 1: diesel combustion + fugitive methane (GWP100-converted to CO2e)."""
    diesel_tco2e = (diesel_litres * ef_diesel_kg_per_l) / KG_PER_TONNE
    # fugitive_methane_t is tonnes of CH4; ef_ch4 is kgCO2e per kgCH4, so convert t->kg then /1000 back to t
    methane_tco2e = (fugitive_methane_t * KG_PER_TONNE * ef_ch4_kg_per_kg) / KG_PER_TONNE
    detail = {
        "diesel_combustion_tco2e": round(diesel_tco2e, 3),
        "fugitive_methane_tco2e": round(methane_tco2e, 3),
    }
    return round(diesel_tco2e + methane_tco2e, 3), detail


def calculate_scope2(electricity_kwh, renewable_share, ef_grid_kg_per_kwh):
    """Scope 2: purchased-grid-electricity emissions, net of on-site/contracted renewable share."""
    grid_kwh = electricity_kwh * (1.0 - (renewable_share or 0.0))
    scope2_tco2e = (grid_kwh * ef_grid_kg_per_kwh) / KG_PER_TONNE
    detail = {
        "grid_electricity_kwh": round(grid_kwh, 1),
        "renewable_share_applied": renewable_share or 0.0,
        "grid_electricity_tco2e": round(scope2_tco2e, 3),
    }
    return round(scope2_tco2e, 3), detail


def calculate_scope3(transport_tkm, commute_pkm, ef_transport_kg_per_tkm, ef_commute_kg_per_pkm):
    """Selected Scope 3: outbound road transport + employee commuting."""
    transport_tco2e = ((transport_tkm or 0.0) * ef_transport_kg_per_tkm) / KG_PER_TONNE
    commute_tco2e = ((commute_pkm or 0.0) * ef_commute_kg_per_pkm) / KG_PER_TONNE
    detail = {
        "transport_tco2e": round(transport_tco2e, 3),
        "commute_tco2e": round(commute_tco2e, 3),
    }
    return round(transport_tco2e + commute_tco2e, 3), detail


def calculate_intensity(total_tco2e, coal_production_t):
    if not coal_production_t:
        return None
    return round(total_tco2e / coal_production_t, 5)


def calculate_period_footprint(activity, factors):
    """
    activity: dict with keys diesel_consumption_l, fugitive_methane_t,
              electricity_consumption_kwh, renewable_electricity_share,
              transport_activity_tkm, commute_activity_pkm (optional), coal_production_t
    factors: dict keyed by factor_id -> factor_value (kg per unit)

    Returns a dict matching emission_calculations_monthly columns + a
    calc_detail dict for provenance/audit display.
    """
    ef_diesel = factors["EF_DIESEL_COMB"]
    ef_ch4 = factors["EF_CH4_FUGITIVE"]
    ef_grid = factors["EF_GRID_ELEC"]
    ef_transport = factors["EF_ROAD_TRANSPORT"]
    ef_commute = factors["EF_EMPLOYEE_COMMUTE"]

    scope1, s1_detail = calculate_scope1(
        activity.get("diesel_consumption_l", 0.0),
        activity.get("fugitive_methane_t", 0.0),
        ef_diesel, ef_ch4,
    )
    scope2, s2_detail = calculate_scope2(
        activity.get("electricity_consumption_kwh", 0.0),
        activity.get("renewable_electricity_share", 0.0),
        ef_grid,
    )
    scope3, s3_detail = calculate_scope3(
        activity.get("transport_activity_tkm", 0.0),
        activity.get("commute_activity_pkm", 0.0),
        ef_transport, ef_commute,
    )
    total = round(scope1 + scope2 + scope3, 3)
    intensity = calculate_intensity(total, activity.get("coal_production_t"))

    return {
        "scope1_tco2e": scope1,
        "scope2_tco2e": scope2,
        "scope3_tco2e": scope3,
        "total_tco2e": total,
        "intensity_tco2e_per_t": intensity,
        "calc_detail": {
            "scope1": s1_detail,
            "scope2": s2_detail,
            "scope3": s3_detail,
            "factors_used": {
                "EF_DIESEL_COMB": ef_diesel,
                "EF_CH4_FUGITIVE": ef_ch4,
                "EF_GRID_ELEC": ef_grid,
                "EF_ROAD_TRANSPORT": ef_transport,
                "EF_EMPLOYEE_COMMUTE": ef_commute,
            },
        },
    }


def aggregate_annual(monthly_calcs):
    """Sum a list of monthly calculation dicts into an annual totals dict."""
    scope1 = round(sum(m["scope1_tco2e"] for m in monthly_calcs), 3)
    scope2 = round(sum(m["scope2_tco2e"] for m in monthly_calcs), 3)
    scope3 = round(sum(m["scope3_tco2e"] for m in monthly_calcs), 3)
    total = round(scope1 + scope2 + scope3, 3)
    return {"scope1_tco2e": scope1, "scope2_tco2e": scope2, "scope3_tco2e": scope3, "total_tco2e": total}
