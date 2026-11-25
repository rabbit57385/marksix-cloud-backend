"""MarkSix signal calculations on the existing immutable analysis foundation."""
from dataclasses import asdict
from .analysis_models import ENGINE_VERSION
from .draw_sync import api_draw
from .statistics_core import TOTAL_NUMBERS


def analysis_mode_name(include_special):
    return "main_plus_special" if include_special else "main_only"


def numbers_per_draw(include_special):
    return 6 + int(include_special)


def build_latest_draw(draws):
    return api_draw(draws[-1])


def ranked(current):
    return sorted((asdict(row) for row in current.numbers),
                  key=lambda row: (-row["score"], -row["frozen_score"], row["number"]))



def _rank_map(results):
    return {
        item["number"]: index + 1
        for index, item in enumerate(results)
    }


def _grade_rank(grade):
    # 數字越小代表等級越高
    return {
        "A": 1,
        "B": 2,
        "C": 3,
        "D": 4,
        "E": 5,
    }.get(str(grade), 99)


def _round_delta(value):
    return round(float(value), 3)


def calculate_explosion_score(r10, r30, r50, r100):
    short_gap = r10 - r30
    mid_gap = r30 - r50
    long_gap = r10 - r100

    explosion_score = (
        short_gap * 0.50
        + mid_gap * 0.30
        + long_gap * 0.20
    )

    return {
        "explosion_score": round(explosion_score, 4),
        "short_gap": round(short_gap, 4),
        "mid_gap": round(mid_gap, 4),
        "long_gap": round(long_gap, 4),
    }


def classify_explosion_stage(explosion_score, r10):
    if r10 < 1.10:
        return "無明顯爆發"
    if explosion_score >= 1.00:
        return "過熱候選"
    if explosion_score >= 0.70:
        return "爆發延續"
    if explosion_score >= 0.50:
        return "升溫觀察"
    if explosion_score >= 0.30:
        return "強爆發"
    if explosion_score >= 0.20:
        return "初步升溫"
    return "無明顯爆發"


def calculate_recovery_score(
    r10,
    r30,
    r50,
    r100,
):
    shortage = (
        max(0.0, 1.0 - r50) * 0.50
        + max(0.0, 1.0 - r100) * 0.50
    )
    rebound = max(0.0, r10 - r30)

    recovery_score = (
        shortage * 0.60
        + rebound * 0.40
    )

    return {
        "recovery_score": round(recovery_score, 4),
        "shortage": round(shortage, 4),
        "rebound": round(rebound, 4),
    }


def classify_recovery_stage(
    shortage,
    rebound,
):
    # 回測顯示深度欠缺並不代表回補更強。
    if shortage >= 0.30:
        return "深度欠缺觀察"

    # 欠缺很輕、且短期尚未明顯拉升：
    # 回測 next1 表現最佳，視為「回補前段」。
    if shortage < 0.10 and rebound < 0.30:
        return "回補蓄勢"

    # 輕度欠缺 + 明顯短期回升：
    # next3 / next5 表現較佳，視為正在回補。
    if shortage < 0.10 and rebound >= 0.90:
        return "強回補"

    if shortage < 0.10 and rebound >= 0.30:
        return "回補延續"

    # 0.10~0.20 欠缺區，回升 0.30~0.60 的回測表現相對較佳。
    if shortage < 0.20 and 0.30 <= rebound < 0.60:
        return "回補升溫"

    if shortage < 0.20:
        return "回補觀察"

    # 0.20~0.30 樣本較少；保留訊號但降低優先度。
    if shortage < 0.30 and rebound < 0.30:
        return "回補蓄勢"

    return "回補觀察"


def calculate_reversal_score(
    r10,
    r30,
    r50,
    r100,
    previous_r10,
    previous_r30,
):
    long_base = (r50 + r100) / 2.0
    previous_direction = previous_r10 - previous_r30
    current_direction = r10 - r30
    direction_change = current_direction - previous_direction
    previous_gap = max(0.0, long_base - r30)

    reversal_score = (
        previous_gap * 0.50
        + current_direction * 0.50
    )

    return {
        "reversal_score": round(reversal_score, 4),
        "long_base": round(long_base, 4),
        "previous_gap": round(previous_gap, 4),
        "previous_direction": round(previous_direction, 4),
        "current_direction": round(current_direction, 4),
        "direction_change": round(direction_change, 4),
    }


