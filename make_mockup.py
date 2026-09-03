"""ساخت پیش‌نمایش بصری «منوی شیشه‌ای» ربات نبردگاه.

خروجی: narbad_bot/assets/menu_preview.png
تصویری که نشان می‌دهد منوی پایین چت تلگرام (صفحه‌کلید سفارشی) با استایل
گلسمورفیسم، تم نظامی تیره و درخشش نئون آبی/بنفش چه شکلی است.

    python make_mockup.py
"""
from __future__ import annotations

import math
import os
import urllib.request

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, features

ROOT = os.path.dirname(os.path.abspath(__file__))
EMOJI_DIR = os.path.join(ROOT, "narbad_bot", "assets", "emoji")
FONT_PATH = os.path.join(ROOT, "narbad_bot", "assets", "fonts",
                         "Vazirmatn-Regular.ttf")
OUT = os.path.join(ROOT, "narbad_bot", "assets", "menu_preview.png")

HAS_RAQM = features.check("raqm")
if not HAS_RAQM:
    import arabic_reshaper
    from bidi.algorithm import get_display

# ── ایموجی‌های Twemoji (کد یونیکد → فایل 72x72) ───────────────────────
EMOJIS = {
    "base": "1f3e0",        # 🏠
    "attack": "2694",       # ⚔️
    "army": "1fa96",        # 🪖
    "clan": "1f3f0",        # 🏰
    "defense": "1f6e1",     # 🛡️
    "shop": "1f6d2",        # 🛒
    "medal": "1f396",       # 🎖
    "rocket": "1f680",      # 🚀
    "boom": "1f4a5",        # 💥
    "gift": "1f381",        # 🎁
}

W, H = 900, 1620
PHONE = (24, 36, 876, 1584)          # قاب گوشی
CHAT_TOP, CHAT_BOTTOM = 118, 820      # ناحیهٔ چت
KB_TOP = 844                          # شروع صفحه‌کلید

BG_TOP = (9, 13, 26)
BG_BOTTOM = (17, 23, 46)
ACCENTS = {"blue": (59, 130, 246), "violet": (139, 92, 246)}
BUTTONS = [
    ("base", "پایگاه", "blue"),
    ("attack", "حمله", "blue"),
    ("army", "ارتش", "violet"),
    ("clan", "اتحادیه", "violet"),
    ("defense", "دفاع", "blue"),
    ("shop", "فروشگاه", "violet"),
]


def fa(text: str) -> str:
    """متن فارسی برای PIL: اگر raqm نبود، شکل‌دهی دستی."""
    if HAS_RAQM:
        return text
    return get_display(arabic_reshaper.reshape(text))


def load_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


def emoji(code: str, size: int = 64) -> Image.Image:
    """دانلود و بازکردن ایموجی (با کش محلی)."""
    os.makedirs(EMOJI_DIR, exist_ok=True)
    path = os.path.join(EMOJI_DIR, f"{code}.png")
    if not os.path.exists(path):
        url = (f"https://cdn.jsdelivr.net/gh/jdecked/twemoji@15.1.0/"
               f"assets/72x72/{code}.png")
        urllib.request.urlretrieve(url, path)
    im = Image.open(path).convert("RGBA")
    return im.resize((size, size), Image.LANCZOS)


