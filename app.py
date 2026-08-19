"""
app.py
------
المنصة التعليمية للتحليل المخبري وتوليد التقارير الطبية.

يسمح للمستخدم بـ:
1. رفع ملف نتائج تحاليل (xlsx/csv) — يُنظَّف تلقائياً حتى لو كان به صفوف
   عناوين إضافية أو أعمدة مكررة/متبادلة.
2. اختيار عمود الفئة (مثل الموسم) والقيم الرقمية المراد مقارنتها.
3. عرض إحصاء وصفي، رسوم بيانية تفاعلية، واختبارات المقارنة (t-test أو
   Mann-Whitney حسب طبيعة التوزيع) مع تفسير نصي تلقائي.
4. تحميل تقرير PDF كامل يترجم النتائج الإحصائية إلى عبارات مقروءة.
"""

import streamlit as st
import pandas as pd
import tempfile
import os

from utils.data_processing import load_and_clean
from utils.stats_engine import run_full_analysis, stratified_analysis
from utils.charts import plotly_boxplot
from utils.report_pdf import build_report

st.set_page_config(
    page_title="Medical Lab Intelligence & PDF Report",
    page_icon="🔬",
    layout="wide",
)

# ---------------------------------------------------------------- الحالة
if "cleaned" not in st.session_state:
    st.session_state.cleaned = None
if "results" not in st.session_state:
    st.session_state.results = None

# ---------------------------------------------------------------- الرأس
st.markdown(
    "<h1 style='text-align:center;'>🔬 المنصة التعليمية للتحليل المخبري "
    "وتوليد التقارير الطبية</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='text-align:center;color:#666;'>ضبط الجودة مع CLSI، تحليل "
    "إحصائي، استخلاص مجالات الرجوع، شامل إمكانية تصدير تقرير PDF.</p>",
    unsafe_allow_html=True,
)
st.divider()

# ---------------------------------------------------------------- رفع الملف
uploaded = st.file_uploader("📂 ارفع ملف نتائج التحاليل (xlsx أو csv)", type=["xlsx", "xls", "csv"])

if uploaded is not None:
    with st.spinner("جاري تنظيف الملف وتحليل بنيته..."):
        try:
            cleaned = load_and_clean(uploaded)
            st.session_state.cleaned = cleaned
        except Exception as e:
            st.error(f"تعذّرت قراءة الملف: {e}")
            st.stop()

    for w in cleaned["warnings"]:
        st.warning(w, icon="⚠️")

    if not cleaned["numeric_cols"]:
        st.error("الملف لا يحتوي على أعمدة رقمية! تحقق من صيغة الملف.")
        st.stop()
    else:
        st.success(f"تم تجهيز {len(cleaned['df'])} صف بنجاح.", icon="✅")

