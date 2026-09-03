"""🛡 سامانه نوین پدافند و دفاع پایگاه نبردگاه.

بخش‌های اصلی منوی دفاع:
    1) 🏰 دفاع پایگاه من     — نمای وضعیت پایگاه، سطح، تک‌تک سازه‌ها و مجموع قدرت دفاعی
    2) 🛒 خرید تجهیزات دفاعی — احداث دیوار، برج دفاعی، پدافند هوایی و سامانه رادار
    3) ⬆️ ارتقای دفاع        — افزایش سطح سازه‌ها، افزایش قدرت دفاعی و پایداری پایگاه
    4) 🔧 تعمیر دفاع         — بازسازی خسارت‌های ناشی از نبردها و بازگرداندن سلامت به ۱۰۰٪
    5) 📊 گزارش دفاع         — گزارش جامع پایگاه، آمار دفع، وضعیت سازه‌ها و آخرین نبردهای دفاعی

اتصال به نبردها و اقتصاد:
    • سازه‌ها در جدول defenses ذخیره می‌شوند (سطح و درصد سلامت)
    • در نبردها: قدرت دفاع از مجموع یگان‌ها (۷۰٪) + سازه‌ها (با احتساب سطح و سلامت) + بستر پایگاه محاسبه می‌شود
    • پس از نبرد: سازه‌های مدافع خسارت دریافت می‌کنند و نیاز به تعمیر پیدا می‌کنند
    • پرداخت سکه‌ها از طریق admin_core.pay انجام شده و هوک مأموریت خرج سکه فراخوانی می‌شود
"""
from __future__ import annotations

import html
import time

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import admin_core, game, hooks
from .db import DB

router = Router(name="defense")

_db: DB | None = None

NAV_MAIN = "nav:main"
NAV_DEFENSE = "nav:defense"


def setup(db: DB) -> None:
    global _db
    _db = db


# ================================================================ ابزارها
def esc(t: str) -> str:
    return html.escape(str(t))


def name_of(u: dict) -> str:
    return u.get("first_name") or u.get("username") or "فرمانده"


async def _ensure_cb(cb: CallbackQuery) -> dict:
    u = cb.from_user
    return await _db.ensure_user(u.id, u.username or "", u.first_name or "")


async def _ensure_msg(message: Message) -> dict:
    u = message.from_user
    return await _db.ensure_user(u.id, u.username or "", u.first_name or "")


def health_badge(health: int) -> str:
    """نمایش وضعیت سلامت سازه با درصد و نشان گرافیکی."""
    health = max(0, min(100, health))
    if health >= 100:
        return "🟢 ۱۰۰٪ (سالم)"
    if health >= 75:
        return f"🟡 {game.fa(health)}٪ (خسارت جزئی)"
    if health >= 50:
        return f"🟠 {game.fa(health)}٪ (آسیب‌دیده)"
    return f"🔴 {game.fa(health)}٪ (خسارت سنگین)"


