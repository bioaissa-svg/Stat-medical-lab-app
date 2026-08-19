"""
charts.py
---------
توليد الرسوم البيانية للمقارنة بين الفترتين، بصيغتين:
- Plotly (للعرض التفاعلي داخل Streamlit)
- Matplotlib (لتضمين صور ثابتة داخل تقرير PDF)
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import io
import pandas as pd

COLORS = {"a": "#4472C4", "b": "#ED7D31"}


def matplotlib_boxplot(df: pd.DataFrame, value_col: str, group_col: str,
                        group_a: str, group_b: str, unit: str = "") -> bytes:
    """يرجع صورة PNG (bytes) لمخطط صندوقي يقارن فئتين لمتغير رقمي واحد."""
    a = pd.to_numeric(df[df[group_col] == group_a][value_col], errors="coerce").dropna()
    b = pd.to_numeric(df[df[group_col] == group_b][value_col], errors="coerce").dropna()

    fig, ax = plt.subplots(figsize=(5, 3.5), dpi=150)
    bp = ax.boxplot([a, b], labels=[group_a, group_b], patch_artist=True, widths=0.5)
    for patch, color in zip(bp["boxes"], [COLORS["a"], COLORS["b"]]):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    ax.set_title(f"{value_col}" + (f" ({unit})" if unit else ""), fontsize=11, fontweight="bold")
    ax.set_ylabel(unit or value_col)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def plotly_boxplot(df: pd.DataFrame, value_col: str, group_col: str, unit: str = ""):
    """يرجع رسم Plotly تفاعلي (لاستخدامه مباشرة داخل st.plotly_chart)."""
    import plotly.express as px
    sub = df[[group_col, value_col]].copy()
    sub[value_col] = pd.to_numeric(sub[value_col], errors="coerce")
    sub = sub.dropna()
    fig = px.box(
        sub, x=group_col, y=value_col, color=group_col, points="outliers",
        color_discrete_sequence=[COLORS["a"], COLORS["b"]],
        title=f"{value_col}" + (f" ({unit})" if unit else ""),
    )
    fig.update_layout(showlegend=False, height=380, margin=dict(t=50, b=30, l=30, r=30))
    return fig