if st.session_state.cleaned is not None:
    cleaned = st.session_state.cleaned
    df = cleaned["df"]
    numeric_cols = cleaned["numeric_cols"]
    categorical_cols = cleaned["categorical_cols"]

    st.divider()
    st.subheader("👁️ معاينة البيانات")
    st.dataframe(df.head(20), use_container_width=True)

    st.divider()
    st.subheader("⚙️ إعداد المقارنة")

    c1, c2, c3 = st.columns(3)
    with c1:
        group_col = st.selectbox("عمود الفئة (مثل الموسم)", categorical_cols,
                                  index=(categorical_cols.index("Saison") if "Saison" in categorical_cols else 0))
    levels = sorted(df[group_col].dropna().unique().tolist())
    with c2:
        group_a = st.selectbox("الفئة الأولى", levels, index=0)
    with c3:
        group_b = st.selectbox("الفئة الثانية", levels, index=min(1, len(levels) - 1))

    default_vals = [c for c in numeric_cols if c.lower() not in ("id",)]
    value_cols = st.multiselect("المتغيرات الرقمية المراد مقارنتها", numeric_cols, default=default_vals)

    strat_col = st.selectbox(
        "تقسيم إضافي اختياري (مثل الجنس) — لكشف تفاعلات محتملة",
        ["بدون"] + [c for c in categorical_cols if c != group_col],
    )

    with st.expander("🔧 وحدات القياس (اختياري، تُستخدم في التقرير فقط)"):
        units = {}
        cols = st.columns(3)
        for i, v in enumerate(value_cols):
            with cols[i % 3]:
                units[v] = st.text_input(f"وحدة {v}", value="", key=f"unit_{v}")

    lang = st.radio("🌐 لغة التقرير والتفسيرات / Langue du rapport", ["Français", "العربية"], horizontal=True)
    lang_code = "ar" if lang == "العربية" else "fr"

    run = st.button("▶️ تشغيل التحليل الإحصائي", type="primary", use_container_width=True)

    if run:
        if group_a == group_b:
            st.error("يجب اختيار فئتين مختلفتين للمقارنة.")
        elif not value_cols:
            st.error("اختر متغيراً رقمياً واحداً على الأقل.")
        else:
            with st.spinner("جاري إجراء الاختبارات الإحصائية..."):
                results = run_full_analysis(df, group_col, value_cols, group_a, group_b, units, lang_code)
                strat_results = None
                if strat_col != "بدون":
                    strat_results = stratified_analysis(df, group_col, value_cols, group_a, group_b,
                                                          strat_col, units, lang_code)
                st.session_state.results = {
                    "results": results, "strat_results": strat_results,
                    "group_col": group_col, "group_a": group_a, "group_b": group_b,
                    "value_cols": value_cols, "units": units, "strat_col": strat_col,
                    "lang_code": lang_code,
                }

    # -------------------------------------------------------- عرض النتائج
    if st.session_state.results is not None:
        R = st.session_state.results
        results = R["results"]

        st.divider()
        n_sig = sum(1 for r in results.values() if r.get("significant"))
        st.subheader(f"📊 النتائج ({n_sig} من أصل {len(results)} متغيرات بفرق ذي دلالة إحصائية)")

        for var, res in results.items():
            if "error" in res:
                st.error(f"**{var}**: {res['error']}")
                continue

            badge = "🔴 دلالة إحصائية" if res["significant"] else "🟢 لا يوجد فرق دال"
            with st.expander(f"**{var}** — {badge} (p = {res['p_value']:.4f})", expanded=res["significant"]):
                cc1, cc2 = st.columns([1, 1.2])
                with cc1:
                    stat_df = pd.DataFrame({
                        R["group_a"]: [res["n_a"], f"{res['mean_a']:.2f} ± {res['std_a']:.2f}",
                                        f"{res['median_a']:.2f}", f"{res['min_a']:.2f}–{res['max_a']:.2f}"],
                        R["group_b"]: [res["n_b"], f"{res['mean_b']:.2f} ± {res['std_b']:.2f}",
                                        f"{res['median_b']:.2f}", f"{res['min_b']:.2f}–{res['max_b']:.2f}"],
                    }, index=["العدد (n)", "المتوسط ± الانحراف", "الوسيط", "المدى"])
                    st.table(stat_df)
                    st.caption(f"الاختبار: {res['test_name']} | {res['effect_name']} = {res['effect_size']:.2f} ({res['effect_label']})")
                with cc2:
                    fig = plotly_boxplot(df, var, R["group_col"], R["units"].get(var, ""))
                    st.plotly_chart(fig, use_container_width=True)

                st.info(res["interpretation"])

        # -------------------------------------------------- تحليل التفاعل
        if R["strat_results"]:
            st.divider()
            st.subheader(f"🔬 تحليل حسب '{R['strat_col']}' (كشف تفاعلات محتملة)")
            for level, lvl_results in R["strat_results"].items():
                st.markdown(f"#### {R['strat_col']} = {level}")
                for var, res in lvl_results.items():
                    if "error" in res:
                        continue
                    badge = "🔴" if res["significant"] else "🟢"
                    st.write(f"{badge} **{var}**: p = {res['p_value']:.4f} — {res['interpretation']}")

        # -------------------------------------------------- تصدير PDF
        st.divider()
        st.subheader("📄 تصدير التقرير")
        default_title = ("Rapport d'analyse statistique de la fonction rénale"
                          if R["lang_code"] == "fr" else "تقرير التحليل الإحصائي لوظائف الكلى")
        default_subtitle = (f"Comparaison {R['group_a']} vs {R['group_b']}"
                             if R["lang_code"] == "fr" else f"مقارنة {R['group_a']} و {R['group_b']}")
        report_title = st.text_input("عنوان التقرير", value=default_title)
        report_subtitle = st.text_input("العنوان الفرعي", value=default_subtitle)

        if st.button("🖨️ توليد تقرير PDF", use_container_width=True):
            with st.spinner("جاري توليد التقرير..."):
                summary = {
                    "n_total": len(df),
                    "n_a": int((df[R["group_col"]] == R["group_a"]).sum()),
                    "n_b": int((df[R["group_col"]] == R["group_b"]).sum()),
                }
                tmp_path = os.path.join(tempfile.gettempdir(), "rapport_analyse.pdf")
                build_report(
                    output_path=tmp_path,
                    title=report_title,
                    subtitle=report_subtitle,
                    df_summary=summary,
                    results=results,
                    df=df,
                    group_col=R["group_col"], group_a=R["group_a"], group_b=R["group_b"],
                    units=R["units"],
                    lang=R["lang_code"],
                )
                with open(tmp_path, "rb") as f:
                    st.download_button(
                        "⬇️ تحميل التقرير (PDF)", data=f.read(),
                        file_name="rapport_analyse_statistique.pdf",
                        mime="application/pdf", use_container_width=True,
                    )
else:
    st.info("👆 ارفع ملف نتائج التحاليل للبدء.")
