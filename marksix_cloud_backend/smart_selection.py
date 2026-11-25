"""Existing B3 candidate-pool strategy port; one immutable MarkSix snapshot."""
import random
from . import momentum_signals as signals
from .analysis_engine import build_analysis_foundation
from .analysis_models import ENGINE_VERSION
from .statistics_core import TOTAL_NUMBERS

SMART_SELECTION_STRATEGIES = {
    "v7": "V7 動能",
    "explosion": "爆發",
    "recovery": "回補",
    "reversal": "反轉",
    "balanced": "均衡",
}


def _smart_base_item(item):
    return {
        "number": int(item["number"]),
        "v7_score": item.get("score"),
        "grade": item.get("grade"),
        "momentum_type": item.get("momentum_type"),
        "momentum": {
            "10": round(float(item["r10"]), 2),
            "30": round(float(item["r30"]), 2),
            "50": round(float(item["r50"]), 2),
            "100": round(float(item["r100"]), 2),
        },
    }


def _parse_number_constraint(value):
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        text = str(value).strip()
        if not text:
            return []
        raw_items = text.split(",")

    output = []
    seen = set()

    for raw in raw_items:
        try:
            number = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ValueError("鎖定／排除號碼必須是 1～49 的整數")

        if number < 1 or number > TOTAL_NUMBERS:
            raise ValueError("鎖定／排除號碼必須介於 1 到 49")

        if number not in seen:
            seen.add(number)
            output.append(number)

    return output