def hex_pattern(size, color=(90, 110, 190, 26), cell=54):
    """الگوی شش‌ضلعی تاکتیکی (سبک نظامی) روی پنل شیشه‌ای."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w, h = size
    r = cell * 0.32
    dh = int(r * 1.5)
    row = 0
    y = 0
    while y < h + cell:
        x = 0 if row % 2 == 0 else cell // 2
        while x < w + cell:
            pts = [(x + r * 1.73 * math.cos(math.pi / 3 * k + math.pi / 6),
                    y + r * 1.73 * math.sin(math.pi / 3 * k + math.pi / 6))
                   for k in range(6)]
            d.polygon(pts, outline=color)
            x += cell
        row += 1
        y += dh + r
    return layer


def v_gradient(size, top, bottom):
    w, h = size
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t)
                                    for i in range(3)))
    return grad.resize((w, h))


def radial_glow(size, color, alpha, blur=80):
    """هالهٔ نئونی نرم برای پس‌زمینه / دکمه‌ها."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w, h = size
    r = min(w, h) // 2
    d.ellipse([w // 2 - r, h // 2 - r, w // 2 + r, h // 2 + r],
              fill=color + (alpha,))
    return layer.filter(ImageFilter.GaussianBlur(blur))


def glossy_button(bg: Image.Image, box, label: str, icon_code: str,
                  accent: tuple, font: ImageFont.FreeTypeFont):
    """یک دکمهٔ شیشه‌ای: هالهٔ نئون + پنل شفاف + حاشیهٔ روشن + ایموجی + برچسب."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    radius = 30

    # ۱) هالهٔ نئونی پشت دکمه
    glow_size = (int(w * 1.25), int(h * 1.5))
    glow = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    gw, gh = glow_size
    g.rounded_rectangle([cx - gw // 2, cy - gh // 2,
                         cx + gw // 2, cy + gh // 2], radius=radius + 14,
                        fill=accent + (150,))
    glow = glow.filter(ImageFilter.GaussianBlur(26))
    bg.alpha_composite(glow)

    # ۲) پنل شیشه‌ای (نیمه‌شفاف)
    panel = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    p = ImageDraw.Draw(panel)
    p.rounded_rectangle(box, radius=radius, fill=(28, 38, 72, 175),
                        outline=accent + (130,), width=3)
    # خط برق بالای پنل (انعکاس شیشه)
    p.rounded_rectangle([x0 + 10, y0 + 4, x1 - 10, y0 + 14], radius=7,
                        fill=(255, 255, 255, 40))
    bg.alpha_composite(panel)

    # ۳) سایهٔ زیر دکمه
    shadow = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    s = ImageDraw.Draw(shadow)
    s.rounded_rectangle([x0 + 8, y0 + 10, x1 - 8, y1 + 22], radius=radius,
                        fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    bg.alpha_composite(shadow)

    # ۴) ایموجی و برچسب
    icon = emoji(icon_code, 58)
    bg.alpha_composite(icon, ((x0 + x1) // 2 - 29, y0 + 22))
    d = ImageDraw.Draw(bg)
    tw = d.textlength(fa(label), font=font)
    d.text(((x0 + x1) / 2 - tw / 2 + 2, y0 + 96 + 2), fa(label),
           font=font, fill=(0, 0, 0, 170), anchor="la")      # سایه
    d.text(((x0 + x1) / 2 - tw / 2, y0 + 96), fa(label),
           font=font, fill=(234, 242, 255, 255), anchor="la")


def _strip_emoji(text: str) -> str:
    return "".join(ch for ch in text if ord(ch) < 0x2500)


def chat_bubble(img: Image.Image, box, text_lines, is_user=False,
                font=None, extra_buttons=None):
    """حباب چت شیشه‌ای + دکمه‌های inline تزئینی."""
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    if is_user:
        fill, outline = (38, 56, 118, 220), (96, 140, 255, 160)
    else:
        fill, outline = (30, 38, 66, 205), (86, 120, 220, 120)
    d.rounded_rectangle(box, radius=26, fill=fill, outline=outline, width=2)

    y = y0 + 18
    for i, line in enumerate(text_lines):
        d.text((x0 + 24, y), fa(_strip_emoji(line)), font=font,
               fill=(226, 233, 248, 255))
        y += font.size + 12

    if extra_buttons:
        bx = int(x0) + 24
        for emoji_key, label in extra_buttons:
            ic = emoji(EMOJIS[emoji_key], 30)
            img.alpha_composite(ic, (bx + 8, int(y) + 4))
            tw = d.textlength(fa(label), font=font_small)
            bw = int(44 + tw + 24)
            d.rounded_rectangle([bx, y, bx + bw, y + 48], radius=24,
                                fill=(48, 74, 148, 235),
                                outline=(112, 152, 255, 150), width=2)
            d.text((bx + 46, y + 12), fa(label), font=font_small,
                   fill=(230, 238, 255, 255))
            bx += bw + 14


def main() -> None:
    # ── پس‌زمینهٔ کلی (گرادیان + هاله‌های نئونی)
    bg = v_gradient((W, H), BG_TOP, BG_BOTTOM).convert("RGBA")
    glow_blue = radial_glow((W, H), ACCENTS["blue"], 60, blur=140)
    glow_violet = radial_glow((W, H), ACCENTS["violet"], 55, blur=150)
    bg.alpha_composite(glow_blue, (-240, 60))
    bg.alpha_composite(glow_violet, (360, 900))

    # ── قاب تلفن
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(frame)
    fd.rounded_rectangle(PHONE, radius=54, fill=(8, 11, 22, 255),
                         outline=(38, 46, 86, 255), width=3)
    bg.alpha_composite(frame)
    chat = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # ماسک برای برش داخل قاب
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(PHONE, radius=54, fill=255)
    bg.paste(chat, (0, 0), mask)  # noqa: B018 — صرفاً برای نگه‌داشتن ترکیب

    font_name = load_font(34)
    font_bubble = load_font(28)
    font_button = load_font(30)
    global font_small
    font_small = load_font(24)
    font_hint = load_font(23)
    font_time = load_font(26)

    # ── سربرگ چت: آواتار و نام ربات
    d0 = ImageDraw.Draw(bg)
    avatar = Image.new("RGBA", (84, 84), (0, 0, 0, 0))
    ad = ImageDraw.Draw(avatar)
    ad.ellipse([0, 0, 84, 84], fill=(46, 62, 130, 255))
    bg.alpha_composite(avatar, (78, 132))
    bg.alpha_composite(emoji("2694", 52), (94, 148))
    d0.text((180, 138), fa("نبردگاه"), font=font_name,
            fill=(240, 245, 255, 255))
    d0.ellipse([182, 190, 192, 200], fill=(60, 220, 130, 255))
    d0.text((200, 178), fa("آنلاین — بازی جنگی"), font=font_hint,
            fill=(120, 200, 160, 255))

    # ── حباب‌های چت
    chat_bubble(bg, (78, 250, 640, 570),
                ["🎖 به نبردگاه خوش آمدی، ژنرال!",
                 "ارتش خود را بساز و به رقیبان",
                 "حمله کن. نبرد در انتظار توست."],
                font=font_bubble,
                extra_buttons=[("boom", "حمله فوری"), ("gift", "جایزهٔ روزانه")])
    chat_bubble(bg, (330, 630, 810, 726),
                ["🚀 حمله را شروع کن!"], is_user=True, font=font_bubble)
    d0.text((W // 2, 790), fa("— منوی اصلی —"), font=font_hint,
            fill=(90, 100, 140, 255), anchor="mm")

    # ── پنل صفحه‌کلید پایین (شیشه‌ای تیره + الگوی شش‌ضلعی تاکتیکی)
    kb_panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    kd = ImageDraw.Draw(kb_panel)
    kd.rounded_rectangle([PHONE[0] + 6, KB_TOP, PHONE[2] - 6, PHONE[3] - 6],
                         radius=44, fill=(12, 17, 32, 238),
                         outline=(56, 66, 116, 120), width=2)
    bg.alpha_composite(kb_panel)

    # الگوی شش‌ضلعی فقط داخل ناحیهٔ پنل
    panel_zone = (PHONE[0] + 8, KB_TOP + 2, PHONE[2] - 8, PHONE[3] - 8)
    pz = (panel_zone[2] - panel_zone[0], panel_zone[3] - panel_zone[1])
    hexes = hex_pattern(pz, color=(110, 130, 210, 16), cell=42)
    hex_mask = Image.new("L", pz, 0)
    ImageDraw.Draw(hex_mask).rounded_rectangle([0, 0, pz[0], pz[1]],
                                               radius=42, fill=255)
    hexes.putalpha(ImageChops.multiply(hexes.getchannel("A"), hex_mask))
    bg.alpha_composite(hexes, (panel_zone[0], panel_zone[1]))

    # ── دکمه‌های شیشه‌ای ۲×۳
    inner_x0, inner_x1 = PHONE[0] + 42, PHONE[2] - 42
    gap = 30
    bw = (inner_x1 - inner_x0 - 2 * gap) // 3
    bh = 158
    rows = [(KB_TOP + 66), (KB_TOP + 66 + bh + 38)]
    for i, (key, label, accent_name) in enumerate(BUTTONS):
        r, c = divmod(i, 3)
        x0 = inner_x0 + c * (bw + gap)
        y0 = rows[r]
        glossy_button(bg, (x0, y0, x0 + bw, y0 + bh), label,
                      EMOJIS[key], ACCENTS[accent_name], font_button)

    # ── راهنمای پایین
    d0.text((W // 2, PHONE[3] - 66),
            fa("بین ۶ دکمه برای شروع انتخاب کن"), font=font_hint,
            fill=(100, 112, 150, 255), anchor="mm")

    bg.convert("RGB").save(OUT)
    print(f"✅ پیش‌نمایش ساخته شد: {OUT}")


if __name__ == "__main__":
    main()
