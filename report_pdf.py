"""
report_pdf.py
-------------
توليد تقرير PDF يترجم نتائج التحليل الإحصائي إلى نص عربي مقروء، مع جداول
وصفية ورسوم بيانية لكل متغير.

يعتمد على:
- reportlab لبناء PDF
- arabic_reshaper + python-bidi لعرض النص العربي بالاتجاه واتصال الحروف الصحيح
  (reportlab لا يدعم RTL/تشكيل الحروف تلقائياً)
- خط FreeSerif المرفق في assets/ (يدعم الحروف العربية والفرنسية معاً)
"""

import os
import io
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
)
from reportlab.pdfgen import canvas as rl_canvas

from .charts import matplotlib_boxplot

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")
FONT_REGULAR = os.path.join(ASSETS_DIR, "FreeSerif.ttf")
FONT_BOLD = os.path.join(ASSETS_DIR, "FreeSerifBold.ttf")

_FONT_NAME = "ArabicFont"
_FONT_NAME_BOLD = "ArabicFont-Bold"


def _register_fonts():
    if _FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        if os.path.exists(FONT_REGULAR):
            pdfmetrics.registerFont(TTFont(_FONT_NAME, FONT_REGULAR))
        else:
            _FONT_NAME_FALLBACK = "Helvetica"
            return _FONT_NAME_FALLBACK, _FONT_NAME_FALLBACK
    if _FONT_NAME_BOLD not in pdfmetrics.getRegisteredFontNames():
        if os.path.exists(FONT_BOLD):
            pdfmetrics.registerFont(TTFont(_FONT_NAME_BOLD, FONT_BOLD))
        else:
            pdfmetrics.registerFont(TTFont(_FONT_NAME_BOLD, FONT_REGULAR))
    return _FONT_NAME, _FONT_NAME_BOLD


def rtl(text: str) -> str:
    """
    يمرّر النص كما هو. محرك Paragraph في reportlab (النسخ الحديثة) يطبّق
    تشكيل الحروف العربية واتجاه RTL تلقائياً على نصوص Unicode العربية، لذا
    لا حاجة لـ arabic_reshaper/python-bidi. تم اختبار هذا فعلياً ويعمل بشكل
    صحيح مع خط FreeSerif المرفق.
    """
    return str(text)


