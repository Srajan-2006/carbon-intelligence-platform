"""
optimizer.py

The decision-support hero feature.

INPUT:  baseline emissions (Scope1/2/3), a list of candidate interventions,
        an investment budget, and a target reduction percentage.

OUTPUT: the minimum-cost feasible combination of intervention deployment
        levels that meets the target reduction within budget -- or, if no
        combination achieves the target within budget, the best achievable
        package and an explicit infeasibility report.

METHOD: exhaustive search over a small, bounded grid of deployment levels
        per intervention (min_deployment .. max_deployment in deployment_step
        increments). This is appropriate at prototype scale (project scope:
        ~5-8 interventions, few discrete levels each) and guarantees an exact
        minimum-cost answer rather than a heuristic approximation -- this
        matters because the platform must never claim a target is met when
        it is not. At larger scale (many more interventions / continuous
        deployment / additional constraints) this should be replaced with a
        proper MILP formulation (documented in project doc, section 36).

KEY MODELING RULE: an intervention's Scope1 and Scope2 effects are NOT
independent percentages subtracted from the total. Each intervention
declares a fractional effect on the mine's Scope1 baseline and/or a
fractional effect (delta) on the mine's Scope2 baseline. Effects across
selected interventions accumulate additively **within** each scope
(fraction-of-baseline terms, not chained/compounding percentages), and the
net whole-mine effect is only ever read off the resulting Scope1+Scope2+
Scope3 total -- never precomputed as an isolated "% reduction" per
intervention. This is how the Scope1/Scope2 interaction for electric haul
trucks (diesel down, purchased electricity up) is honestly represented.
"""

import itertools


def _deployment_levels(intervention):
    lo = intervention["min_deployment"]
    hi = intervention["max_deployment"]
    step = intervention["deployment_step"] or 0.25
    levels = [0.0]  # "not deployed" is always an option
    level = lo if lo > 0 else step
    while level <= hi + 1e-9:
        levels.append(round(level, 4))
        level += step
    # dedupe, keep within bounds, always include 0
    levels = sorted(set(l for l in levels if l == 0.0 or (lo - 1e-9) <= l <= (hi + 1e-9)))
    return levels


def _apply_combination(baseline, interventions, levels):
    """
    baseline: {'scope1_tco2e':.., 'scope2_tco2e':.., 'scope3_tco2e':.., 'total_tco2e':..}
    interventions: list of intervention dicts (from DB)
    levels: list of deployment level floats, same order as interventions

    Returns (optimized_scope_dict, total_cost_inr, per_intervention_effects)
    """
    scope1_reduction_frac = 0.0
    scope2_delta_frac = 0.0
    scope3_reduction_frac = 0.0
    total_cost = 0.0
    effects = []

    for interv, level in zip(interventions, levels):
        if level <= 0:
            continue
        cost = level * interv["cost_per_unit_deployment_inr"]
        total_cost += cost

        s1_frac = level * (interv.get("scope1_reduction_at_full") or 0.0)
        s2_frac = level * (interv.get("scope2_delta_at_full") or 0.0)
        s3_frac = level * (interv.get("scope3_reduction_at_full") or 0.0)

        scope1_reduction_frac += s1_frac
        scope2_delta_frac += s2_frac
        scope3_reduction_frac += s3_frac

        effects.append({
            "intervention_id": interv["intervention_id"],
            "name": interv["name"],
            "deployment_level": level,
            "investment_inr": round(cost, 2),
            "scope1_effect_t": round(-s1_frac * baseline["scope1_tco2e"], 3),
            "scope2_effect_t": round(s2_frac * baseline["scope2_tco2e"], 3),
            "scope3_effect_t": round(-s3_frac * baseline["scope3_tco2e"], 3),
            "has_interaction": bool(interv.get("has_interaction")),
        })

    # Clamp fractional reductions so a scope can't go below zero (physical bound)
    scope1_reduction_frac = min(scope1_reduction_frac, 1.0)
    scope3_reduction_frac = min(scope3_reduction_frac, 1.0)

    opt_scope1 = max(0.0, baseline["scope1_tco2e"] * (1 - scope1_reduction_frac))
    opt_scope2 = max(0.0, baseline["scope2_tco2e"] * (1 + scope2_delta_frac))
    opt_scope3 = max(0.0, baseline["scope3_tco2e"] * (1 - scope3_reduction_frac))
    opt_total = opt_scope1 + opt_scope2 + opt_scope3

    optimized = {
        "scope1_tco2e": round(opt_scope1, 3),
        "scope2_tco2e": round(opt_scope2, 3),
        "scope3_tco2e": round(opt_scope3, 3),
        "total_tco2e": round(opt_total, 3),
    }
    return optimized, round(total_cost, 2), effects