# ================================================================ منوی اصلی دفاع (Landing)
def defense_landing_text(user: dict, defenses: dict, army: dict) -> str:
    units = {k: v for k, v in army.items() if k in game.UNITS}
    total_def = game.defense_power(units, defenses, base_level=user.get("level", 1))
    owned_count = sum(1 for k in game.DEFENSE_KEYS if k in defenses and defenses[k].get("level", 0) > 0)
    
    damaged = [k for k, v in defenses.items() if v.get("health", 100) < 100]
    warn_line = ""
    if damaged:
        warn_line = f"\n⚠️ <b>هشدار:</b> {game.fa(len(damaged))} سازه دفاعی دچار خسارت شده است! برای بازیابی قدرت به «تعمیر دفاع» بروید.\n"

    shield_info = "غیرفعال ⚪"
    if user.get("shield_until", 0) > time.time():
        hours = int((user["shield_until"] - time.time()) // 3600)
        mins = int(((user["shield_until"] - time.time()) % 3600) // 60)
        shield_info = f"فعال 🟢 ({game.fa(hours)}س {game.fa(mins)}د)"

    return (
        f"╔════════════════════════╗\n"
        f"║  🛡 <b>سامانه دفاعی پایگاه {esc(name_of(user))}</b>  ║\n"
        f"╚════════════════════════╝\n"
        f"🏰 سطح پایگاه: <b>سطح {game.fa(user.get('level', 1))}</b>\n"
        f"🛡 مجموع قدرت دفاعی: <b>{game.fa(total_def)}</b>\n"
        f"🏗 سازه‌های فعال: <b>{game.fa(owned_count)}</b> از {game.fa(len(game.DEFENSE_KEYS))} سازه\n"
        f"🕊 وضعیت سپر: {shield_info}\n"
        f"💰 موجودی: <b>{admin_core.coins_display(user)}</b> سکه\n"
        f"{warn_line}"
        f"────────────────\n"
        f"از منوی زیر بخش مورد نظر را انتخاب کنید:"
    )


def defense_landing_kb(has_damaged: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🏰 دفاع پایگاه من", callback_data="defense:my")
    b.button(text="🛒 خرید تجهیزات دفاعی", callback_data="defense:buy")
    b.button(text="⬆️ ارتقای دفاع", callback_data="defense:upgrade")
    repair_btn = "🔧 تعمیر دفاع ⚠️" if has_damaged else "🔧 تعمیر دفاع"
    b.button(text=repair_btn, callback_data="defense:repair")
    b.button(text="📊 گزارش دفاع", callback_data="defense:report")
    b.button(text="🛡️ سپر محافظتی", callback_data="defense:shield")
    b.button(text="⬅️ بازگشت", callback_data=NAV_MAIN)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(1, 2, 2, 1, 2)
    return b.as_markup()


# ================================================================ 1) 🏰 دفاع پایگاه من (My Base Defense)
def my_defense_text(user: dict, defenses: dict, army: dict) -> str:
    base_lvl = user.get("level", 1)
    units = {k: v for k, v in army.items() if k in game.UNITS}
    unit_def = round(sum(c * game.UNITS[u]["power"] * 0.7 for u, c in units.items() if u in game.UNITS))
    base_bonus = max(0, (base_lvl - 1) * 15)
    total_def = game.defense_power(units, defenses, base_level=base_lvl)

    lines = [
        "╔════════════════════════╗",
        f"║  🏰 <b>دفاع پایگاه من</b>  ║",
        "╚════════════════════════╝",
        f"👤 فرمانده: <b>{esc(name_of(user))}</b>",
        f"🏰 <b>سطح پایگاه:</b> سطح {game.fa(base_lvl)} (+{game.fa(base_bonus)} پاداش بستر پایگاه)",
        "────────────────",
    ]

    for key in game.DEFENSE_KEYS:
        info = game.DEFENSES[key]
        d_data = defenses.get(key)
        if d_data and d_data.get("level", 0) > 0:
            lvl = d_data["level"]
            hlth = d_data.get("health", 100)
            pwr = game.struct_defense_power(key, lvl, hlth)
            det_label = "قدرت شناسایی/دفاع" if key == "radar" else "قدرت دفاع"
            lines.append(
                f"{info['emoji']} <b>{info['name']}</b>:\n"
                f"  • سطح: <b>سطح {game.fa(lvl)}</b>\n"
                f"  • {det_label}: <b>{game.fa(pwr)}</b> 🛡️ | وضعیت: {health_badge(hlth)}"
            )
        else:
            lines.append(
                f"{info['emoji']} <b>{info['name']}</b>:\n"
                f"  • سطح: <i>ساخته نشده (سطح ۰)</i> — از «خرید تجهیزات دفاعی» احداث کنید."
            )
        lines.append("")

    lines.append("────────────────")
    lines.append(f"👥 پدافند یگان‌های ارتش: <b>{game.fa(unit_def)}</b> 🛡️ (۷۰٪ قدرت آتش)")
    lines.append(f"🛡 <b>مجموع کل قدرت دفاعی پایگاه: {game.fa(total_def)}</b> 🛡️")

    return "\n".join(lines)


def my_defense_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🛒 خرید تجهیزات", callback_data="defense:buy")
    b.button(text="⬆️ ارتقای دفاع", callback_data="defense:upgrade")
    b.button(text="🔧 تعمیر دفاع", callback_data="defense:repair")
    b.button(text="📊 گزارش دفاع", callback_data="defense:report")
    b.button(text="⬅️ بازگشت", callback_data=NAV_DEFENSE)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2, 2, 2)
    return b.as_markup()


# ================================================================ 2) 🛒 خرید تجهیزات دفاعی (Buy Defense Equipment)
def buy_defense_text(user: dict) -> str:
    return (
        "🛒 <b>فروشگاه و احداث سازه‌های دفاعی</b>\n"
        f"💰 موجودی شما: <b>{admin_core.coins_display(user)}</b> سکه\n"
        "────────────────\n"
        "سازه‌های دفاعی امنیت پایگاه شما را در برابر حملات دشمن تضمین می‌کنند.\n"
        "برای مشاهدهٔ مشخصات و احداث اولیه، روی هر سازه بزنید:"
    )


def buy_defense_kb(defenses: dict) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key in game.DEFENSE_KEYS:
        info = game.DEFENSES[key]
        d_data = defenses.get(key)
        owned_lvl = d_data["level"] if (d_data and d_data.get("level", 0) > 0) else 0
        if owned_lvl > 0:
            label = f"{info['emoji']} {info['name']} (دارای سطح {game.fa(owned_lvl)})"
        else:
            label = f"{info['emoji']} {info['name']} — {game.fa(info['cost'])}💰"
        b.button(text=label, callback_data=f"defense:buyview:{key}")
    b.button(text="⬅️ بازگشت", callback_data=NAV_DEFENSE)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(1, 1, 1, 1, 2)
    return b.as_markup()


def buy_structure_view(user: dict, key: str, defenses: dict) -> tuple[str, InlineKeyboardMarkup] | None:
    info = game.DEFENSES.get(key)
    if not info:
        return None
    d_data = defenses.get(key)
    owned_lvl = d_data["level"] if (d_data and d_data.get("level", 0) > 0) else 0
    
    det_label = "قدرت شناسایی/دفاع اولیه" if key == "radar" else "قدرت دفاع اولیه"

    if owned_lvl > 0:
        pwr = game.struct_defense_power(key, owned_lvl, d_data.get("health", 100))
        text = (
            f"{info['emoji']} <b>{info['name']}</b>\n"
            f"────────────────\n"
            f"📄 {info['desc']}\n"
            f"🗃 وضعیت فعلی: <b>احداث‌شده (سطح {game.fa(owned_lvl)})</b>\n"
            f"🛡 قدرت فعلی: <b>{game.fa(pwr)}</b> 🛡️ | {health_badge(d_data.get('health', 100))}\n"
            f"────────────────\n"
            f"💡 این سازه قبلاً احداث شده است. برای افزایش قدرت آن از بخش «ارتقای دفاع» اقدام کنید."
        )
        b = InlineKeyboardBuilder()
        b.button(text="⬆️ رفتن به ارتقای این سازه", callback_data=f"defense:upview:{key}")
        b.button(text="⬅️ بازگشت به فروشگاه", callback_data="defense:buy")
        b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
        b.adjust(1, 2)
        return text, b.as_markup()

    text = (
        f"{info['emoji']} <b>احداث {info['name']}</b>\n"
        f"────────────────\n"
        f"📄 {info['desc']}\n"
        f"💵 قیمت احداث (سطح ۱): <b>{game.fa(info['cost'])}</b> سکه\n"
        f"🛡 {det_label}: <b>{game.fa(info['defense'])}</b> 🛡️\n"
        f"🗃 وضعیت فعلی: <i>ساخته نشده (سطح ۰)</i>\n"
        f"💰 موجودی شما: {admin_core.coins_display(user)} سکه\n"
        f"────────────────\n"
        f"آیا مایل به خرید و احداث اولیه این سازه هستید؟"
    )
    b = InlineKeyboardBuilder()
    b.button(text=f"✅ خرید و احداث ({game.fa(info['cost'])}💰)", callback_data=f"defense:buyconf:{key}")
    b.button(text="❌ انصراف", callback_data="defense:buy")
    b.button(text="⬅️ بازگشت", callback_data="defense:buy")
    b.adjust(1, 2)
    return text, b.as_markup()


# ================================================================ 3) ⬆ Upgrade Defense (ارتقای دفاع)
def upgrade_defense_text(user: dict) -> str:
    return (
        "⬆️ <b>سامانه ارتقای سطح سازه‌های دفاعی</b>\n"
        f"💰 موجودی شما: <b>{admin_core.coins_display(user)}</b> سکه\n"
        "────────────────\n"
        "با ارتقای هر سازه، قدرت پدافندی و مقاومت پایگاه چند برابر می‌شود.\n"
        "سازه‌ای را برای ارتقا انتخاب کنید:"
    )


def upgrade_defense_kb(defenses: dict) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key in game.DEFENSE_KEYS:
        info = game.DEFENSES[key]
        d_data = defenses.get(key)
        owned_lvl = d_data["level"] if (d_data and d_data.get("level", 0) > 0) else 0
        if owned_lvl > 0:
            cost = game.struct_upgrade_cost(key, owned_lvl)
            label = f"{info['emoji']} {info['name']} (سطح {game.fa(owned_lvl)} ➔ {game.fa(owned_lvl + 1)}) — {game.fa(cost)}💰"
            b.button(text=label, callback_data=f"defense:upview:{key}")
        else:
            label = f"{info['emoji']} {info['name']} (احداث نشده — {game.fa(info['cost'])}💰)"
            b.button(text=label, callback_data=f"defense:buyview:{key}")
    b.button(text="⬅️ بازگشت", callback_data=NAV_DEFENSE)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(1, 1, 1, 1, 2)
    return b.as_markup()


def upgrade_structure_view(user: dict, key: str, defenses: dict) -> tuple[str, InlineKeyboardMarkup] | None:
    info = game.DEFENSES.get(key)
    if not info:
        return None
    d_data = defenses.get(key)
    owned_lvl = d_data["level"] if (d_data and d_data.get("level", 0) > 0) else 0
    if owned_lvl <= 0:
        return buy_structure_view(user, key, defenses)

    next_lvl = owned_lvl + 1
    cost = game.struct_upgrade_cost(key, owned_lvl)
    cur_pwr = game.struct_defense_power(key, owned_lvl, 100)
    next_pwr = game.struct_defense_power(key, next_lvl, 100)
    diff = next_pwr - cur_pwr

    det_label = "قدرت شناسایی/دفاع" if key == "radar" else "قدرت دفاع"

    text = (
        f"⬆️ <b>ارتقای {info['name']}</b>\n"
        f"────────────────\n"
        f"🎚 <b>سطح:</b> سطح {game.fa(owned_lvl)} ➔ <b>سطح {game.fa(next_lvl)}</b>\n"
        f"🛡 <b>{det_label}:</b> {game.fa(cur_pwr)} ➔ <b>{game.fa(next_pwr)} 🛡️</b> (+{game.fa(diff)})\n"
        f"💵 <b>هزینه ارتقا:</b> <b>{game.fa(cost)}</b> سکه\n"
        f"💰 موجودی شما: {admin_core.coins_display(user)} سکه\n"
        f"────────────────\n"
        f"آیا ارتقای این سازه را تأیید می‌کنید؟"
    )
    b = InlineKeyboardBuilder()
    b.button(text=f"✅ تأیید ارتقا به سطح {game.fa(next_lvl)} ({game.fa(cost)}💰)", callback_data=f"defense:updone:{key}")
    b.button(text="❌ انصراف", callback_data="defense:upgrade")
    b.button(text="⬅️ بازگشت", callback_data="defense:upgrade")
    b.adjust(1, 2)
    return text, b.as_markup()


# ================================================================ 4) 🔧 Repair Defense (تعمیر دفاع)
def repair_defense_text_and_kb(user: dict, defenses: dict) -> tuple[str, InlineKeyboardMarkup]:
    lines = [
        "🔧 <b>سامانه تعمیر و بازسازی سازه‌های دفاعی</b>",
        f"💰 موجودی شما: <b>{admin_core.coins_display(user)}</b> سکه",
        "────────────────",
    ]

    owned_keys = [k for k in game.DEFENSE_KEYS if k in defenses and defenses[k].get("level", 0) > 0]
    damaged_items: list[tuple[str, int, int, int]] = []  # (key, level, health, cost)
    total_repair_cost = 0

    if not owned_keys:
        lines.append("هنوز هیچ سازه دفاعی احداث نکرده‌اید! ابتدا از «خرید تجهیزات دفاعی» سازه بسازید.")
    else:
        for key in owned_keys:
            info = game.DEFENSES[key]
            d_data = defenses[key]
            lvl = d_data["level"]
            hlth = d_data.get("health", 100)
            cost = game.struct_repair_cost(key, lvl, hlth)
            
            if hlth < 100:
                damaged_items.append((key, lvl, hlth, cost))
                total_repair_cost += cost
                lines.append(f"{info['emoji']} <b>{info['name']}</b> (سطح {game.fa(lvl)}): {health_badge(hlth)} ⚠️ — هزینه تعمیر: <b>{game.fa(cost)}</b>💰")
            else:
                lines.append(f"{info['emoji']} <b>{info['name']}</b> (سطح {game.fa(lvl)}): {health_badge(hlth)}")

    lines.append("────────────────")
    b = InlineKeyboardBuilder()

    if damaged_items:
        lines.append(f"🛠 <b>جمع کل هزینه تعمیر تمام سازه‌ها:</b> <b>{game.fa(total_repair_cost)}</b> سکه")
        b.button(text=f"🔧 تعمیر همه سازه‌ها ({game.fa(total_repair_cost)}💰)", callback_data="defense:repdone:all")
        for key, lvl, hlth, cost in damaged_items:
            info = game.DEFENSES[key]
            b.button(text=f"🔧 تعمیر {info['name']} ({game.fa(cost)}💰)", callback_data=f"defense:repdone:{key}")
    else:
        if owned_keys:
            lines.append("✅ تمام سازه‌های دفاعی در سلامت کامل (۱۰۰٪) قرار دارند و نیازی به تعمیر ندارند.")

    b.button(text="⬅️ بازگشت", callback_data=NAV_DEFENSE)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(1)
    return "\n".join(lines), b.as_markup()


# ================================================================ 5) 📊 Defense Report (گزارش دفاع)
def defense_report_text(user: dict, defenses: dict, army: dict, history: list[dict]) -> str:
    base_lvl = user.get("level", 1)
    units = {k: v for k, v in army.items() if k in game.UNITS}
    unit_def = round(sum(c * game.UNITS[u]["power"] * 0.7 for u, c in units.items() if u in game.UNITS))
    total_def = game.defense_power(units, defenses, base_level=base_lvl)

    shield_status = "غیرفعال ⚪"
    if user.get("shield_until", 0) > time.time():
        hours = int((user["shield_until"] - time.time()) // 3600)
        shield_status = f"فعال تا {game.fa(hours)} ساعت دیگر 🟢"

    lines = [
        "╔════════════════════════╗",
        f"║  📊 <b>گزارش جامع پدافند پایگاه</b>  ║",
        "╚════════════════════════╝",
        f"👤 فرمانده: <b>{esc(name_of(user))}</b>  •  🎚 سطح پایگاه: <b>{game.fa(base_lvl)}</b>",
        f"🏅 درجه نظامی: <b>{game.rank_name(base_lvl)}</b>",
        f"🛡 مجموع قدرت دفاعی: <b>{game.fa(total_def)}</b> 🛡️",
        f"🕊 وضعیت سپر: {shield_status}",
        f"🏆 آمار دفاع: <b>{game.fa(user.get('def_wins', 0))}</b> دفع موفق  |  🔥 <b>{game.fa(user.get('def_losses', 0))}</b> باخت دفاعی",
        "────────────────",
        "🏗 <b>وضعیت سازه‌های دفاعی:</b>",
    ]

    for key in game.DEFENSE_KEYS:
        info = game.DEFENSES[key]
        d_data = defenses.get(key)
        if d_data and d_data.get("level", 0) > 0:
            lvl = d_data["level"]
            hlth = d_data.get("health", 100)
            pwr = game.struct_defense_power(key, lvl, hlth)
            lines.append(f"• {info['emoji']} <b>{info['name']}</b>: سطح {game.fa(lvl)} | قدرت: {game.fa(pwr)} 🛡️ | {health_badge(hlth)}")
        else:
            lines.append(f"• {info['emoji']} <b>{info['name']}</b>: <i>احداث نشده</i>")

    lines.append(f"• 👥 <b>یگان‌های پدافندی ارتش:</b> {game.fa(unit_def)} 🛡️ (۷۰٪ قدرت آتش)")
    lines.append("────────────────")
    lines.append("📜 <b>آخرین نبردهای دفاعی پایگاه:</b>")

    if not history:
        lines.append("هنوز هیچ نبرد دفاعی برای پایگاه شما ثبت نشده است.")
    else:
        for r in history:
            when = time.strftime("%m/%d %H:%M", time.localtime(r["ts"]))
            lines.append(f"• {when} — {r.get('def_summary', 'نبرد دفاعی')}")

    return "\n".join(lines)


def defense_report_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🏰 دفاع پایگاه من", callback_data="defense:my")
    b.button(text="🔧 تعمیر دفاع", callback_data="defense:repair")
    b.button(text="🛒 خرید تجهیزات", callback_data="defense:buy")
    b.button(text="⬆️ ارتقای دفاع", callback_data="defense:upgrade")
    b.button(text="⬅️ بازگشت", callback_data=NAV_DEFENSE)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2, 2, 2)
    return b.as_markup()


# ================================================================ هندلرها — ناوبری و منوی اصلی
@router.message(F.text == "🛡 دفاع")
async def on_defense(message: Message) -> None:
    user = await _ensure_msg(message)
    defenses = await _db.get_defenses(user["user_id"])
    army = await _db.get_army(user["user_id"])
    has_damaged = any(v.get("health", 100) < 100 for v in defenses.values())
    await message.answer(
        defense_landing_text(user, defenses, army),
        reply_markup=defense_landing_kb(has_damaged),
    )


@router.callback_query(F.data == NAV_DEFENSE)
async def cb_nav_defense(cb: CallbackQuery) -> None:
    user = await _ensure_cb(cb)
    defenses = await _db.get_defenses(user["user_id"])
    army = await _db.get_army(user["user_id"])
    has_damaged = any(v.get("health", 100) < 100 for v in defenses.values())
    await cb.message.edit_text(
        defense_landing_text(user, defenses, army),
        reply_markup=defense_landing_kb(has_damaged),
    )
    await cb.answer()


@router.callback_query(F.data == "defense:my")
async def cb_defense_my(cb: CallbackQuery) -> None:
    user = await _ensure_cb(cb)
    defenses = await _db.get_defenses(user["user_id"])
    army = await _db.get_army(user["user_id"])
    await cb.message.edit_text(
        my_defense_text(user, defenses, army),
        reply_markup=my_defense_kb(),
    )
    await cb.answer()


@router.callback_query(F.data == "defense:buy")
async def cb_defense_buy(cb: CallbackQuery) -> None:
    user = await _ensure_cb(cb)
    defenses = await _db.get_defenses(user["user_id"])
    await cb.message.edit_text(
        buy_defense_text(user),
        reply_markup=buy_defense_kb(defenses),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("defense:buyview:"))
async def cb_defense_buyview(cb: CallbackQuery) -> None:
    key = cb.data.split(":")[-1]
    user = await _ensure_cb(cb)
    defenses = await _db.get_defenses(user["user_id"])
    view = buy_structure_view(user, key, defenses)
    if view is None:
        await cb.answer("❌ سازه ناشناخته است!", show_alert=True)
        return
    text, kb = view
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("defense:buyconf:"))
async def cb_defense_buyconf(cb: CallbackQuery) -> None:
    key = cb.data.split(":")[-1]
    user = await _ensure_cb(cb)
    uid = user["user_id"]
    info = game.DEFENSES.get(key)
    if not info or key not in game.DEFENSE_KEYS:
        await cb.answer("❌ سازه نامعتبر است!", show_alert=True)
        return

    defenses = await _db.get_defenses(uid)
    if defenses.get(key, {}).get("level", 0) > 0:
        await cb.answer("💡 این سازه قبلاً احداث شده است! برای افزایش قدرت به ارتقا بروید.", show_alert=True)
        view = buy_structure_view(user, key, defenses)
        if view:
            await cb.message.edit_text(view[0], reply_markup=view[1])
        return

    cost = info["cost"]
    if not await admin_core.pay(user, cost):
        await cb.answer(f"❌ سکه کافی نداری! هزینه احداث: {game.fa(cost)}💰", show_alert=True)
        return

    await _db.set_defense(uid, key, 1, 100)
    await hooks.after_purchase(uid, 0, cost)

    user = await _db.get_user(uid)
    defenses = await _db.get_defenses(uid)
    army = await _db.get_army(uid)
    new_total = game.defense_power({k: v for k, v in army.items() if k in game.UNITS}, defenses, base_level=user.get("level", 1))

    await cb.answer(f"✅ {info['emoji']} {info['name']} با موفقیت احداث شد!", show_alert=True)
    
    b = InlineKeyboardBuilder()
    b.button(text="🏰 دفاع پایگاه من", callback_data="defense:my")
    b.button(text="🛒 خرید سازه دیگر", callback_data="defense:buy")
    b.button(text="⬆️ ارتقای دفاع", callback_data="defense:upgrade")
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2, 2)
    
    await cb.message.edit_text(
        f"🎉 <b>احداث موفق سازه دفاعی!</b>\n"
        f"────────────────\n"
        f"{info['emoji']} <b>{info['name']} (سطح ۱)</b> با موفقیت به پایگاه شما اضافه شد.\n"
        f"🛡 قدرت اضافه شده: <b>+{game.fa(info['defense'])}</b> 🛡️\n"
        f"💸 هزینه پرداختی: {game.fa(cost)} سکه | 💰 موجودی: {admin_core.coins_display(user)}\n"
        f"🛡 <b>مجموع قدرت دفاعی پایگاه: {game.fa(new_total)}</b>",
        reply_markup=b.as_markup(),
    )