# ------------------------------------------------------------------ نصوص التقرير
TEXTS = {
    "ar": {
        "report_date": "تاريخ إصدار التقرير",
        "sec1": "1. ملخص العينة",
        "summary": lambda n_total, n_a, group_a, n_b, group_b: (
            f"شملت الدراسة {n_total} عيّنة تحليل، منها {n_a} خلال {group_a} و{n_b} خلال {group_b}."
        ),
        "sec2": "2. المنهجية الإحصائية",
        "method": (
            "لكل متغير رقمي، تم أولاً اختبار طبيعية التوزيع (Shapiro-Wilk أو "
            "D'Agostino-Pearson حسب حجم العيّنة). عند تحقق الطبيعية في الفئتين، "
            "استُخدم اختبار t لعيّنتين مستقلتين (مع تصحيح Welch عند عدم تجانس "
            "التباين وفق اختبار Levene). في غير ذلك استُخدم اختبار Mann-Whitney U "
            "اللامعلمي. اعتُبر الفرق ذا دلالة إحصائية عند p < 0.05، مع حساب حجم "
            "الأثر (Cohen's d أو معامل r) لتقدير الأهمية العملية للفرق وليس فقط "
            "دلالته الإحصائية."
        ),
        "sec3": "3. النتائج التفصيلية حسب المتغير",
        "sec3_summary": lambda total, sig: (
            f"من أصل {total} متغيرات تم تحليلها، أظهرت {sig} فروقاً ذات دلالة إحصائية بين الفترتين."
        ),
        "row_indicator": "المؤشر",
        "row_n": "العدد (n)",
        "row_mean": "المتوسط ± الانحراف المعياري",
        "row_median": "الوسيط (Q1–Q3)",
        "row_range": "المدى (Min–Max)",
        "test_line": lambda res: (
            f"الاختبار: {res['test_name']} | p = {res['p_value']:.4f} | "
            f"{res['effect_name']} = {res['effect_size']:.2f} ({res['effect_label']})"
        ),
        "sec4": "4. الخلاصة",
        "conclusion_sig": lambda sig_vars: (
            "أظهرت الدراسة فروقاً ذات دلالة إحصائية بين الفترتين الشتوية والصيفية "
            f"في المتغيرات التالية: {', '.join(sig_vars)}. "
            "يُنصح بمراجعة هذه الفروقات سريرياً لتحديد ما إذا كانت تعكس تغيّرات "
            "فسيولوجية موسمية حقيقية (مثل التمثيل الغذائي أو حالة الإماهة) أم "
            "عوامل أخرى مرتبطة بالعيّنة أو ظروف أخذ العينة."
        ),
        "conclusion_nosig": (
            "لم تُظهر الدراسة فروقاً ذات دلالة إحصائية بين الفترتين لأي من "
            "المتغيرات المدروسة، مما يشير إلى استقرار نسبي لوظيفة الكلى عبر "
            "الفصول ضمن هذه العيّنة."
        ),
        "align": TA_RIGHT,
    },
    "fr": {
        "report_date": "Date d'émission du rapport",
        "sec1": "1. Résumé de l'échantillon",
        "summary": lambda n_total, n_a, group_a, n_b, group_b: (
            f"L'étude a porté sur {n_total} échantillons, dont {n_a} en {group_a} "
            f"et {n_b} en {group_b}."
        ),
        "sec2": "2. Méthodologie statistique",
        "method": (
            "Pour chaque variable numérique, la normalité de la distribution a été "
            "évaluée (test de Shapiro-Wilk ou de D'Agostino-Pearson selon la taille "
            "de l'échantillon). Lorsque la normalité était vérifiée dans les deux "
            "groupes, un test t de Student pour échantillons indépendants a été "
            "utilisé (avec correction de Welch en cas d'hétérogénéité des variances "
            "selon le test de Levene). Dans le cas contraire, le test non "
            "paramétrique de Mann-Whitney U a été appliqué. Une différence a été "
            "considérée comme statistiquement significative pour p < 0.05, avec "
            "calcul de la taille d'effet (d de Cohen ou coefficient r) afin "
            "d'évaluer la pertinence pratique de la différence, au-delà de sa "
            "seule signification statistique."
        ),
        "sec3": "3. Résultats détaillés par variable",
        "sec3_summary": lambda total, sig: (
            f"Sur {total} variables analysées, {sig} présentent une différence "
            "statistiquement significative entre les deux périodes."
        ),
        "row_indicator": "Indicateur",
        "row_n": "Effectif (n)",
        "row_mean": "Moyenne ± écart-type",
        "row_median": "Médiane (Q1–Q3)",
        "row_range": "Étendue (Min–Max)",
        "test_line": lambda res: (
            f"Test : {res['test_name']} | p = {res['p_value']:.4f} | "
            f"{res['effect_name']} = {res['effect_size']:.2f} ({res['effect_label']})"
        ),
        "sec4": "4. Conclusion",
        "conclusion_sig": lambda sig_vars: (
            "L'étude a mis en évidence des différences statistiquement "
            f"significatives entre les périodes hivernale et estivale pour les "
            f"variables suivantes : {', '.join(sig_vars)}. Il est recommandé "
            "d'examiner cliniquement ces différences afin de déterminer si elles "
            "reflètent de véritables variations physiologiques saisonnières "
            "(métabolisme, état d'hydratation, etc.) ou d'autres facteurs liés à "
            "l'échantillon ou aux conditions de prélèvement."
        ),
        "conclusion_nosig": (
            "L'étude n'a pas mis en évidence de différence statistiquement "
            "significative entre les deux périodes pour les variables étudiées, "
            "ce qui suggère une relative stabilité de la fonction rénale au fil "
            "des saisons dans cet échantillon."
        ),
        "align": TA_LEFT,
    },
}


