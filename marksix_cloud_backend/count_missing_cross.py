"""A7 cross analysis using the existing V7 foundation and historical signal thresholds."""
from dataclasses import asdict
from statistics import median

from .analysis_engine import build_analysis_foundation
from .statistics_core import TOTAL_NUMBERS, count_by_window, missing_count, theoretical_probability


def count_missing_cross_response(snapshot, window=30, include_special=False):
    foundation = build_analysis_foundation(snapshot, include_special)
    current = foundation.current
    result_map = {row.number: asdict(row) for row in current.numbers}
    counts = count_by_window(snapshot, window, include_special)
    theoretical_average = window * theoretical_probability(include_special)
    missing_map = {n: missing_count(snapshot, n, include_special)
                   for n in range(1, TOTAL_NUMBERS + 1)}
    missing_median = float(median(m["missing_periods"] for m in missing_map.values()))

    # Candidate membership is the existing A2/A3/A4 rule, calculated from
    # the same current and previous MarkSix snapshots.
    recovery_numbers, reversal_numbers, overheat_numbers = set(), set(), set()
    for row, previous in zip(current.numbers, foundation.previous.numbers):
        r10, r30, r50, r100 = row.r10, row.r30, row.r50, row.r100
        if (r50 < 1 or r100 < 1) and r10 > 1 and r10 > r30:
            recovery_numbers.add(row.number)
        previous_direction = previous.r10 - previous.r30
        current_direction = r10 - r30
        if (round(previous_direction, 4) <= 0 and
                round(current_direction, 4) >= 0.20 and
                round(current_direction - previous_direction, 4) > 0):
            reversal_numbers.add(row.number)
        long_base = (r50 + r100) / 2.0
        heat = round(max(0.0, r10 - r30) * 0.50 +
                     max(0.0, r10 - long_base) * 0.50, 4)
        if r10 >= 1.50 and heat >= 0.50:
            overheat_numbers.add(row.number)

    output = []

    for number in range(1, TOTAL_NUMBERS + 1):
        item = result_map[number]
        missing = missing_map[number]
        missing_periods = int(missing["missing_periods"])
        count = counts[number]

        frequency_ratio = (
            count / theoretical_average
            if theoretical_average > 0
            else 0.0
        )

        # 次數高低：相對該視窗理論平均。
        frequency_level = (
            "高頻"
            if count >= theoretical_average
            else "低頻"
        )

        # A7 v1.1：遺漏改為三層，避免中位數只有 4 期時，
        # 把遺漏 4～5 期直接稱為「長漏」而造成誤解。
        # 短漏：低於中位數
        # 一般遺漏：中位數 ～ 未滿 2 倍中位數
        # 高遺漏：至少 2 倍中位數
        high_missing_threshold = (
            missing_median * 2.0
            if missing_median > 0
            else 1.0
        )

        if missing_periods < missing_median:
            missing_level = "短漏"
        elif missing_periods < high_missing_threshold:
            missing_level = "一般遺漏"
        else:
            missing_level = "高遺漏"

        cross_type = f"{frequency_level}{missing_level}"

        has_recovery = number in recovery_numbers
        has_reversal = number in reversal_numbers
        has_overheat = number in overheat_numbers

        # 觀察標籤有優先順序：
        # A4 是風險層，優先標示；A2/A3 是轉強訊號；
        # 若都沒有，再回到次數 × 遺漏的純狀態描述。
        if has_overheat:
            observation = "過熱注意"
            observation_priority = 5
        elif has_recovery and missing_level == "高遺漏":
            observation = "回補觀察"
            observation_priority = 4
        elif has_reversal:
            observation = "反轉觀察"
            observation_priority = 3
        elif cross_type == "高頻短漏":
            observation = "持續活躍"
            observation_priority = 2
        elif cross_type == "高頻一般遺漏":
            observation = "活躍觀察"
            observation_priority = 2
        elif cross_type == "高頻高遺漏":
            observation = "活躍後沉寂"
            observation_priority = 2
        elif cross_type == "低頻高遺漏":
            observation = "弱勢沉寂"
            observation_priority = 1
        elif cross_type == "低頻一般遺漏":
            observation = "低頻觀察"
            observation_priority = 1
        else:
            observation = "低頻近期出現"
            observation_priority = 1

        # 交叉指標只用於頁面排序，不取代 V7。
        # frequency_ratio 代表開出次數相對理論平均；
        # missing_ratio 代表遺漏相對當期中位數。
        missing_ratio = (
            missing_periods / missing_median
            if missing_median > 0
            else float(missing_periods)
        )
        v7_score = float(item["score"]) if item else 0.0
        v7_ratio = max(0.0, min(v7_score / 100.0, 1.0))

        cross_score = (
            min(frequency_ratio, 2.5) * 0.40
            + min(missing_ratio, 3.0) * 0.30
            + v7_ratio * 0.30
        )

        # 過熱是風險提示，不把它當加分推薦。
        if has_overheat:
            cross_score -= 0.20

        output.append({
            "number": number,
            "window": window,
            "count": count,
            "theoretical_average": round(theoretical_average, 2),
            "difference_from_average": round(
                count - theoretical_average,
                2,
            ),
            "frequency_ratio": round(frequency_ratio, 3),
            "frequency_level": frequency_level,
            "missing_periods": missing_periods,
            "missing_median": round(missing_median, 2),
            "missing_ratio": round(missing_ratio, 3),
            "missing_level": missing_level,
            "cross_type": cross_type,
            "observation": observation,
            "signals": {
                "recovery_a2": has_recovery,
                "reversal_a3": has_reversal,
                "overheat_a4": has_overheat,
            },
            "cross_score": round(cross_score, 4),
            "last_draw_no": missing["last_draw"],
            "last_draw_date": missing["last_date"],
            "v7_score": item["score"] if item else None,
            "grade": item["grade"] if item else None,
            "momentum_type": item["momentum_type"] if item else None,
            "momentum": {
                "10": round(float(item["r10"]), 2) if item else None,
                "30": round(float(item["r30"]), 2) if item else None,
                "50": round(float(item["r50"]), 2) if item else None,
                "100": round(float(item["r100"]), 2) if item else None,
            },
            "_observation_priority": observation_priority,
        })

    # 預設先看有明確訊號者，再看交叉指標。
    output.sort(
        key=lambda x: (
            -x["_observation_priority"],
            -x["cross_score"],
            -x["v7_score"] if x["v7_score"] is not None else 999999,
            x["number"],
        )
    )

    for item in output:
        item.pop("_observation_priority", None)

    type_counts = {
        cross_type: sum(
            1 for x in output
            if x["cross_type"] == cross_type
        )
        for cross_type in (
            "高頻短漏",
            "高頻一般遺漏",
            "高頻高遺漏",
            "低頻短漏",
            "低頻一般遺漏",
            "低頻高遺漏",
        )
    }

    return {
        "include_special": include_special,
        "theoretical_probability": theoretical_probability(include_special),
        "latest_draw": snapshot.draws[-1].as_dict(),
        "window": window,
        "missing_median": round(missing_median, 2),
        "high_missing_threshold": round(missing_median * 2.0 if missing_median > 0 else 1.0, 2),
        "theoretical_average": round(theoretical_average, 2),
        "type_counts": type_counts,
        "count": len(output),
        "numbers": output,
    }