# ================================================================ هندلرها — ارتقای دفاع
@router.callback_query(F.data == "defense:upgrade")
async def cb_defense_upgrade(cb: CallbackQuery) -> None:
    user = await _ensure_cb(cb)
    defenses = await _db.get_defenses(user["user_id"])
    await cb.message.edit_text(
        upgrade_defense_text(user),
        reply_markup=upgrade_defense_kb(defenses),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("defense:upview:"))
async def cb_defense_upview(cb: CallbackQuery) -> None:
    key = cb.data.split(":")[-1]
    user = await _ensure_cb(cb)
    defenses = await _db.get_defenses(user["user_id"])
    view = upgrade_structure_view(user, key, defenses)
    if view is None:
        await cb.answer("❌ سازه ناشناخته است!", show_alert=True)
        return
    text, kb = view
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("defense:updone:"))
async def cb_defense_updone(cb: CallbackQuery) -> None:
    key = cb.data.split(":")[-1]
    user = await _ensure_cb(cb)
    uid = user["user_id"]
    info = game.DEFENSES.get(key)
    if not info or key not in game.DEFENSE_KEYS:
        await cb.answer("❌ سازه نامعتبر است!", show_alert=True)
        return

    defenses = await _db.get_defenses(uid)
    d_data = defenses.get(key)
    owned_lvl = d_data["level"] if (d_data and d_data.get("level", 0) > 0) else 0
    if owned_lvl <= 0:
        await cb.answer("❌ این سازه ابتدا باید احداث شود!", show_alert=True)
        return

    cost = game.struct_upgrade_cost(key, owned_lvl)
    if not await admin_core.pay(user, cost):
        await cb.answer(f"❌ سکه کافی نداری! هزینه ارتقا: {game.fa(cost)}💰", show_alert=True)
        return

    new_lvl = await _db.upgrade_defense(uid, key)
    await hooks.after_purchase(uid, 0, cost)

    user = await _db.get_user(uid)
    defenses = await _db.get_defenses(uid)
    army = await _db.get_army(uid)
    new_total = game.defense_power({k: v for k, v in army.items() if k in game.UNITS}, defenses, base_level=user.get("level", 1))
    new_pwr = game.struct_defense_power(key, new_lvl, 100)

    await cb.answer(f"✅ {info['emoji']} {info['name']} به سطح {game.fa(new_lvl)} ارتقا یافت!", show_alert=True)

    b = InlineKeyboardBuilder()
    b.button(text="⬆️ ادامه ارتقا", callback_data="defense:upgrade")
    b.button(text="🏰 دفاع پایگاه من", callback_data="defense:my")
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2, 1)

    await cb.message.edit_text(
        f"🎉 <b>ارتقای موفق سازه دفاعی!</b>\n"
        f"────────────────\n"
        f"{info['emoji']} <b>{info['name']}</b> به <b>سطح {game.fa(new_lvl)}</b> ارتقا یافت.\n"
        f"🛡 قدرت دفاعی سازه: <b>{game.fa(new_pwr)}</b> 🛡️\n"
        f"💸 هزینه ارتقا: {game.fa(cost)} سکه | 💰 موجودی: {admin_core.coins_display(user)}\n"
        f"🛡 <b>مجموع قدرت دفاعی پایگاه: {game.fa(new_total)}</b>",
        reply_markup=b.as_markup(),
    )


