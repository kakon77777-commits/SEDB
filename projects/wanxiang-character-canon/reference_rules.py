from __future__ import annotations

from dataclasses import dataclass
from typing import Any


RULE_VERSION = "wanxiang-reference-rules/v1"
EVENT_LOGIC_METADATA_EVIDENCE = (
    "事件逻辑类型：0对话 1选项 2一般事件 3战斗 4答题 5骰子"
)
EVENT_LOGIC_TARGETS = {
    0: "EventDialog",
    1: "EventSelection",
    2: "EventNormal",
    3: "Battle",
    4: "EventPuzzle",
    5: "EventDice",
}


@dataclass(frozen=True)
class ReferenceRule:
    rule_id: str
    source_table: str
    field_pattern: str
    target_table: str
    split_ampersand: bool
    evidence: str


def resolve_event_logic_target(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return EVENT_LOGIC_TARGETS.get(value)


def _rule(
    rule_id: str,
    source_table: str,
    field_pattern: str,
    target_table: str,
    *,
    split_ampersand: bool = False,
    evidence: str,
) -> ReferenceRule:
    return ReferenceRule(
        rule_id,
        source_table,
        field_pattern,
        target_table,
        split_ampersand,
        evidence,
    )


DIRECT_REFERENCE_RULES = (
    _rule("hero.birth", "Hero", r"Birth", "Birth", evidence="Hero metadata field Birth"),
    _rule("hero.parent", "Hero", r"ParentId", "Hero", evidence="Hero metadata field ParentId"),
    _rule("hero.skill", "Hero", r"SkillId[0-3]", "Skill", evidence="Hero SkillId slot"),
    _rule("hero.property", "Hero", r"Property[0-5]", "Property", evidence="Hero Property slot"),
    _rule("hero.extra", "Hero", r"ExtraHeroId", "Hero", evidence="Hero metadata field ExtraHeroId"),
    _rule("hero.story", "Hero", r"StoryId", "Story", evidence="Hero metadata field StoryId"),
    _rule("map.parent", "Map", r"ParentId", "Map", evidence="Map metadata field ParentId"),
    _rule("birth.resident-map", "Birth", r"ResidentMap", "Map", evidence="Birth metadata field ResidentMap"),
    _rule("relation.birth", "Relation", r"Birth", "Birth", evidence="Relation metadata 所属地"),
    _rule("relation.property", "Relation", r"PropertyId", "Property", evidence="Relation metadata 好感度id"),
    _rule("relation.guide-event", "Relation", r"GuidEvent[0-9]", "Event", split_ampersand=True, evidence="Relation metadata 攻略事件id"),
    _rule("event.map", "Event", r"Map", "Map", evidence="Event metadata map表"),
    _rule("event.condition", "Event", r"ConditionId", "Condition", evidence="Event metadata 事件触发条件id"),
    _rule("event.result", "Event", r"ResultId", "EventResult", evidence="Event metadata 事件奖励"),
    _rule("dialog.next-dialog", "EventDialog", r"NextDialogId", "EventDialog", evidence="EventDialog metadata 下一句对话"),
    _rule("dialog.next-event", "EventDialog", r"NextEventId", "Event", evidence="EventDialog metadata 下一个事件"),
    _rule("selection.condition", "EventSelection", r"Condition(?:[0-9]|1[0-9])", "Condition", evidence="EventSelection metadata 选项条件id"),
    _rule("selection.event", "EventSelection", r"EventId(?:[0-9]|1[0-9])", "Event", evidence="EventSelection metadata 事件id"),
    _rule("normal.next-event", "EventNormal", r"NextEventId", "Event", evidence="EventNormal next event field"),
    _rule("puzzle.group", "EventPuzzle", r"PuzzleGroupId", "PuzzleGroup", evidence="EventPuzzle group field"),
    _rule("puzzle.success", "EventPuzzle", r"SuccessEventId", "Event", evidence="EventPuzzle success event field"),
    _rule("puzzle.failure", "EventPuzzle", r"FailedEventId", "Event", evidence="EventPuzzle failure event field"),
    _rule("dice.definition", "EventDice", r"DiceId", "Dice", evidence="EventDice metadata DiceId"),
    _rule("battle.success", "Battle", r"SuccessEventId", "Event", evidence="Battle metadata 胜利事件"),
    _rule("battle.failure", "Battle", r"FailedEventId", "Event", evidence="Battle metadata 失败事件"),
    _rule("battle.fixed-hero", "Battle", r"FixedHero[0-4]", "Hero", evidence="Battle metadata 固定侠客id"),
    _rule("skill.condition", "Skill", r"conditionId", "SkillCondition", evidence="Skill conditionId field"),
    _rule("skill.formula", "Skill", r"(?:FormulaId|ExtraFormulaId)", "Formula", evidence="Skill metadata 公式id"),
    _rule("skill.effect", "Skill", r"(?:EffectId[0-1]|ExtraEffectId[0-1])", "Effect", evidence="Skill metadata 特效"),
    _rule("result.condition", "EventResult", r"ConditionId[0-9]", "Condition", evidence="EventResult metadata 条件id"),
)