def get_smart_selection(snapshot, count=6, strategy="balanced", locked=None, excluded=None, include_special=False):
    try:
        count = int(count)
    except (TypeError, ValueError):
        raise ValueError("母號數量必須是 6 到 10 的整數")

    if count < 6 or count > 10:
        raise ValueError("母號數量必須介於 6 到 10")

    strategy = str(strategy or "balanced").strip().lower()
    if strategy not in SMART_SELECTION_STRATEGIES:
        raise ValueError(
            "strategy 必須是 v7、explosion、recovery、reversal、balanced 其中之一"
        )

    locked_numbers = _parse_number_constraint(locked)
    excluded_numbers = _parse_number_constraint(excluded)
    locked_set = set(locked_numbers)
    excluded_set = set(excluded_numbers)

    overlap = locked_set & excluded_set
    if overlap:
        raise ValueError(
            "同一號碼不能同時鎖定與排除：" +
            ",".join(str(n) for n in sorted(overlap))
        )

    if len(locked_numbers) > count:
        raise ValueError("鎖定號碼數量不能超過母號數量")

    foundation = build_analysis_foundation(snapshot, include_special)
    results = signals.ranked(foundation.current)
    result_map = {int(item["number"]): item for item in results}
    v7_order = [int(item["number"]) for item in results]

    strategy_details = {}

    if strategy == "v7":
        ranked_numbers = list(v7_order)

    elif strategy == "explosion":
        source = signals.get_explosion_momentum(snapshot, foundation.current)["numbers"]
        primary = [int(item["number"]) for item in source]
        ranked_numbers = primary + [n for n in v7_order if n not in set(primary)]
        strategy_details = {
            int(item["number"]): {
                "source_stage": item.get("stage"),
                "source_score": item.get("explosion_score"),
            } for item in source
        }

    elif strategy == "recovery":
        source = signals.get_recovery_momentum(snapshot, foundation.current)["numbers"]
        primary = [int(item["number"]) for item in source]
        ranked_numbers = primary + [n for n in v7_order if n not in set(primary)]
        strategy_details = {
            int(item["number"]): {
                "source_stage": item.get("stage"),
                "source_score": item.get("recovery_score"),
            } for item in source
        }

    elif strategy == "reversal":
        source = signals.get_reversal_momentum(snapshot, foundation)["numbers"]
        primary = [int(item["number"]) for item in source]
        ranked_numbers = primary + [n for n in v7_order if n not in set(primary)]
        strategy_details = {
            int(item["number"]): {
                "source_stage": item.get("stage"),
                "source_score": item.get("reversal_score"),
            } for item in source
        }

    else:
        explosion = signals.get_explosion_momentum(snapshot, foundation.current)["numbers"]
        recovery = signals.get_recovery_momentum(snapshot, foundation.current)["numbers"]
        reversal = signals.get_reversal_momentum(snapshot, foundation)["numbers"]
        overheat = signals.get_overheat_momentum(snapshot, foundation)["numbers"]

        ranking_points = {number: 0.0 for number in range(1, TOTAL_NUMBERS + 1)}
        sources = {number: [] for number in range(1, TOTAL_NUMBERS + 1)}

        def add_ranked_points(items, label, weight):
            total = len(items)
            if total <= 0:
                return
            for rank, item in enumerate(items, start=1):
                number = int(item["number"])
                rank_value = (total - rank + 1) / total
                ranking_points[number] += rank_value * weight
                sources[number].append(label)

        add_ranked_points(results, "V7", 0.40)
        add_ranked_points(explosion, "A1爆發", 0.20)
        add_ranked_points(recovery, "A2回補", 0.20)
        add_ranked_points(reversal, "A3反轉", 0.20)

        heat_penalty = {
            "高度過熱": 0.30,
            "過熱警示": 0.22,
            "過熱觀察": 0.14,
            "升溫偏熱": 0.07,
        }
        heat_map = {}

        for item in overheat:
            number = int(item["number"])
            stage = item.get("stage")
            penalty = heat_penalty.get(stage, 0.0)
            ranking_points[number] -= penalty
            heat_map[number] = {
                "stage": stage,
                "overheat_score": item.get("overheat_score"),
                "penalty": penalty,
            }

        ranked_numbers = sorted(
            range(1, TOTAL_NUMBERS + 1),
            key=lambda number: (
                -ranking_points[number],
                -float(result_map[number]["score"]),
                number,
            ),
        )

        strategy_details = {
            number: {
                "balanced_score": round(ranking_points[number], 4),
                "sources": sources[number],
                "overheat": heat_map.get(number),
            } for number in range(1, TOTAL_NUMBERS + 1)
        }

    # B3 重新產生：
    # - 鎖定號碼永遠保留。
    # - 排除號碼永遠不加入。
    # - 其餘位置不是 1~49 純隨機，而是從「目前策略排名前段」抽取。
    # - 排名越前面的號碼權重越高，因此保留策略方向，同時讓重新產生有變化。
    selected_numbers = list(locked_numbers)
    selected_set = set(selected_numbers)
    remaining_count = count - len(selected_numbers)

    eligible_ranked = [
        number
        for number in ranked_numbers
        if number not in excluded_set and number not in selected_set
    ]

    if len(eligible_ranked) < remaining_count:
        raise ValueError("排除條件過多，無法產生指定數量的母號")

    # 候選池維持在策略排名前段；母號越多，候選池同步放大。
    # 例如 count=6 時通常從前 17 名抽取，count=10 時從前 25 名抽取。
    candidate_pool_size = min(
        len(eligible_ranked),
        max(15, count * 2 + 5),
    )
    candidate_pool = eligible_ranked[:candidate_pool_size]

    rng = random.SystemRandom()

    # 依策略名次做加權不放回抽樣。
    # 第一名權重最高、候選池最後一名權重最低。
    for _ in range(remaining_count):
        weights = list(range(len(candidate_pool), 0, -1))
        chosen = rng.choices(candidate_pool, weights=weights, k=1)[0]
        selected_numbers.append(chosen)
        selected_set.add(chosen)
        candidate_pool.remove(chosen)

    output = []
    for number in selected_numbers[:count]:
        base = _smart_base_item(result_map[number])
        detail = dict(strategy_details.get(number) or {})
        if number in locked_set:
            detail["locked"] = True
        if detail:
            base["strategy_detail"] = detail
        output.append(base)

    return {
        "engine_version": ENGINE_VERSION,
        "game": "marksix",
        "analysis_mode": signals.analysis_mode_name(include_special),
        "include_special": include_special,
        "expected_probability": f"{signals.numbers_per_draw(include_special)}/{TOTAL_NUMBERS}",
        "analysis_engine": "smart_selection_b3",
        "formula_version": "b3_v1.0_marksix",
        "latest_draw": signals.build_latest_draw(snapshot.draws),
        "strategy": strategy,
        "strategy_name": SMART_SELECTION_STRATEGIES[strategy],
        "requested_count": count,
        "count": len(output),
        "locked": locked_numbers,
        "excluded": excluded_numbers,
        "numbers": output,
        "rule": {
            "mother_number_range": [6, 10],
            "strategies": SMART_SELECTION_STRATEGIES,
            "locked": "鎖定號碼必定保留，且鎖定數量不可超過母號數量",
            "excluded": "排除號碼不會出現在結果中，且不能與鎖定號碼重複",
            "regenerate": (
                "未鎖定位置從目前策略排名前段做加權不放回抽樣；"
                "排名越前權重越高，因此每次重新產生可變化但仍保留策略方向"
            ),
            "balanced": (
                "依 V7/A1/A2/A3 正式排名整合；"
                "A4 過熱只作風險降權；A5 開出次數不直接納入推薦"
            ),
            "note": "智慧選牌為資料分析與組牌輔助，不代表或保證未來開獎結果。",
        },
    }