def classify_reversal_stage(
    previous_gap,
    current_direction,
):
    if previous_gap < 0.10 and 0.20 <= current_direction < 0.30:
        return "強反轉"

    if previous_gap < 0.20 and 0.20 <= current_direction < 0.60:
        return "反轉升溫"

    if previous_gap < 0.30 and current_direction >= 0.20:
        return "反轉延續"

    return "跨零反轉"


def calculate_overheat_score(
    r10,
    r30,
    r50,
    r100,
):
    long_base = (r50 + r100) / 2.0
    short_excess = max(0.0, r10 - r30)
    long_excess = max(0.0, r10 - long_base)

    overheat_score = (
        short_excess * 0.50
        + long_excess * 0.50
    )

    return {
        "overheat_score": round(overheat_score, 4),
        "long_base": round(long_base, 4),
        "short_excess": round(short_excess, 4),
        "long_excess": round(long_excess, 4),
    }


def classify_overheat_stage(
    r10,
    overheat_score,
    previous_overheat_score,
):
    # A4 是風險層級，不以分數高低作為推薦排序。
    # 先把真正短期極強且延伸幅度大的號碼列為最高警示。
    if r10 >= 2.40 and overheat_score >= 1.40:
        return "高度過熱"

    # 前一期已熱、這一期仍維持明顯延伸，代表熱度具有延續性。
    if (
        r10 >= 2.10
        and overheat_score >= 1.10
        and previous_overheat_score >= 0.80
    ):
        return "過熱警示"

    # 中高短期強度 + 明顯超越中長期基準。
    if r10 >= 1.80 and overheat_score >= 0.80:
        return "過熱觀察"

    # 剛進入熱區，但尚不足以判定為正式過熱。
    if r10 >= 1.50 and overheat_score >= 0.50:
        return "升溫偏熱"

    return "無明顯過熱"


def get_today_momentum_changes(snapshot, foundation):
    draws = snapshot.draws
    include_special = foundation.current.include_special
    current_results = ranked(foundation.current)
    previous_results = ranked(foundation.previous)
    current_map = {
        item["number"]: item
        for item in current_results
    }
    previous_map = {
        item["number"]: item
        for item in previous_results
    }

    current_rank = _rank_map(current_results)
    previous_rank = _rank_map(previous_results)

    current_top5 = [item["number"] for item in current_results[:5]]
    previous_top5 = [item["number"] for item in previous_results[:5]]

    changes = []

    for number in range(1, 50):
        current = current_map.get(number)
        previous = previous_map.get(number)

        if current is None or previous is None:
            continue

        current_score = float(current["score"])
        previous_score = float(previous["score"])
        score_delta = _round_delta(current_score - previous_score)

        current_grade = str(current["grade"])
        previous_grade = str(previous["grade"])

        current_warnings = list(current.get("warnings", []))
        previous_warnings = list(previous.get("warnings", []))

        item = {
            "number": number,
            "score": round(current_score, 3),
            "previous_score": round(previous_score, 3),
            "score_delta": score_delta,
            "grade": current_grade,
            "previous_grade": previous_grade,
            "grade_changed": current_grade != previous_grade,
            "grade_improved": (
                _grade_rank(current_grade) < _grade_rank(previous_grade)
            ),
            "grade_declined": (
                _grade_rank(current_grade) > _grade_rank(previous_grade)
            ),
            "rank": current_rank.get(number),
            "previous_rank": previous_rank.get(number),
            "rank_delta": (
                previous_rank.get(number, 40) - current_rank.get(number, 40)
            ),
            "momentum_delta": {
                "10": _round_delta(float(current["r10"]) - float(previous["r10"])),
                "30": _round_delta(float(current["r30"]) - float(previous["r30"])),
                "50": _round_delta(float(current["r50"]) - float(previous["r50"])),
                "100": _round_delta(float(current["r100"]) - float(previous["r100"])),
            },
            "frozen_score_delta": _round_delta(
                float(current["frozen_score"]) -
                float(previous["frozen_score"])
            ),
            "warning_count": len(current_warnings),
            "previous_warning_count": len(previous_warnings),
            "warning_delta": len(current_warnings) - len(previous_warnings),
            "entered_top5": (
                number in current_top5 and number not in previous_top5
            ),
            "left_top5": (
                number not in current_top5 and number in previous_top5
            ),
        }

        changes.append(item)

    rising_top5 = sorted(
        changes,
        key=lambda item: (-item["score_delta"], item["number"]),
    )[:5]

    falling_top5 = sorted(
        changes,
        key=lambda item: (item["score_delta"], item["number"]),
    )[:5]

    grade_changes = [
        item for item in changes
        if item["grade_changed"]
    ]
    grade_changes.sort(
        key=lambda item: (
            0 if item["grade_improved"] else 1,
            -abs(item["score_delta"]),
            item["number"],
        )
    )

    key_changes = [
        item for item in changes
        if (
            item["entered_top5"]
            or item["left_top5"]
            or item["warning_delta"] != 0
        )
    ]
    key_changes.sort(
        key=lambda item: (
            0 if item["entered_top5"] else
            1 if item["left_top5"] else 2,
            -abs(item["score_delta"]),
            item["number"],
        )
    )

    return {
        "engine_version": ENGINE_VERSION,
        "analysis_mode": analysis_mode_name(include_special),
        "include_special": include_special,
        "comparison": {
            "current_draw": build_latest_draw(draws),
            "previous_draw": build_latest_draw(draws[:-1]),
        },
        "rising_top5": rising_top5,
        "falling_top5": falling_top5,
        "grade_changes": grade_changes,
        "key_changes": key_changes,
        "all_changes": changes,
    }


