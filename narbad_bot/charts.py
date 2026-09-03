"""تولید نمودارهای رشد قدرت با matplotlib + فونت فارسی."""
from __future__ import annotations

import io
import os

import arabic_reshaper
import matplotlib
from bidi.algorithm import get_display

matplotlib.use("Agg")

from matplotlib import font_manager  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

_FONT_PATH = os.path.join(os.path.dirname(__file__),
                          "assets", "fonts", "Vazirmatn-Regular.ttf")
if os.path.exists(_FONT_PATH):
    font_manager.fontManager.addfont(_FONT_PATH)
    plt.rcParams["font.family"] = "Vazirmatn"
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = "#1c1c2e"
plt.rcParams["axes.facecolor"] = "#26263c"
plt.rcParams["savefig.facecolor"] = "#1c1c2e"


def _style(ax) -> None:
    ax.tick_params(colors="#e8e8f0", labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#4a4a6a")
    ax.grid(color="#3a3a55", alpha=0.6, linestyle="--")
    ax.set_facecolor("#26263c")


def _clean(text: str) -> str:
    """آماده‌سازی متن فارسی برای matplotlib:
    حذف ایموجی‌ها + شکل‌دهی حروف + جهت راست‌به‌چپ."""
    text = "".join(ch for ch in text if ord(ch) < 0x2500)
    return get_display(arabic_reshaper.reshape(text))


def growth_chart_png(history: list[dict], title: str) -> bytes | None:
    """نمودار خطی رشد قدرت؛ خروجی: بایت‌های PNG یا None اگر داده کم باشد."""
    points = [(h["ts"], h["power"]) for h in history if h["power"] > 0]
    if len(points) < 2:
        return None

    import datetime

    times = [datetime.datetime.fromtimestamp(ts) for ts, _ in points]
    powers = [p for _, p in points]

    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=110)
    ax.plot(times, powers, color="#ff6b35", linewidth=2.4, marker="o",
            markersize=4.5, markerfacecolor="#ffd166", markeredgecolor="none")
    ax.fill_between(times, powers, color="#ff6b35", alpha=0.12)
    _style(ax)

    ax.set_title(_clean(title), color="#ffffff", fontsize=13,
                 fontweight="bold", pad=12)
    ax.set_ylabel(_clean("قدرت"), color="#c9c9dd", fontsize=10)
    ax.set_xlabel(_clean("زمان"), color="#c9c9dd", fontsize=10)
    fig.autofmt_xdate()

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def bar_chart_png(labels: list[str], values: list[int], title: str,
                  xlabel: str = "") -> bytes | None:
    """نمودار میله‌ای (مثلاً مقایسهٔ قدرت اتحادیه‌ها)."""
    if not labels or not values:
        return None
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=110)
    colors = ["#ff6b35", "#e63946", "#f4a261", "#2a9d8f", "#457b9d",
              "#9b5de5", "#f15bb5", "#00bbf9"]
    ax.bar(range(len(values)), values,
           color=[colors[i % len(colors)] for i in range(len(values))],
           edgecolor="#ffffff22")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels([_clean(l) for l in labels], rotation=20, ha="right",
                       color="#e8e8f0", fontsize=9)
    _style(ax)
    ax.set_title(_clean(title), color="#ffffff", fontsize=13,
                 fontweight="bold", pad=12)
    ax.set_ylabel(_clean(xlabel or "مقدار"), color="#c9c9dd", fontsize=10)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
