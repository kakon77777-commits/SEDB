from __future__ import annotations

from collections import Counter
from statistics import fmean

from gameplay.common import StaticDataset, standard_claims


def _numeric(payloads: list[dict], key: str) -> list[float | int]:
    return [
        payload[key]
        for payload in payloads
        if isinstance(payload.get(key), (int, float))
        and not isinstance(payload.get(key), bool)
    ]


def _distribution(values) -> dict[str, int]:
    return dict(
        sorted(
            ((str(key), count) for key, count in Counter(values).items()),
            key=lambda item: item[0],
        )
    )


def analyze_combat_progression(dataset: StaticDataset) -> dict:
    skills = dataset.table("Skill")
    battles = dataset.table("Battle")
    difficulties = dataset.table("Difficulty")
    formulas = dataset.table("Formula")
    effects = dataset.table("Effect")
    buffs = dataset.table("Buff")
    skill_payloads = [record.values.get("source_row_payload") or {} for record in skills]
    battle_payloads = [record.values.get("source_row_payload") or {} for record in battles]
    difficulty_payloads = [record.values.get("source_row_payload") or {} for record in difficulties]
    skill_edges = [
        edge
        for edge in dataset.edges()
        if edge.values.get("edge_source_table") == "Skill"
    ]
    battle_edges = [
        edge
        for edge in dataset.edges()
        if edge.values.get("edge_source_table") == "Battle"
    ]
    formula_edges = [
        edge for edge in skill_edges
        if edge.values.get("edge_target_table") == "Formula"
    ]
    effect_edges = [
        edge for edge in skill_edges
        if edge.values.get("edge_target_table") == "Effect"
    ]
    costs = _numeric(skill_payloads, "Cost")
    launch_rates = _numeric(skill_payloads, "LaunchRate")
    success_rates = _numeric(skill_payloads, "SuccessRate")
    metrics = {
        "skills": len(skills),
        "battles": len(battles),
        "difficulty_profiles": len(difficulties),
        "formulas": len(formulas),
        "effects": len(effects),
        "buffs": len(buffs),
        "skills_with_cost": sum(payload.get("Cost") not in (None, -1, "nil") for payload in skill_payloads),
        "skills_with_formula": sum(payload.get("FormulaId") not in (None, -1, "nil") for payload in skill_payloads),
        "battles_with_fixed_hero": sum(any(payload.get(f"FixedHero{slot}") not in (None, -1, "nil") for slot in range(5)) for payload in battle_payloads),
        "single_battles": sum(payload.get("IsSingle") is True for payload in battle_payloads),
        "fixed_party_battles": sum(payload.get("IsFixed") is True for payload in battle_payloads),
        "resolved_formula_links": sum(
            edge.values.get("edge_resolution_status") == "resolved"
            for edge in formula_edges
        ),
        "missing_formula_links": sum(
            edge.values.get("edge_resolution_status") == "missing_target"
            for edge in formula_edges
        ),
        "resolved_effect_links": sum(
            edge.values.get("edge_resolution_status") == "resolved"
            for edge in effect_edges
        ),
        "missing_effect_links": sum(
            edge.values.get("edge_resolution_status") == "missing_target"
            for edge in effect_edges
        ),
        "resolved_battle_continuations": sum(
            edge.values.get("edge_target_table") == "Event"
            and edge.values.get("edge_resolution_status") == "resolved"
            for edge in battle_edges
        ),
        "missing_battle_continuations": sum(
            edge.values.get("edge_target_table") == "Event"
            and edge.values.get("edge_resolution_status") == "missing_target"
            for edge in battle_edges
        ),
    }
    difficulty_values = [
            {
                "id": record.values.get("source_record_id"),
                "name": payload.get("Name"),
                "hp": payload.get("Hp"),
                "damage": payload.get("Damage"),
                "debuff_resist": payload.get("DebuffResist"),
            }
            for record, payload in zip(difficulties, difficulty_payloads)
        ]
    return {
        "analysis_name": "combat-progression",
        "source_tables": ["Skill", "SkillCondition", "Formula", "Effect", "Buff", "Battle", "Difficulty"],
        "metrics": metrics,
        "details": {
            "skill_cost_distribution": _distribution(costs),
            "skill_type_distribution": _distribution(
                payload.get("SkillType")
                for payload in skill_payloads
                if payload.get("SkillType") not in (None, "nil")
            ),
            "skill_subtype_distribution": _distribution(
                payload.get("SubType")
                for payload in skill_payloads
                if payload.get("SubType") not in (None, "nil")
            ),
            "launch_rate_average": float(fmean(launch_rates)) if launch_rates else None,
            "success_rate_average": float(fmean(success_rates)) if success_rates else None,
            "unique_formula_targets": len(
                {
                    edge.values.get("edge_target_entity_id")
                    for edge in formula_edges
                    if edge.values.get("edge_target_entity_id")
                }
            ),
            "unique_effect_targets": len(
                {
                    edge.values.get("edge_target_entity_id")
                    for edge in effect_edges
                    if edge.values.get("edge_target_entity_id")
                }
            ),
            "difficulty_values": difficulty_values,
            "diversity_boundary": "STATIC_REPRESENTATION_ONLY_NOT_LIVE_BUILD_DIVERSITY",
        },
        "claims": standard_claims(
            observed=f"The static catalog contains {len(skills)} Skill rows, {len(battles)} Battle rows, and {len(difficulties)} Difficulty rows.",
            inferred="The represented formula and effect space may permit multiple build patterns.",
            unknown="Obtainability, dominant builds, encounter execution, and strategic variety remain unmeasured.",
            falsifying_test="Compare naturally obtainable builds under the same isolated battle gate.",
            evidence=("Skill", "Formula", "Battle", "Difficulty"),
        ),
    }
