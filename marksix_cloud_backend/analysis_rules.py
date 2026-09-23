"""Production V7 rules, copied from the existing BigLotto product implementation.

score_number/build_reasons were AST-compared with both local 539 sources.
No loaders, research modules, database settings or API dependencies are imported.
Integer score increments make Python round(score, 1) equal verified Dart rounding;
this assertion is specific to V7, not a general cross-language rounding rule.
"""

def score_number(r10, r30, r50, r100):
    score = 50.0
    reasons = []
    warnings = []
    if 1.1 <= r50 <= 1.2:
        score += 18
        reasons.append('50期穩定偏熱')
    elif 1.2 < r50 < 1.3:
        score += 14
        reasons.append('50期強勢')
    elif 1.05 <= r50 < 1.1:
        score += 8
        reasons.append('50期略強')
    elif r50 < 0.9:
        score -= 5
        warnings.append('50期偏弱')
    if 1.05 <= r100 <= 1.15:
        score += 10
        reasons.append('長期偏熱')
    elif 1.15 < r100 <= 1.25:
        score += 7
        reasons.append('長期強勢')
    elif r100 < 0.9:
        score -= 5
        warnings.append('長期偏冷')
    if r10 >= 1.05 and r30 >= 1.05:
        score += 6
        reasons.append('短中共振')
    if r30 >= 1.0 and r50 >= 1.0 and (r100 >= 1.0):
        score += 5
        reasons.append('三週期共振')
    if r30 >= 1.0 and r50 >= 1.0 and (r100 >= 1.0):
        score += 4
        reasons.append('中長期一致')
    if r100 < 1.0 and r50 <= 1.05 and (r30 >= 1.0) and (r10 >= r30):
        score += 3
        reasons.append('回補訊號')
    if r10 > r30 and r30 > r50:
        score += 3
        reasons.append('動能加速')
    if r10 >= 1.8 and r30 >= 1.4:
        score -= 8
        warnings.append('短中期過熱')
    if r10 >= 2.2 and r30 >= 1.6:
        score -= 6
        warnings.append('嚴重過熱')
    score = max(0, min(100, round(score, 1)))
    return (score, reasons, warnings)


def build_reasons(r10, r30, r50, r100):
    reasons = []
    warnings = []
    if r10 >= 1.05 and r30 >= 1.05:
        reasons.append('短中共振')
    if r30 >= 1.0 and r50 >= 1.0 and (r100 >= 1.0):
        reasons.append('三週期共振')
    if r50 >= 1.1:
        reasons.append('50期偏強')
    if r100 >= 1.05:
        reasons.append('長期偏熱')
    if r100 < 1.0 and r50 <= 1.05 and (r30 >= 1.0) and (r10 >= r30):
        reasons.append('長冷短熱回補')
    if r10 > r30 and r30 > r50:
        reasons.append('動能加速')
    if r10 > r100:
        reasons.append('短期高於長期')
    if r50 < 0.9:
        warnings.append('50期偏弱')
    if r100 < 0.9:
        warnings.append('長期偏冷')
    if r10 >= 1.8 and r30 >= 1.4:
        warnings.append('短中期過熱')
    if r10 >= 2.2 and r30 >= 1.6:
        warnings.append('嚴重過熱')
    return (reasons, warnings)


def classify_grade(score):
    if score >= 75:
        return 'A'
    if score >= 65:
        return 'B'
    if score >= 55:
        return 'C'
    if score >= 45:
        return 'D'
    return 'E'


def classify_momentum_type(r10, r30, r50, r100):
    if r10 >= 1.8 and r30 >= 1.5 and (r50 >= 1.4):
        return '過熱警戒'
    if r10 >= 1.5 and r30 >= 1.3 and (r50 >= 1.2):
        return '高檔延續'
    if r10 >= 1.5 and r30 >= 1.2 and (r100 < 1.0):
        return '加速上升'
    if r10 >= 1.2 and r30 >= 1.1 and (r50 >= 1.0) and (r100 >= 1.0):
        return '穩定強勢'
    if r10 >= 1.2 and r30 >= 1.0 and (r100 < 1.0):
        return '回補啟動'
    if r10 < 1.0 and r30 >= 1.1:
        return '動能衰退'
    return '一般'


def frozen_long_hot_score(r50, r100):
    return r50 * 0.5 + r100 * 0.5
