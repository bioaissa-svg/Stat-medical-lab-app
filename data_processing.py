"""
data_processing.py
-------------------
تنظيف تلقائي لملفات نتائج التحاليل المخبرية (xlsx/csv).

يعالج المشاكل الشائعة في ملفات المخبر:
- صفوف عناوين إضافية قبل رأس الجدول الحقيقي (مثل "12---02" فوق الأعمدة الفعلية)
- أعمدة "متبادلة" تمثل نفس المتغير مقسّماً حسب فئة (مثل P.hivernale / P.estivale
  حيث كل صف يملأ عموداً واحداً فقط) -> يتم دمجها في عمود واحد Saison
- أعمدة مكررة أو بلا اسم يعيد pandas تسميتها تلقائياً (Unnamed: 0 ...)
- تحويل الأعمدة الرقمية (نصية بسبب فواصل عشرية أو قيم فارغة) إلى float/int فعلية
"""

from __future__ import annotations
import pandas as pd
import numpy as np
import re


def _find_header_row(raw: pd.DataFrame, max_scan: int = 10) -> int:
    """
    يبحث عن أول صف يحتوي على عدد كافٍ من الخلايا النصية غير الفارغة
    ولا يحتوي على تواريخ/أرقام فقط -> يُعتبر رأس الجدول الحقيقي.
    """
    best_row, best_score = 0, -1
    for i in range(min(max_scan, len(raw))):
        row = raw.iloc[i]
        non_null = row.notna().sum()
        # نفضل صفاً بخلايا نصية متعددة وغير مكررة
        text_cells = sum(isinstance(v, str) and len(v.strip()) > 0 for v in row)
        score = text_cells * 2 + non_null
        if text_cells >= 3 and score > best_score:
            best_score = score
            best_row = i
    return best_row


def _dedupe_columns(cols: list[str]) -> list[str]:
    seen = {}
    out = []
    for c in cols:
        is_blank = c is None or (isinstance(c, float) and pd.isna(c))
        c = "" if is_blank else str(c).strip()
        if c == "" or c.lower().startswith("unnamed") or c.lower() == "nan":
            c = "Date"
        if c in seen:
            seen[c] += 1
            out.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            out.append(c)
    return out


def detect_exclusive_pairs(df: pd.DataFrame, candidate_cols: list[str]) -> list[tuple]:
    """
    يكتشف أزواج أعمدة "متبادلة" (كل صف يملأ عموداً واحداً فقط من الاثنين، أبداً
    لا يمتلئان معاً ولا يفرغان معاً) -> مرشحة للدمج في عمود فئوي واحد (مثل الموسم).
    """
    pairs = []
    for i, a in enumerate(candidate_cols):
        for b in candidate_cols[i + 1:]:
            both = df[a].notna() & df[b].notna()
            neither = df[a].isna() & df[b].isna()
            if both.sum() == 0 and neither.sum() == 0:
                pairs.append((a, b))
    return pairs


def load_and_clean(file, merged_col_name: str = "Saison") -> dict:
    """
    يقرأ ملف xlsx/csv ويعيد قاموساً:
        {
          "df": DataFrame نظيف وجاهز للتحليل,
          "warnings": [رسائل توضيحية عن التعديلات التي تمت],
          "numeric_cols": [أسماء الأعمدة الرقمية المكتشفة],
          "categorical_cols": [أسماء الأعمدة الفئوية],
        }
    """
    warnings = []

    if hasattr(file, "name") and file.name.lower().endswith(".csv"):
        raw = pd.read_csv(file, header=None)
    else:
        raw = pd.read_excel(file, header=None)

    header_row = _find_header_row(raw)
    if header_row > 0:
        warnings.append(
            f"تم تجاهل {header_row} صف/صفوف قبل رأس الجدول (عناوين/فراغات) "
            f"واعتماد السطر {header_row + 1} كرأس فعلي."
        )

    df = raw.iloc[header_row + 1:].reset_index(drop=True)
    df.columns = _dedupe_columns(list(raw.iloc[header_row]))

    # إسقاط الأعمدة الفارغة كلياً
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    if empty_cols:
        df = df.drop(columns=empty_cols)
        warnings.append(f"تم حذف أعمدة فارغة بالكامل: {', '.join(empty_cols)}")

    # اكتشاف ودمج الأعمدة المتبادلة (نصية، عدد قيم فريدة قليل)
    # ملاحظة: عند القراءة بـ header=None تكون كل الأعمدة object/StringDtype،
    # لذا نستبعد فقط ما هو رقمي أو تاريخ فعلاً بدل الاعتماد على == object
    text_cols = [
        c for c in df.columns
        if not pd.api.types.is_numeric_dtype(df[c])
        and not pd.api.types.is_datetime64_any_dtype(df[c])
    ]
    small_domain_cols = [c for c in text_cols if df[c].dropna().nunique() <= 6]
    pairs = detect_exclusive_pairs(df, small_domain_cols)

    season_hint = {"h": "Hivernale", "e": "Estivale", "hivernale": "Hivernale",
                    "estivale": "Estivale", "hiver": "Hivernale", "été": "Estivale",
                    "ete": "Estivale", "winter": "Hivernale", "summer": "Estivale"}

    for a, b in pairs:
        new_series = df[a].where(df[a].notna(), df[b])
        new_series = new_series.astype(str).str.strip()
        col_name = merged_col_name if merged_col_name not in df.columns else f"{a}_{b}"
        # إن كانت القيم رموزاً معروفة لموسم، نستبدلها بأسماء واضحة
        lowered = new_series.str.lower()
        if lowered.isin(season_hint.keys()).mean() > 0.8:
            new_series = lowered.map(season_hint).fillna(new_series)
        df[col_name] = new_series
        df = df.drop(columns=[a, b])
        warnings.append(
            f"الأعمدة '{a}' و '{b}' متبادلة (لا تمتلئان معاً أبداً) -> تم دمجها في عمود '{col_name}'."
        )

    # محاولة تحويل كل عمود متبقٍ إلى رقمي إن أمكن
    numeric_cols, categorical_cols = [], []
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_datetime64_any_dtype(df[c]):
            cleaned = (
                df[c].astype(str)
                .str.strip()
                .str.replace(",", ".", regex=False)
                .replace({"nan": np.nan, "": np.nan, "None": np.nan})
            )
            converted = pd.to_numeric(cleaned, errors="coerce")
            # إن نجح التحويل لأغلب القيم غير الفارغة نعتبره عمود رقمي
            non_null = cleaned.notna().sum()
            if non_null > 0 and converted.notna().sum() / non_null >= 0.9:
                df[c] = converted
                numeric_cols.append(c)
            else:
                df[c] = df[c].astype(str).str.strip()
                categorical_cols.append(c)
        elif pd.api.types.is_numeric_dtype(df[c]):
            numeric_cols.append(c)
        else:
            categorical_cols.append(c)

    # محاولة تحويل عمود تاريخ إن وجد (يحتوي كلمة date/تاريخ أو Unnamed الأولى)
    for c in df.columns:
        if re.search(r"date|تاريخ", str(c), re.IGNORECASE):
            df[c] = pd.to_datetime(df[c], errors="coerce")

    df = df.reset_index(drop=True)

    return {
        "df": df,
        "warnings": warnings,
        "numeric_cols": numeric_cols,
        "categorical_cols": categorical_cols,
    }