# ================================================================ هندلرها — تعمیر دفاع
@router.callback_query(F.data == "defense:repair")
async def cb_defense_repair(cb: CallbackQuery) -> None:
    user = await _ensure_cb(cb)
    defenses = await _db.get_defenses(user["user_id"])
    text, kb = repair_defense_text_and_kb(user, defenses)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("defense:repdone:"))
async def cb_defense_repdone(cb: CallbackQuery) -> None:
    target = cb.data.split(":")[-1]  # "all" or specific key
    user = await _ensure_cb(cb)
    uid = user["user_id"]
    defenses = await _db.get_defenses(uid)

    if target == "all":
        damaged = [(k, v["level"], v.get("health", 100)) for k, v in defenses.items() if v.get("health", 100) < 100]
        if not damaged:
            await cb.answer("✅ تمام سازه‌ها کاملاً سالم هستند!", show_alert=True)
            return
        total_cost = sum(game.struct_repair_cost(k, lvl, hlth) for k, lvl, hlth in damaged)
        if not await admin_core.pay(user, total_cost):
            await cb.answer(f"❌ سکه کافی نداری! هزینه تعمیر: {game.fa(total_cost)}💰", show_alert=True)
            return
        await _db.repair_defense(uid, None)
        await hooks.after_purchase(uid, 0, total_cost)
        await cb.answer(f"✅ تمام سازه‌ها با موفقیت تعمیر شدند! (پرداخت {game.fa(total_cost)}💰)", show_alert=True)
    else:
        if target not in game.DEFENSES:
            await cb.answer("❌ سازه نامعتبر است!", show_alert=True)
            return
        d_data = defenses.get(target)
        if not d_data or d_data.get("health", 100) >= 100:
            await cb.answer("✅ این سازه کاملاً سالم است و نیازی به تعمیر ندارد.", show_alert=True)
            return
        cost = game.struct_repair_cost(target, d_data["level"], d_data.get("health", 100))
        if not await admin_core.pay(user, cost):
            await cb.answer(f"❌ سکه کافی نداری! هزینه تعمیر: {game.fa(cost)}💰", show_alert=True)
            return
        await _db.repair_defense(uid, target)
        await hooks.after_purchase(uid, 0, cost)
        info = game.DEFENSES[target]
        await cb.answer(f"✅ {info['name']} به سلامت کامل ۱۰۰٪ تعمیر شد!", show_alert=True)

    user = await _db.get_user(uid)
    defenses = await _db.get_defenses(uid)
    text, kb = repair_defense_text_and_kb(user, defenses)
    await cb.message.edit_text(text, reply_markup=kb)