def get_explosion_momentum(snapshot, current):
    draws = snapshot.draws
    include_special = current.include_special
    results = ranked(current)
    output = []

    for item in results:
        r10 = float(item["r10"])
        r30 = float(item["r30"])
        r50 = float(item["r50"])
        r100 = float(item["r100"])

        explosion = calculate_explosion_score(
            r10, r30, r50, r100
        )
        explosion_score = explosion["explosion_score"]
        stage = classify_explosion_stage(
            explosion_score, r10
        )

        if stage == "無明顯爆發":
            continue

        output.append({
            "number": int(item["number"]),
            "explosion_score": explosion_score,
            "stage": stage,
            "v7_score": item["score"],
            "grade": item["grade"],
            "momentum_type": item["momentum_type"],
            "momentum": {
                "10": round(r10, 2),
                "30": round(r30, 2),
                "50": round(r50, 2),
                "100": round(r100, 2),
            },
            "change": {
                "short_gap": explosion["short_gap"],
                "mid_gap": explosion["mid_gap"],
                "long_gap": explosion["long_gap"],
            },
        })

    stage_priority = {
        "強爆發": 0,
        "爆發延續": 1,
        "升溫觀察": 2,
        "初步升溫": 3,
        "過熱候選": 4,
    }

    output.sort(
        key=lambda x: (
            stage_priority.get(x["stage"], 99),
            -x["explosion_score"],
            -x["momentum"]["10"],
            x["number"],
        )
    )

    return {
        "engine_version": ENGINE_VERSION,
        "analysis_engine": "explosion_momentum_a1_marksix",
        "formula_version": "a1_v1.0",
        "analysis_mode": analysis_mode_name(include_special),
        "include_special": include_special,
        "expected_probability": (
            "7/49" if include_special else "6/49"
        ),
        "latest_draw": build_latest_draw(draws),
        "rule": {
            "min_r10": 1.10,
            "formula": (
                "(r10-r30)*0.50 + "
                "(r30-r50)*0.30 + "
                "(r10-r100)*0.20"
            ),
        },
        "count": len(output),
        "numbers": output,
    }


