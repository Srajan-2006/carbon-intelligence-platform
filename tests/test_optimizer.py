import sys, os, csv
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import optimizer as opt

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def load_interventions():
    path = os.path.join(DATA_DIR, "interventions.csv")
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "intervention_id": r["intervention_id"],
                "name": r["name"],
                "min_deployment": float(r["min_deployment"]),
                "max_deployment": float(r["max_deployment"]),
                "deployment_step": float(r["deployment_step"]),
                "cost_per_unit_deployment_inr": float(r["cost_per_unit_deployment_inr"]),
                "scope1_reduction_at_full": float(r["scope1_reduction_at_full"]),
                "scope2_delta_at_full": float(r["scope2_delta_at_full"]),
                "scope3_reduction_at_full": float(r["scope3_reduction_at_full"]),
                "has_interaction": r["has_interaction"] == "1",
            })
    return rows


# PM001 annual baseline (derived from operations data, no renewable share applied for this
# specific hand-check to match the design doc's paper derivation)
PM001_BASELINE = {
    "scope1_tco2e": 22440.0,
    "scope2_tco2e": 10740.0,
    "scope3_tco2e": 850.0,
    "total_tco2e": 34030.0,
}


def test_pm001_default_demo_scenario():
    """
    Budget 10 crore, target 30% -- doc says prototype demonstrates ~80 lakh
    investment for ~31% reduction. This must come out of the optimizer's own
    search, not be hard-coded anywhere.
    """
    interventions = load_interventions()
    result = opt.optimize(PM001_BASELINE, interventions, budget_inr=100_000_000, target_reduction_pct=30)

    assert result["status"] == "TARGET_MET", result["status"]
    print("Recommended investment (INR):", result["recommended_investment_inr"])
    print("Achieved reduction %:", result["achieved_reduction_pct"])
    print("Selected interventions:", [s["intervention_id"] for s in result["selected_interventions"]])

    # Should land close to the documented ~80 lakh / ~31% (within reasonable tolerance,
    # since these are described as "approximately" in the project doc)
    assert 7_500_000 <= result["recommended_investment_inr"] <= 8_500_000, result["recommended_investment_inr"]
    assert 30.0 <= result["achieved_reduction_pct"] <= 32.0, result["achieved_reduction_pct"]
    assert result["achieved_reduction_pct"] >= 30.0  # target actually met, not approximated down


def test_infeasible_low_budget_reports_honestly():
    interventions = load_interventions()
    # Absurdly small budget cannot buy any intervention
    result = opt.optimize(PM001_BASELINE, interventions, budget_inr=100, target_reduction_pct=30)
    assert result["status"] == "TARGET_NOT_FEASIBLE_WITHIN_BUDGET"
    assert result["achieved_reduction_pct"] == 0.0
    assert result["gap_to_target_pct"] == 30.0


def test_infeasible_high_target_reports_gap_not_fake_success():
    interventions = load_interventions()
    # Even full budget cannot be expected to hit an unrealistic 95% target
    result = opt.optimize(PM001_BASELINE, interventions, budget_inr=1_000_000_000, target_reduction_pct=95)
    assert result["status"] == "TARGET_NOT_FEASIBLE_WITHIN_BUDGET"
    assert result["achieved_reduction_pct"] < 95.0
    assert "gap_to_target_pct" in result


def test_ev_truck_interaction_shows_both_scope_effects():
    interventions = load_interventions()
    result = opt.optimize(PM001_BASELINE, interventions, budget_inr=100_000_000, target_reduction_pct=30)
    ev = next((s for s in result["selected_interventions"] if s["intervention_id"] == "INT_EV_TRUCKS"), None)
    assert ev is not None, "EV trucks expected in the min-cost package for this scenario"
    assert ev["scope1_effect_t"] < 0  # Scope 1 goes down (negative = reduction)
    assert ev["scope2_effect_t"] > 0  # Scope 2 goes up
    assert ev["has_interaction"] is True


def test_zero_budget_zero_deployment():
    interventions = load_interventions()
    result = opt.optimize(PM001_BASELINE, interventions, budget_inr=0, target_reduction_pct=10)
    assert result["status"] == "TARGET_NOT_FEASIBLE_WITHIN_BUDGET"
    assert result["recommended_investment_inr"] == 0
    assert result["selected_interventions"] == []


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
