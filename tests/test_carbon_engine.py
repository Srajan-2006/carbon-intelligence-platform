import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import carbon_engine as ce

FACTORS = {
    "EF_DIESEL_COMB": 2.68,
    "EF_CH4_FUGITIVE": 25.0,
    "EF_GRID_ELEC": 0.716,
    "EF_ROAD_TRANSPORT": 0.11,
    "EF_EMPLOYEE_COMMUTE": 0.15,
}


def test_scope1_diesel_only():
    scope1, detail = ce.calculate_scope1(1000, 0, FACTORS["EF_DIESEL_COMB"], FACTORS["EF_CH4_FUGITIVE"])
    # 1000 L * 2.68 kg/L = 2680 kg = 2.68 tCO2e
    assert abs(scope1 - 2.68) < 1e-6, scope1


def test_scope1_with_methane():
    scope1, detail = ce.calculate_scope1(0, 1, FACTORS["EF_DIESEL_COMB"], FACTORS["EF_CH4_FUGITIVE"])
    # 1 tCH4 = 1000 kgCH4 * 25 kgCO2e/kgCH4 = 25000 kgCO2e = 25 tCO2e
    assert abs(scope1 - 25.0) < 1e-6, scope1


def test_scope2_no_renewables():
    scope2, detail = ce.calculate_scope2(1000, 0.0, FACTORS["EF_GRID_ELEC"])
    # 1000 kWh * 0.716 kg/kWh = 716 kg = 0.716 t
    assert abs(scope2 - 0.716) < 1e-6, scope2


def test_scope2_with_renewable_share():
    scope2, detail = ce.calculate_scope2(1000, 0.5, FACTORS["EF_GRID_ELEC"])
    # only 500 kWh from grid -> 500*0.716/1000 = 0.358
    assert abs(scope2 - 0.358) < 1e-6, scope2


def test_scope3():
    scope3, detail = ce.calculate_scope3(1000, 500, FACTORS["EF_ROAD_TRANSPORT"], FACTORS["EF_EMPLOYEE_COMMUTE"])
    # transport: 1000*0.11/1000=0.11 ; commute: 500*0.15/1000=0.075 ; total=0.185
    assert abs(scope3 - 0.185) < 1e-6, scope3


def test_intensity():
    assert ce.calculate_intensity(100, 1000) == 0.1
    assert ce.calculate_intensity(100, 0) is None
    assert ce.calculate_intensity(100, None) is None


def test_period_footprint_matches_pm001_annual_design():
    """
    Cross-check against the hand-derived PM001 annual design values used to
    build the demo dataset: diesel 8,000,000 L, elec 15,000,000 kWh (5% renewable),
    methane 40 t, transport 5,000,000 tkm, commute 2,000,000 pkm.
    Expected (from design doc): Scope1=22440, Scope2=10740(ish w/ 5% renewable
    reduces it slightly), Scope3=850.
    """
    activity = {
        "diesel_consumption_l": 8_000_000,
        "fugitive_methane_t": 40,
        "electricity_consumption_kwh": 15_000_000,
        "renewable_electricity_share": 0.0,  # test the pure baseline first
        "transport_activity_tkm": 5_000_000,
        "commute_activity_pkm": 2_000_000,
        "coal_production_t": 1_200_000,
    }
    result = ce.calculate_period_footprint(activity, FACTORS)
    assert abs(result["scope1_tco2e"] - 22440.0) < 1.0, result["scope1_tco2e"]
    assert abs(result["scope2_tco2e"] - 10740.0) < 1.0, result["scope2_tco2e"]
    assert abs(result["scope3_tco2e"] - 850.0) < 1.0, result["scope3_tco2e"]
    assert abs(result["total_tco2e"] - 34030.0) < 2.0, result["total_tco2e"]
    assert result["intensity_tco2e_per_t"] is not None


def test_aggregate_annual():
    monthly = [
        {"scope1_tco2e": 10, "scope2_tco2e": 5, "scope3_tco2e": 1},
        {"scope1_tco2e": 20, "scope2_tco2e": 10, "scope3_tco2e": 2},
    ]
    agg = ce.aggregate_annual(monthly)
    assert agg["scope1_tco2e"] == 30
    assert agg["scope2_tco2e"] == 15
    assert agg["scope3_tco2e"] == 3
    assert agg["total_tco2e"] == 48


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