def get_recovery_momentum(snapshot, current):
    draws = snapshot.draws
    include_special = current.include_special
    results = ranked(current)
    output = []

    for item in results:
        r10 = float(item["r10"])
        r30 = float(item["r30"])
        r50 = float(item["r50"])
        r100 = float(item["r100"])

        # A2 候選門檻沿用正式回測條件：
        # r50 < 1 或 r100 < 1；r10 > 1；r10 > r30。
        if not (
            (r50 < 1.0 or r100 < 1.0)
            and r10 > 1.0
            and r10 > r30
        ):
            continue

        recovery = calculate_recovery_score(
            r10,
            r30,
            r50,
            r100,
        )

        stage = classify_recovery_stage(
            recovery["shortage"],
            recovery["rebound"],
        )

        output.append({
            "number": int(item["number"]),
            "recovery_score": recovery["recovery_score"],
            "stage": stage,
            "v7_score": item["score"],
            "grade": item["grade"],
            "momentum_type": item["momentum_type"],
            "momentum": {
                "10": round(r10, 2),
                "30": round(r30, 2),
                "50": round(r50, 2),
                "100": round(r100, 2),
            },
            "change": {
                "shortage": recovery["shortage"],
                "rebound": recovery["rebound"],
            },
        })

    # 不以 recovery_score 單純由高到低排列。
    # 先依回測後的回補階段，再用分數與短期回升做同級排序。
    stage_priority = {
        "強回補": 0,
        "回補蓄勢": 1,
        "回補升溫": 2,
        "回補延續": 3,
        "回補觀察": 4,
        "深度欠缺觀察": 5,
    }

    output.sort(
        key=lambda x: (
            stage_priority.get(x["stage"], 99),
            -x["recovery_score"],
            -x["change"]["rebound"],
            x["number"],
        )
    )

    return {
        "engine_version": ENGINE_VERSION,
        "analysis_engine": "recovery_momentum_a2_marksix",
        "formula_version": "a2_v1.0",
        "analysis_mode": analysis_mode_name(include_special),
        "include_special": include_special,
        "expected_probability": (
            "7/49" if include_special else "6/49"
        ),
        "latest_draw": build_latest_draw(draws),
        "rule": {
            "candidate": (
                "(r50 < 1.00 or r100 < 1.00) "
                "and r10 > 1.00 and r10 > r30"
            ),
            "formula": (
                "shortage*0.60 + rebound*0.40; "
                "shortage=max(0,1-r50)*0.50 + "
                "max(0,1-r100)*0.50; "
                "rebound=max(0,r10-r30)"
            ),
            "note": "回補分數不是越高越好；深度欠缺降低優先度",
        },
        "count": len(output),
        "numbers": output,
    }


def get_reversal_momentum(snapshot, foundation):
    draws = snapshot.draws
    include_special = foundation.current.include_special
    current_results = ranked(foundation.current)
    previous_results = ranked(foundation.previous)
    previous_map = {
        int(item["number"]): item
        for item in previous_results
    }

    output = []

    for item in current_results:
        number = int(item["number"])
        previous = previous_map.get(number)

        if not previous:
            continue

        r10 = float(item["r10"])
        r30 = float(item["r30"])
        r50 = float(item["r50"])
        r100 = float(item["r100"])
        previous_r10 = float(previous["r10"])
        previous_r30 = float(previous["r30"])

        reversal = calculate_reversal_score(
            r10,
            r30,
            r50,
            r100,
            previous_r10,
            previous_r30,
        )

        if not (
            reversal["previous_direction"] <= 0.0
            and reversal["current_direction"] >= 0.20
            and reversal["direction_change"] > 0.0
        ):
            continue

        stage = classify_reversal_stage(
            reversal["previous_gap"],
            reversal["current_direction"],
        )

        output.append({
            "number": number,
            "reversal_score": reversal["reversal_score"],
            "stage": stage,
            "v7_score": item["score"],
            "grade": item["grade"],
            "momentum_type": item["momentum_type"],
            "momentum": {
                "10": round(r10, 2),
                "30": round(r30, 2),
                "50": round(r50, 2),
                "100": round(r100, 2),
            },
            "change": {
                "long_base": reversal["long_base"],
                "previous_gap": reversal["previous_gap"],
                "previous_direction": reversal["previous_direction"],
                "current_direction": reversal["current_direction"],
                "direction_change": reversal["direction_change"],
            },
        })

    stage_priority = {
        "強反轉": 0,
        "反轉升溫": 1,
        "反轉延續": 2,
        "跨零反轉": 3,
    }

    output.sort(
        key=lambda x: (
            stage_priority.get(x["stage"], 99),
            x["change"]["previous_gap"],
            x["change"]["current_direction"],
            -x["reversal_score"],
            x["number"],
        )
    )

    return {
        "engine_version": ENGINE_VERSION,
        "analysis_engine": "reversal_momentum_a3_marksix",
        "formula_version": "a3_v3.0",
        "analysis_mode": analysis_mode_name(include_special),
        "include_special": include_special,
        "expected_probability": (
            "7/49" if include_special else "6/49"
        ),
        "latest_draw": build_latest_draw(draws),
        "previous_draw": build_latest_draw(draws[:-1]),
        "rule": {
            "candidate": (
                "previous_direction <= 0 and current_direction >= 0.20 "
                "and direction_change > 0"
            ),
            "formula": (
                "long_base=(r50+r100)/2; "
                "previous_gap=max(0,long_base-r30); "
                "reversal_score=previous_gap*0.50 + current_direction*0.50"
            ),
            "note": (
                "A3 專看短期方向由弱跨零轉強，"
                "不以反轉分數單純由高到低排列"
            ),
        },
        "count": len(output),
        "numbers": output,
    }


