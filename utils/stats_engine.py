"""
stats_engine.py
----------------
محرك إحصائي عام لمقارنة توزيع متغيرات رقمية بين فئتين (مثلاً: الفترة الشتوية
مقابل الفترة الصيفية)، مع اختيار تلقائي للاختبار المناسب واستخلاص تفسير نصي.

المنهجية لكل متغير رقمي:
1. إحصاء وصفي لكل فئة (n, mean, std, median, min, max, Q1, Q3)
2. اختبار التوزيع الطبيعي (D'Agostino-Pearson، أو Shapiro لعينات صغيرة n<50)
3. اختيار الاختبار:
     - عيّنتان طبيعيتا التوزيع -> Levene لتجانس التباين -> t-test (مناسب/Welch)
     - غير ذلك -> Mann-Whitney U (اختبار لا معلمي)
4. حجم الأثر: Cohen's d للعيّنات المعلمية، أو r = Z/sqrt(N) لـ Mann-Whitney
5. تفسير نصي تلقائي بالعربية
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from scipy import stats


def _normality_test(x: np.ndarray):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 8:
        return True, 1.0  # عيّنة صغيرة جداً لاختبار موثوق، نفترض طبيعية بحذر
    if len(x) <= 50:
        stat, p = stats.shapiro(x)
    else:
        stat, p = stats.normaltest(x)
    return p > 0.05, p


def _effect_size_label(d: float, lang: str = "ar") -> str:
    d = abs(d)
    labels = {
        "ar": ["ضعيف جداً / مهمل", "صغير", "متوسط", "كبير"],
        "fr": ["négligeable", "faible", "modéré", "important"],
    }
    L = labels.get(lang, labels["ar"])
    if d < 0.2:
        return L[0]
    if d < 0.5:
        return L[1]
    if d < 0.8:
        return L[2]
    return L[3]


def compare_two_groups(series: pd.Series, group: pd.Series, group_a: str, group_b: str,
                        lang: str = "ar") -> dict:
    """يقارن قيم عمود رقمي واحد بين فئتين من عمود تصنيفي."""
    a = pd.to_numeric(series[group == group_a], errors="coerce").dropna()
    b = pd.to_numeric(series[group == group_b], errors="coerce").dropna()

    err_msg = {
        "ar": "عدد العيّنات غير كافٍ لإجراء اختبار موثوق (يلزم 3 على الأقل في كل فئة).",
        "fr": "Effectif insuffisant pour un test fiable (minimum 3 par groupe requis).",
    }
    if len(a) < 3 or len(b) < 3:
        return {"error": err_msg.get(lang, err_msg["ar"])}

    norm_a, p_norm_a = _normality_test(a.values)
    norm_b, p_norm_b = _normality_test(b.values)
    both_normal = norm_a and norm_b

    test_names = {
        "ar": {
            "t_eq": "t-test لعيّنتين مستقلتين (تباين متجانس)",
            "t_welch": "t-test لعيّنتين مستقلتين (تصحيح Welch)",
            "mwu": "Mann-Whitney U (لا معلمي)",
        },
        "fr": {
            "t_eq": "Test t de Student (variances égales)",
            "t_welch": "Test t de Welch (variances inégales)",
            "mwu": "Test U de Mann-Whitney (non paramétrique)",
        },
    }
    TN = test_names.get(lang, test_names["ar"])

    if both_normal:
        _, p_lev = stats.levene(a, b)
        equal_var = p_lev > 0.05
        stat, pval = stats.ttest_ind(a, b, equal_var=equal_var)
        test_name = TN["t_eq"] if equal_var else TN["t_welch"]
        pooled_std = np.sqrt(((len(a) - 1) * a.std(ddof=1) ** 2 + (len(b) - 1) * b.std(ddof=1) ** 2)
                              / (len(a) + len(b) - 2))
        effect = (a.mean() - b.mean()) / pooled_std if pooled_std > 0 else 0.0
        effect_name = "Cohen's d"
    else:
        stat, pval = stats.mannwhitneyu(a, b, alternative="two-sided")
        test_name = TN["mwu"]
        n = len(a) + len(b)
        z = stats.norm.ppf(1 - pval / 2) if pval > 0 else 0.0
        effect = z / np.sqrt(n)
        effect_name = "r (Wilcoxon effect size)" if lang != "fr" else "r (taille d'effet de Wilcoxon)"

    significant = pval < 0.05

    direction = None
    if significant:
        higher = {"ar": "أعلى", "fr": "supérieure"}
        lower = {"ar": "أقل", "fr": "inférieure"}
        direction = higher[lang] if a.mean() > b.mean() else lower[lang]

    return {
        "n_a": len(a), "n_b": len(b),
        "mean_a": float(a.mean()), "std_a": float(a.std(ddof=1)),
        "median_a": float(a.median()), "q1_a": float(a.quantile(.25)), "q3_a": float(a.quantile(.75)),
        "mean_b": float(b.mean()), "std_b": float(b.std(ddof=1)),
        "median_b": float(b.median()), "q1_b": float(b.quantile(.25)), "q3_b": float(b.quantile(.75)),
        "min_a": float(a.min()), "max_a": float(a.max()),
        "min_b": float(b.min()), "max_b": float(b.max()),
        "normal_a": norm_a, "p_norm_a": float(p_norm_a),
        "normal_b": norm_b, "p_norm_b": float(p_norm_b),
        "test_name": test_name,
        "statistic": float(stat),
        "p_value": float(pval),
        "significant": bool(significant),
        "effect_size": float(effect),
        "effect_name": effect_name,
        "effect_label": _effect_size_label(effect, lang),
        "direction": direction,
        "group_a": group_a, "group_b": group_b,
    }


def interpret_result(var_name: str, res: dict, unit: str = "", lang: str = "ar") -> str:
    """يولّد جملة تفسيرية بلغة مختارة (ar/fr) للنتيجة."""
    if "error" in res:
        return f"{var_name}: {res['error']}"

    u = f" {unit}" if unit else ""

    if lang == "fr":
        if res["significant"]:
            txt = (
                f"L'analyse de {var_name} révèle une différence statistiquement "
                f"significative entre les deux périodes ({res['test_name']}, "
                f"p = {res['p_value']:.4f}). La valeur moyenne en {res['group_a']} "
                f"({res['mean_a']:.2f}{u}) est {res['direction']} à celle observée "
                f"en {res['group_b']} ({res['mean_b']:.2f}{u}). Taille d'effet "
                f"{res['effect_label']} ({res['effect_name']} = {res['effect_size']:.2f})."
            )
        else:
            txt = (
                f"L'analyse de {var_name} ne révèle pas de différence "
                f"statistiquement significative entre les deux périodes "
                f"({res['test_name']}, p = {res['p_value']:.4f}). Les moyennes "
                f"sont comparables : {res['group_a']} = {res['mean_a']:.2f}{u}, "
                f"{res['group_b']} = {res['mean_b']:.2f}{u}."
            )
        return txt

    # الافتراضي: العربية
    if res["significant"]:
        txt = (
            f"أظهر تحليل {var_name} فرقاً ذا دلالة إحصائية بين الفترتين "
            f"({res['test_name']}، p = {res['p_value']:.4f}). "
            f"كانت القيمة المتوسطة في {res['group_a']} ({res['mean_a']:.2f}{u}) "
            f"{res['direction']} منها في {res['group_b']} ({res['mean_b']:.2f}{u}). "
            f"حجم الأثر {res['effect_label']} ({res['effect_name']} = {res['effect_size']:.2f})."
        )
    else:
        txt = (
            f"لم يُظهر تحليل {var_name} فرقاً ذا دلالة إحصائية بين الفترتين "
            f"({res['test_name']}، p = {res['p_value']:.4f}). "
            f"المتوسطات متقاربة: {res['group_a']} = {res['mean_a']:.2f}{u}، "
            f"{res['group_b']} = {res['mean_b']:.2f}{u}."
        )
    return txt


def run_full_analysis(df: pd.DataFrame, group_col: str, value_cols: list[str],
                       group_a: str, group_b: str, units: dict | None = None,
                       lang: str = "ar") -> dict:
    """يشغّل المقارنة على كل الأعمدة الرقمية المطلوبة ويعيد قاموس نتائج + تفسيرات."""
    units = units or {}
    results = {}
    for col in value_cols:
        res = compare_two_groups(df[col], df[group_col], group_a, group_b, lang)
        res["interpretation"] = interpret_result(col, res, units.get(col, ""), lang)
        results[col] = res
    return results


def stratified_analysis(df: pd.DataFrame, group_col: str, value_cols: list[str],
                         group_a: str, group_b: str, strat_col: str,
                         units: dict | None = None, lang: str = "ar") -> dict:
    """يكرر المقارنة داخل كل فئة من عمود إضافي (مثلاً الجنس) لكشف تفاعلات محتملة."""
    out = {}
    for level in df[strat_col].dropna().unique():
        sub = df[df[strat_col] == level]
        out[level] = run_full_analysis(sub, group_col, value_cols, group_a, group_b, units, lang)
    return out