# ================================================================ هندلرها — گزارش دفاع
@router.callback_query(F.data == "defense:report")
async def cb_defense_report(cb: CallbackQuery) -> None:
    user = await _ensure_cb(cb)
    defenses = await _db.get_defenses(user["user_id"])
    army = await _db.get_army(user["user_id"])
    history = await _db.defense_battle_history(user["user_id"], 5)
    await cb.message.edit_text(
        defense_report_text(user, defenses, army, history),
        reply_markup=defense_report_kb(),
    )
    await cb.answer()


# ================================================================ هندلرها — سپر محافظتی
@router.callback_query(F.data == "defense:shield")
async def cb_defense_shield(cb: CallbackQuery) -> None:
    user = await _ensure_cb(cb)
    if user.get("shield_until", 0) > time.time():
        hours = int((user["shield_until"] - time.time()) // 3600)
        b = InlineKeyboardBuilder()
        b.button(text="⬅️ بازگشت", callback_data=NAV_DEFENSE)
        b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
        b.adjust(2)
        await cb.message.edit_text(
            f"🕊 سپر پایگاه شما فعال است و تا <b>{game.fa(hours)} ساعت دیگر</b> ادامه دارد!",
            reply_markup=b.as_markup(),
        )
        await cb.answer()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🕊 سپر ۶ ساعته — {game.fa(game.SHIELD_COSTS[6])}💰", callback_data="shield:6")],
        [InlineKeyboardButton(text=f"🕊 سپر ۲۴ ساعته — {game.fa(game.SHIELD_COSTS[24])}💰", callback_data="shield:24")],
        [
            InlineKeyboardButton(text="⬅️ بازگشت", callback_data=NAV_DEFENSE),
            InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NAV_MAIN),
        ],
    ])
    await cb.message.edit_text(
        f"🕊 <b>سپر محافظتی پایگاه</b>\n"
        f"────────────────\n"
        f"تا وقتی سپر فعال است هیچ بازیکنی نمی‌تواند به پایگاه شما حمله کند!\n"
        f"💰 موجودی: <b>{admin_core.coins_display(user)}</b> سکه",
        reply_markup=kb,
    )
    await cb.answer()