def optimize(baseline, interventions, budget_inr, target_reduction_pct):
    """
    Exhaustive search for the minimum-cost feasible intervention package.

    Returns a result dict with status TARGET_MET or TARGET_NOT_FEASIBLE_WITHIN_BUDGET,
    plus full explainability detail. Never fabricates a MET status.
    """
    baseline_total = baseline["total_tco2e"]
    target_total_max = baseline_total * (1 - target_reduction_pct / 100.0)

    level_options = [_deployment_levels(i) for i in interventions]

    best_feasible = None  # minimum cost combination that meets target within budget
    best_overall = None   # best reduction achieved anywhere within budget (for infeasible case)

    for combo in itertools.product(*level_options):
        optimized, cost, effects = _apply_combination(baseline, interventions, combo)
        if cost > budget_inr + 1e-6:
            continue  # over budget, not a candidate at all

        reduction_t = baseline_total - optimized["total_tco2e"]
        reduction_pct = (reduction_t / baseline_total * 100.0) if baseline_total else 0.0

        meets_target = optimized["total_tco2e"] <= target_total_max + 1e-6

        if meets_target:
            if best_feasible is None or cost < best_feasible["cost"] or (
                abs(cost - best_feasible["cost"]) < 1e-6 and reduction_pct > best_feasible["reduction_pct"]
            ):
                best_feasible = {
                    "cost": cost,
                    "optimized": optimized,
                    "effects": effects,
                    "reduction_t": reduction_t,
                    "reduction_pct": reduction_pct,
                }

        # Track best achievable reduction within budget regardless of target, for the infeasible-case report
        if best_overall is None or reduction_pct > best_overall["reduction_pct"] or (
            abs(reduction_pct - best_overall["reduction_pct"]) < 1e-9 and cost < best_overall["cost"]
        ):
            best_overall = {
                "cost": cost,
                "optimized": optimized,
                "effects": effects,
                "reduction_t": reduction_t,
                "reduction_pct": reduction_pct,
            }

    if best_feasible is not None:
        chosen = best_feasible
        status = "TARGET_MET"
    else:
        chosen = best_overall
        status = "TARGET_NOT_FEASIBLE_WITHIN_BUDGET"

    if chosen is None:
        # Should not happen (0-deployment combo with cost 0 is always evaluated),
        # but guard rather than silently succeed.
        return {
            "status": "OPTIMIZER_ERROR",
            "message": "No feasible combination could be evaluated.",
        }

    selected = [e for e in chosen["effects"] if e["deployment_level"] > 0]
    residual_t = chosen["optimized"]["total_tco2e"]
    co2e_avoided_t = round(chosen["reduction_t"], 3)
    cost_per_tco2e = round(chosen["cost"] / co2e_avoided_t, 2) if co2e_avoided_t > 0 else None

    result = {
        "status": status,
        "mine_baseline": baseline,
        "target_reduction_pct": target_reduction_pct,
        "budget_inr": budget_inr,
        "recommended_investment_inr": round(chosen["cost"], 2),
        "achieved_reduction_pct": round(chosen["reduction_pct"], 2),
        "co2e_avoided_t": co2e_avoided_t,
        "residual_emissions_t": round(residual_t, 3),
        "cost_per_tco2e_inr": cost_per_tco2e,
        "optimized_scopes": chosen["optimized"],
        "selected_interventions": selected,
        "explanation": _build_explanation(status, selected, target_reduction_pct, chosen["reduction_pct"]),
    }

    if status == "TARGET_NOT_FEASIBLE_WITHIN_BUDGET":
        gap_pct = round(target_reduction_pct - chosen["reduction_pct"], 2)
        result["gap_to_target_pct"] = gap_pct

    return result


def _build_explanation(status, selected, target_pct, achieved_pct):
    if not selected:
        return ("No intervention could be deployed within the given budget. "
                "Increase the budget or review the intervention library.")

    lines = []
    if status == "TARGET_MET":
        lines.append(
            f"The optimizer found a minimum-cost combination of {len(selected)} intervention(s) "
            f"that achieves an estimated {achieved_pct:.1f}% reduction, meeting the {target_pct:.0f}% target within budget."
        )
    else:
        lines.append(
            f"No combination of available interventions reaches the {target_pct:.0f}% target within the given budget. "
            f"The best achievable package within budget is an estimated {achieved_pct:.1f}% reduction."
        )

    for e in selected:
        if e["has_interaction"]:
            s1_avoided = -e["scope1_effect_t"]
            s2_added = e["scope2_effect_t"]
            net = s1_avoided - s2_added
            lines.append(
                f"{e['name']}: modeled net effect combines a Scope 1 reduction of "
                f"~{s1_avoided:.0f} tCO2e (less diesel) with a Scope 2 increase of "
                f"~{s2_added:.0f} tCO2e (more purchased electricity for charging), "
                f"for a net ~{net:.0f} tCO2e avoided -- calculated jointly, never summed as independent percentages."
            )
    return " ".join(lines)