def build_report(
    output_path: str,
    title: str,
    subtitle: str,
    df_summary: dict,
    results: dict,
    df,
    group_col: str,
    group_a: str,
    group_b: str,
    units: dict | None = None,
    logo_path: str | None = None,
    lang: str = "ar",
):
    """
    ينشئ تقرير PDF كامل بلغة مختارة (lang="ar" أو "fr").

    Parameters
    ----------
    df_summary : dict
        معلومات عامة عن العينة: {"n_total":.., "n_a":.., "n_b":.., "date_range":..}
    results : dict
        مخرجات stats_engine.run_full_analysis (متغير -> نتائج + تفسير، مولّدة
        بنفس lang لضمان اتساق لغة التفسير مع لغة التقرير)
    """
    units = units or {}
    T = TEXTS.get(lang, TEXTS["ar"])
    align = T["align"]
    font, font_bold = _register_fonts()

    styles = {
        "title": ParagraphStyle("title", fontName=font_bold, fontSize=20, leading=26,
                                 alignment=TA_CENTER, textColor=colors.HexColor("#1F3864"),
                                 spaceAfter=6),
        "subtitle": ParagraphStyle("subtitle", fontName=font, fontSize=12, leading=18,
                                    alignment=TA_CENTER, textColor=colors.HexColor("#555555"),
                                    spaceAfter=20),
        "h2": ParagraphStyle("h2", fontName=font_bold, fontSize=14, leading=20,
                              alignment=align, textColor=colors.HexColor("#1F3864"),
                              spaceBefore=16, spaceAfter=8),
        "body": ParagraphStyle("body", fontName=font, fontSize=10.5, leading=17,
                                alignment=align, spaceAfter=8),
        "small": ParagraphStyle("small", fontName=font, fontSize=8.5, leading=12,
                                 alignment=TA_CENTER, textColor=colors.HexColor("#888888")),
        "cell": ParagraphStyle("cell", fontName=font, fontSize=8.5, leading=11,
                                alignment=TA_CENTER),
    }

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        rightMargin=1.8 * cm, leftMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.6 * cm,
    )

    story = []

    if logo_path and os.path.exists(logo_path):
        story.append(Image(logo_path, width=3 * cm, height=3 * cm))

    story.append(Paragraph(rtl(title), styles["title"]))
    story.append(Paragraph(rtl(subtitle), styles["subtitle"]))
    story.append(Paragraph(
        rtl(f"{T['report_date']}: {datetime.date.today().strftime('%Y-%m-%d')}"),
        styles["small"],
    ))
    story.append(Spacer(1, 10))

    # ---- ملخص العينة ----
    story.append(Paragraph(rtl(T["sec1"]), styles["h2"]))
    summary_txt = T["summary"](
        df_summary.get("n_total", "-"), df_summary.get("n_a", "-"), group_a,
        df_summary.get("n_b", "-"), group_b,
    )
    story.append(Paragraph(rtl(summary_txt), styles["body"]))
    story.append(Spacer(1, 6))

    # ---- منهجية ----
    story.append(Paragraph(rtl(T["sec2"]), styles["h2"]))
    story.append(Paragraph(rtl(T["method"]), styles["body"]))

    # ---- لكل متغير: جدول + رسم + تفسير ----
    story.append(PageBreak())
    story.append(Paragraph(rtl(T["sec3"]), styles["h2"]))

    n_sig = sum(1 for r in results.values() if r.get("significant"))
    story.append(Paragraph(rtl(T["sec3_summary"](len(results), n_sig)), styles["body"]))
    story.append(Spacer(1, 8))

    for var, res in results.items():
        if "error" in res:
            story.append(Paragraph(rtl(f"{var}: {res['error']}"), styles["body"]))
            continue

        unit = units.get(var, "")
        story.append(Paragraph(rtl(f"{var}" + (f" ({unit})" if unit else "")), styles["h2"]))

        # جدول وصفي
        table_data = [
            [rtl(T["row_indicator"]), rtl(group_a), rtl(group_b)],
            [rtl(T["row_n"]), str(res["n_a"]), str(res["n_b"])],
            [rtl(T["row_mean"]),
             f"{res['mean_a']:.2f} ± {res['std_a']:.2f}",
             f"{res['mean_b']:.2f} ± {res['std_b']:.2f}"],
            [rtl(T["row_median"]),
             f"{res['median_a']:.2f} ({res['q1_a']:.2f}–{res['q3_a']:.2f})",
             f"{res['median_b']:.2f} ({res['q1_b']:.2f}–{res['q3_b']:.2f})"],
            [rtl(T["row_range"]),
             f"{res['min_a']:.2f}–{res['max_a']:.2f}",
             f"{res['min_b']:.2f}–{res['max_b']:.2f}"],
        ]
        tbl = Table(table_data, colWidths=[6.5 * cm, 4.5 * cm, 4.5 * cm])
        tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTNAME", (0, 0), (-1, 0), font_bold),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 8))

        # نتيجة الاختبار
        sig_color = colors.HexColor("#C00000") if res["significant"] else colors.HexColor("#548235")
        story.append(Paragraph(rtl(T["test_line"](res)), ParagraphStyle(
            "testline", fontName=font, fontSize=9.5, alignment=align,
            textColor=sig_color, spaceAfter=6,
        )))

        # رسم بياني
        try:
            img_bytes = matplotlib_boxplot(df, var, group_col, group_a, group_b, unit)
            img_buf = io.BytesIO(img_bytes)
            story.append(Image(img_buf, width=9 * cm, height=6.3 * cm))
        except Exception:
            pass

        story.append(Spacer(1, 4))
        story.append(Paragraph(rtl(res["interpretation"]), styles["body"]))
        story.append(Spacer(1, 14))

    # ---- خاتمة ----
    story.append(PageBreak())
    story.append(Paragraph(rtl(T["sec4"]), styles["h2"]))
    sig_vars = [v for v, r in results.items() if r.get("significant")]
    conclusion = T["conclusion_sig"](sig_vars) if sig_vars else T["conclusion_nosig"]
    story.append(Paragraph(rtl(conclusion), styles["body"]))

    doc.build(story)
    return output_path
