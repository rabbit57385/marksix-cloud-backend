"""Aggregate the existing signals from a single MarkSix snapshot."""
import hashlib
import json
from .analysis_models import ENGINE_VERSION
from .draw_sync import source_revision
from .momentum_signals import (
    analysis_mode_name, build_latest_draw, ranked, get_today_momentum_changes,
    get_explosion_momentum, get_recovery_momentum, get_reversal_momentum,
    get_overheat_momentum,
)


def focus_identity(history, include_special, versions):
    revision = source_revision(history).split(":", 1)[1]
    identity = json.dumps([revision, include_special, versions, "focus_observation_v1_marksix"],
                          sort_keys=True, separators=(",", ":"))
    return "marksix-data-v1:" + revision, "marksix-focus-v1:" + hashlib.sha256(identity.encode()).hexdigest()


_POSITIVE_STAGES = (
    ("explosion", "爆發動能", frozenset({"強爆發", "爆發延續"})),
    ("recovery", "回補動能", frozenset({"強回補", "回補延續", "回補升溫"})),
    ("reversal", "反轉動能", frozenset({"強反轉", "反轉升溫", "反轉延續", "跨零反轉"})),
)
_RISK_STAGES = frozenset({"高度過熱", "過熱警示", "過熱觀察", "升溫偏熱"})


def assemble_focus_observation(*, analysis, changes, explosion, recovery, reversal, overheat,
                               include_special, history):
    mode = analysis_mode_name(include_special)
    latest = analysis["latest_draw"]
    sources = (analysis, changes, explosion, recovery, reversal, overheat)
    for source in sources:
        source_latest = source.get("latest_draw", source.get("comparison", {}).get("current_draw"))
        if source["include_special"] is not include_special or source["analysis_mode"] != mode or source_latest != latest:
            raise ValueError("Focus sources do not share mode and draw identity")
    reasons = {}
    for item in changes["grade_changes"]:
        if item["grade_improved"]:
            reasons.setdefault(item["number"], {})["grade_up"] = {
                "key": "grade_up", "label": "分級上升", "details": dict(item)}
    for item in changes["key_changes"]:
        if item["entered_top5"]:
            reasons.setdefault(item["number"], {})["top5_enter"] = {
                "key": "top5_enter", "label": "新進 Top5", "details": dict(item)}
    maps = [{item["number"]: item for item in source["numbers"]}
            for source in (explosion, recovery, reversal)]
    frozen = set(analysis["frozen_strategy"]["top5"])
    risks = {item["number"]: item["stage"] for item in overheat["numbers"] if item["stage"] in _RISK_STAGES}
    numbers = []
    for item in analysis["numbers"]:
        number, grade = item["number"], item["grade"]
        signals = {}
        def add(key, category, label, stage=None, why=None):
            signals[category] = {"key": key, "category": category, "label": label,
                                 "stage": stage, "reasons": why or []}
        if grade in ("A", "B"):
            add("grade_a" if grade == "A" else "grade_b", "grade_state",
                "強勢動能" if grade == "A" else "回升動能", grade)
        if number in reasons:
            add("momentum_change", "momentum_change", "動能變化", why=list(reasons[number].values()))
        for (key, label, accepted), mapping in zip(_POSITIVE_STAGES, maps):
            stage = mapping.get(number, {}).get("stage")
            if stage in accepted:
                add(key, key, label, stage)
        if number in frozen:
            add("frozen_top5", "frozen_top5", "中長期支撐")
        risk_stage = risks.get(number)
        numbers.append({"number": number, "grade": grade, "activity_score": item["score"],
                        "positive_signal_count": len(signals), "signals": list(signals.values()),
                        "risk": risk_stage is not None, "risk_stage": risk_stage, "risk_label": risk_stage})
    numbers.sort(key=lambda item: (-item["positive_signal_count"], -item["activity_score"], item["number"]))
    versions = {"momentum": analysis["engine_version"],
                "explosion": explosion["formula_version"], "recovery": recovery["formula_version"],
                "reversal": reversal["formula_version"], "overheat": overheat["formula_version"],
                "frozen_strategy": analysis["frozen_strategy"]["name"],
                "frozen": analysis["frozen_strategy"]["version"]}
    revision, snapshot = focus_identity(history, include_special, versions)
    return {"analysis_engine": "focus_observation_v1_marksix", "engine_version": analysis["engine_version"],
            "analysis_mode": mode, "include_special": include_special,
            "data_revision": revision, "snapshot_id": snapshot, "latest_draw": latest, "numbers": numbers,
            "metadata": {"total_numbers": 49, "qualified_count": sum(n["positive_signal_count"] >= 2 for n in numbers),
                         "min_positive_signals": 2,
                         "sort_rule": ["positive_signal_count DESC", "activity_score DESC", "number ASC"],
                         "formula_versions": versions}}


def get_focus_observation(snapshot, foundation):
    current = foundation.current
    rows = ranked(current)
    frozen = sorted(rows, key=lambda row: (-row["frozen_score"], row["number"]))
    analysis = {
        "engine_version": ENGINE_VERSION,
        "include_special": current.include_special,
        "analysis_mode": analysis_mode_name(current.include_special),
        "latest_draw": build_latest_draw(snapshot.draws),
        "numbers": rows,
        "frozen_strategy": {"name": "long_hot_v1", "version": "1.0.0",
                            "top5": [row["number"] for row in frozen[:5]]},
    }
    return assemble_focus_observation(
        analysis=analysis, changes=get_today_momentum_changes(snapshot, foundation),
        explosion=get_explosion_momentum(snapshot, current),
        recovery=get_recovery_momentum(snapshot, current),
        reversal=get_reversal_momentum(snapshot, foundation),
        overheat=get_overheat_momentum(snapshot, foundation),
        include_special=current.include_special, history=snapshot,
    )