def get_overheat_momentum(snapshot, foundation):
    draws = snapshot.draws
    include_special = foundation.current.include_special
    current_results = ranked(foundation.current)
    previous_results = ranked(foundation.previous)
    previous_map = {
        int(item["number"]): item
        for item in previous_results
    }

    output = []

    for item in current_results:
        number = int(item["number"])
        previous = previous_map.get(number)

        if not previous:
            continue

        r10 = float(item["r10"])
        r30 = float(item["r30"])
        r50 = float(item["r50"])
        r100 = float(item["r100"])

        previous_r10 = float(previous["r10"])
        previous_r30 = float(previous["r30"])
        previous_r50 = float(previous["r50"])
        previous_r100 = float(previous["r100"])

        current_heat = calculate_overheat_score(
            r10,
            r30,
            r50,
            r100,
        )

        previous_heat = calculate_overheat_score(
            previous_r10,
            previous_r30,
            previous_r50,
            previous_r100,
        )

        overheat_score = current_heat["overheat_score"]
        previous_overheat_score = previous_heat["overheat_score"]

        # A4 主清單只收進入偏熱區的號碼。
        # r10 與 overheat_score 同時設最低門檻，避免一般波動被誤標。
        if not (
            r10 >= 1.50
            and overheat_score >= 0.50
        ):
            continue

        stage = classify_overheat_stage(
            r10,
            overheat_score,
            previous_overheat_score,
        )

        if stage == "無明顯過熱":
            continue

        output.append({
            "number": number,
            "overheat_score": overheat_score,
            "stage": stage,
            "risk": True,
            "v7_score": item["score"],
            "grade": item["grade"],
            "momentum_type": item["momentum_type"],
            "momentum": {
                "10": round(r10, 2),
                "30": round(r30, 2),
                "50": round(r50, 2),
                "100": round(r100, 2),
            },
            "change": {
                "long_base": current_heat["long_base"],
                "short_excess": current_heat["short_excess"],
                "long_excess": current_heat["long_excess"],
                "previous_overheat_score": previous_overheat_score,
                "overheat_change": round(
                    overheat_score - previous_overheat_score,
                    4,
                ),
            },
        })

    # A4 排的是「風險嚴重度」，不是推薦優先度。
    stage_priority = {
        "高度過熱": 0,
        "過熱警示": 1,
        "過熱觀察": 2,
        "升溫偏熱": 3,
    }

    output.sort(
        key=lambda x: (
            stage_priority.get(x["stage"], 99),
            -x["overheat_score"],
            -x["momentum"]["10"],
            x["number"],
        )
    )

    return {
        "engine_version": ENGINE_VERSION,
        "analysis_mode": analysis_mode_name(include_special),
        "include_special": include_special,
        "expected_probability": f"{numbers_per_draw(include_special)}/{TOTAL_NUMBERS}",
        "analysis_engine": "overheat_warning_a4",
        "formula_version": "a4_v2.0_marksix",
        "latest_draw": build_latest_draw(draws),
        "previous_draw": build_latest_draw(draws[:-1]),
        "rule": {
            "candidate": (
                "r10 >= 1.50 and overheat_score >= 0.50"
            ),
            "formula": (
                "long_base=(r50+r100)/2; "
                "short_excess=max(0,r10-r30); "
                "long_excess=max(0,r10-long_base); "
                "overheat_score=short_excess*0.50 + long_excess*0.50"
            ),
            "note": (
                "A4 為風險警示模組；分數越高代表過度延伸風險越高，"
                "不代表推薦程度越高。前一期熱度用於辨識持續過熱。"
            ),
        },
        "count": len(output),
        "numbers": output,
    }
