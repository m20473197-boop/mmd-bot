"""🪖 سیستم نوین ارتش نبردگاه — ارتش من، فروشگاه تجهیزات نظامی و پادگان آموزش نیروی زمینی.

ساختار منو (با دکمهٔ پایین چت «🪖 ارتش» یا callback ‏nav:army باز می‌شود):
    1) 🪖 ارتش من            — نمای کامل یگان‌ها، تعداد، قدرت هر یگان و قدرت کل
    2) 🛒 خرید تجهیزات نظامی — تانک/موشک/ناو/جنگنده/بمب‌افکن/پهپاد/بالگرد (خرید فوری)
    3) 🏗 آموزش نیروی زمینی  — سرباز و کماندو؛ زمان‌دار و صفی (جلوگیری از ساخت آنی)

جریان خرید/آموزش (مطابق طراحی جدید):
    انتخاب یگان ← وارد‌کردن تعداد (تایپی یا دکمهٔ سریع) ← نمایش جمع قیمت/زمان
    ← ✅ تأیید / ❌ انصراف

اتصال به بقیهٔ بازی:
    • سکه از همان موجودی دیتابیس کم می‌شود (admin_core.pay؛ مدیر: رایگان)
    • یگان‌ها در جدول army ذخیره می‌شوند → نبرد، دفاع، رده‌بندی و نمودار بدون تغییر کار می‌کنند
    • آموزش‌ها در جدول training می‌نشینند و «تنها پس از پایان زمان» (با lazy settlement
      روی هوک ensure_user) به ارتش اضافه می‌شوند؛ مأموریت «آموزش یگان» همان‌جا رد می‌شود
    • ناوبری/بازگشت با همان الگوی سراسری منو (nav:army / nav:main)
"""
from __future__ import annotations

import html
import time

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import admin_core, game, hooks
from .db import DB

router = Router(name="army")

_db: DB | None = None

# ورودی در انتظارِ تعداد: user_id -> (flow, unit_key)  |  flow ∈ {"eq", "tr"}
_pending_qty: dict[int, tuple[str, str]] = {}
# آموزش‌های تازه‌تکمیل‌شده که هنوز در صفحهٔ «ارتش من» دیده نشده‌اند
_arrived: dict[int, list[dict]] = {}
_prev_hook = None

MAX_QTY = game.TRAIN_MAX_QTY

# ارقام فارسی/عربی → لاتین، برای پذیرش ورودی عددی کاربر
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_BT_QUICK = (1, 5, 10, 25, 50, 100)

NAV_MAIN = "nav:main"
NAV_ARMY = "nav:army"


def setup(db: DB) -> None:
    """ثبت دیتابیس + اتصال هوک تسویهٔ آموزش روی ensure_user (زنجیر پس از admin_core)."""
    global _db, _prev_hook
    _db = db
    if getattr(db.user_hook, "_army_hook", False):
        return                          # از ثبت تودرتوی چندبارهٔ هوک جلوگیری می‌کند
    _prev_hook = db.user_hook           # هوک هدیهٔ تست‌کننده (admin_core) اگر ثبت شده باشد
    db.user_hook = _army_user_hook
    _army_user_hook._army_hook = True


async def _army_user_hook(user: dict) -> dict:
    """هر لمس کاربر (دستور یا دکمه) اول آموزش‌های کامل‌شده‌اش را تحویل می‌گیرد.

    «جلوگیری از ساخت آنی»: تا finish_ts نرسیده باشد هیچ یگانی اضافه نمی‌شود؛
    به‌محض رسیدن زمان، در اولین تماس با ensure_user، یگان‌ها به ارتش می‌پیوندند،
    مأموریت «آموزش یگان» جلو می‌رود و پیام رسیدن در صفحهٔ «ارتش من» انبار می‌شود.
    """
    uid = user["user_id"]
    done = await _db.settle_training(uid)
    if done:
        _arrived.setdefault(uid, []).extend(done)
        for r in done:
            await hooks.after_purchase(uid, r["count"], 0)
    if _prev_hook:
        user = await _prev_hook(user)
    return user


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


def parse_qty(raw: str) -> int | None:
    """تبدیل ورودی متنی کاربر به تعداد معتبر (ارقام فارسی هم می‌پذیرد)."""
    if not raw:
        return None
    t = (raw.strip().translate(_DIGITS)
         .replace(",", "").replace("٬", "").replace("،", "").replace(" ", ""))
    if not t.isdigit():
        return None
    n = int(t)
    if 1 <= n <= MAX_QTY:
        return n
    return None


def dur_text(seconds: int) -> str:
    """زمان به فارسی: «۴۵ ثانیه»، «۳ دقیقه»، «۱ ساعت و ۲۰ دقیقه»."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{game.fa(seconds)} ثانیه"
    mins, sec = divmod(seconds, 60)
    if mins < 60:
        return f"{game.fa(mins)} دقیقه" + (f" و {game.fa(sec)} ثانیه" if sec else "")
    hours, mins = divmod(mins, 60)
    out = f"{game.fa(hours)} ساعت"
    if mins:
        out += f" و {game.fa(mins)} دقیقه"
    return out


async def _training_active(user_id: int) -> dict | None:
    return await _db.training_get(user_id)


# ================================================================ صفحه‌ها (ساخت متن/کیبورد)
def nav_buttons(b: InlineKeyboardBuilder, back_cb: str | None = None) -> None:
    """ردیف ناوبری استاندارد: بازگشت (اختیاری) + منوی اصلی."""
    if back_cb:
        b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
        b.button(text="⬅️ بازگشت", callback_data=back_cb)
        b.adjust(2)
    else:
        b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
        b.adjust(1)


def army_landing_text(user: dict, army: dict, training: dict | None) -> str:
    units = {k: v for k, v in army.items() if k in game.UNITS}
    power = game.attack_power(units)
    lines = [
        f"╔════════════════════════╗",
        f"║  🪖 <b>ارتش {esc(name_of(user))}</b>  ║",
        f"╚════════════════════════╝",
        f"⚔️ قدرت حملهٔ فعلی: <b>{game.fa(power)}</b>",
        f"👥 یگان‌های فعال: {game.fa(sum(units.values()))}",
    ]
    if training:
        left = training["finish_ts"] - int(time.time())
        info = game.UNITS.get(training["unit"], {})
        lines.append(f"⏳ در حال آموزش: {info.get('emoji', '')} ×{game.fa(training['count'])} "
                     f"— تا {dur_text(left)} دیگر")
    lines.append("────────────────")
    lines.append("🎖 بخش مورد نظر را انتخاب کن:")
    return "\n".join(lines)


def army_landing_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🪖 ارتش من", callback_data="army:my")
    b.button(text="🛒 خرید تجهیزات نظامی", callback_data="army:eq")
    b.button(text="🏗 آموزش نیروی زمینی", callback_data="army:tr")
    b.adjust(1, 2)
    return b.as_markup()


async def my_army_text(user: dict) -> tuple[str, InlineKeyboardMarkup]:
    uid = user["user_id"]
    await _db.settle_training(uid)          # تسویهٔ کامل‌شده‌ها (بی‌صدا؛ پیام‌ها از _arrived)
    army = await _db.get_army(uid)
    units = {k: v for k, v in army.items() if k in game.UNITS}
    defenses = await _db.get_defenses(uid)

    lines = ["🪖 <b>ارتش من</b>",
             f"👤 {esc(name_of(user))}",
             "────────────────"]
    if not units:
        lines.append("هنوز یگانی نداری! از «🏗 آموزش نیروی زمینی» یا "
                     "«🛒 خرید تجهیزات نظامی» شروع کن.")
    else:
        for key in game.UNITS:
            cnt = units.get(key, 0)
            if cnt <= 0:
                continue
            info = game.UNITS[key]
            lines.append(f"{info['emoji']} <b>{info['name']}</b> — تعداد: {game.fa(cnt)}"
                         f" | قدرت هر عدد: {game.fa(info['power'])}"
                         f" | <b>{game.fa(cnt * info['power'])}</b>⚔️")
    lines.append("────────────────")
    lines.append(f"⚔️ <b>قدرت کل حمله: {game.fa(game.attack_power(units))}</b>")
    if defenses:
        d = game.defense_power(units, defenses, base_level=user.get("level", 1))
        lines.append(f"🛡 سازه‌های دفاعی: {game.fa(sum(s['level'] for s in defenses.values()))} "
                     f"| قدرت دفاع (با یگان‌ها): {game.fa(d)}")
    else:
        lines.append(f"🛡 قدرت دفاع: {game.fa(game.defense_power(units, {}, base_level=user.get('level', 1)))} "
                     "(سازه نداری — از منوی «🛡 دفاع») ")

    training = await _db.training_get(uid)
    if training:
        info = game.UNITS.get(training["unit"], {})
        left = training["finish_ts"] - int(time.time())
        lines.append("────────────────")
        lines.append(f"⏳ <b>پادگان:</b> {info.get('emoji', '')} ×{game.fa(training['count'])} "
                     f"در حال آموزش — {dur_text(left)} تا ورود به ارتش")
    arrivals = _arrived.pop(uid, [])
    if arrivals:
        parts = [f"{game.UNITS.get(r['unit'], {}).get('emoji', '')}×{game.fa(r['count'])}"
                 for r in arrivals]
        lines.append("🎉 نیروهای تازه‌رسیده به ارتش پیوستند: " + "، ".join(parts))

    b = InlineKeyboardBuilder()
    b.button(text="🛒 خرید تجهیزات نظامی", callback_data="army:eq")
    b.button(text="🏗 آموزش نیروی زمینی", callback_data="army:tr")
    nav_buttons(b, NAV_ARMY)
    return "\n".join(lines), b.as_markup()


async def equipment_text(user: dict) -> tuple[str, InlineKeyboardMarkup]:
    """فهرست تجهیزات نظامی — قیمت و تعدادِ مالک‌شده روی هر دکمه."""
    uid = user["user_id"]
    army = await _db.get_army(uid)
    lines = ["🛒 <b>فروشگاه تجهیزات نظامی</b>",
             f"💰 موجودی تو: {admin_core.coins_display(user)} سکه",
             "────────────────",
             "تجهیزات سنگین بدون زمان آموزش، <b>فوری</b> به ارتش می‌پیوندند.",
             "روی هر تجهیز بزن تا جزئیات ببینی و تعداد دلخواه سفارش بده:"]
    b = InlineKeyboardBuilder()
    for key in game.EQUIPMENT_UNITS:
        info = game.UNITS[key]
        owned = army.get(key, 0)
        b.button(text=f"{info['emoji']} {info['name']} — {game.fa(info['cost'])}💰"
                 f" | دارای: {game.fa(owned)}",
                 callback_data=f"army:eqview:{key}")
    nav_buttons(b, NAV_ARMY)
    return "\n".join(lines), b.as_markup()


def equipment_kb() -> InlineKeyboardMarkup:
    """کیبورد خالصِ فهرست تجهیزات (برای تست/بازاستفاده)."""
    b = InlineKeyboardBuilder()
    for key in game.EQUIPMENT_UNITS:
        info = game.UNITS[key]
        b.button(text=f"{info['emoji']} {info['name']} — {game.fa(info['cost'])}💰",
                 callback_data=f"army:eqview:{key}")
    nav_buttons(b, NAV_ARMY)
    return b.as_markup()


async def equipment_view(uid: int, key: str) -> tuple[str, InlineKeyboardMarkup] | None:
    info = game.UNITS.get(key)
    if not info or key not in game.EQUIPMENT_UNITS:
        return None
    army = await _db.get_army(uid)
    owned = army.get(key, 0)
    text = (
        f"{info['emoji']} <b>{info['name']}</b>\n"
        f"────────────────\n"
        f"📄 {info['desc']}\n"
        f"💵 قیمت هر عدد: <b>{game.fa(info['cost'])}</b> سکه\n"
        f"⚔️ قدرت حمله: <b>{game.fa(info['power'])}</b>\n"
        f"🗃 تعداد در ارتش تو: <b>{game.fa(owned)}</b> "
        f"(قدرت فعلی این یگان: {game.fa(owned * info['power'])}⚔️)\n"
        f"────────────────\n"
        f"تعداد دلخواه را بنویس یا از دکمه‌های سریع بزن:"
    )
    b = InlineKeyboardBuilder()
    b.button(text="🔢 تعداد دلخواه…", callback_data=f"army:eqask:{key}")
    for n in _BT_QUICK:
        b.button(text=f"×{game.fa(n)}", callback_data=f"army:conf:eq:{key}:{n}")
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.button(text="⬅️ بازگشت", callback_data="army:eq")
    b.adjust(1, 3, 3, 2)
    return text, b.as_markup()


async def training_text(user: dict) -> tuple[str, InlineKeyboardMarkup]:
    """پادگان آموزش نیروی زمینی — سرباز و کماندو، زمان‌دار و صفی."""
    uid = user["user_id"]
    army = await _db.get_army(uid)
    soldier_pow = game.UNITS["soldier"]["power"]
    lines = ["🏗 <b>پادگان آموزش نیروی زمینی</b>",
             f"💰 موجودی تو: {admin_core.coins_display(user)} سکه",
             "────────────────",
             "یگان‌های زمینی <b>آنی ساخته نمی‌شوند</b>؛ پس از پرداخت، "
             "به صف آموزش می‌روند و در پایان زمان، به ارتش می‌پیوندند.",
             "────────────────"]
    for key in game.GROUND_UNITS:
        info = game.UNITS[key]
        owned = army.get(key, 0)
        lines.append(f"{info['emoji']} <b>{info['name']}</b> — {game.fa(info['cost'])}💰 هر نفر"
                     f" | زمان: {game.fa(info['train_sec'])} ثانیه/نفر"
                     f" | قدرت: {game.fa(info['power'])}⚔️"
                     + (f" ({game.fa(info['power'] // soldier_pow)}× سرباز)"
                        if key == "commando" else ""))
    training = await _db.training_get(uid)
    if training:
        info = game.UNITS.get(training["unit"], {})
        left = training["finish_ts"] - int(time.time())
        elapsed = max(0, min(int(time.time()) - training["start_ts"],
                             training["finish_ts"] - training["start_ts"]))
        total = max(1, training["finish_ts"] - training["start_ts"])
        pct = min(100, round(elapsed / total * 100)) if total else 100
        cells = round(pct / 10)
        lines.append("────────────────")
        lines.append(f"⏳ <b>در حال آموزش:</b> {info.get('emoji', '')} "
                     f"×{game.fa(training['count'])} {info.get('name', '')}")
        lines.append(f"🟩" * cells + "⬜" * (10 - cells) + f"  {game.fa(pct)}٪")
        lines.append(f"⏱ {dur_text(left)} تا پیوستن به ارتش")
    else:
        lines.append("────────────────")
        lines.append("🆓 پادگان آزاد است — یک یگان انتخاب کن.")
    b = InlineKeyboardBuilder()
    for key in game.GROUND_UNITS:
        info = game.UNITS[key]
        b.button(text=f"🎖 آموزش {info['name']} ({game.fa(info['cost'])}💰)",
                 callback_data=f"army:trask:{key}")
    nav_buttons(b, NAV_ARMY)
    return "\n".join(lines), b.as_markup()


# ================================================================ ورود تعداد
def qty_prompt_text(info: dict, flow: str) -> str:
    verb = "خرید" if flow == "eq" else "آموزش"
    extra = "" if flow == "eq" else (
        f"\n⏱ زمان: <b>{game.fa(info['train_sec'])} ثانیه به ازای هر نفر</b>")
    return (
        f"{info['emoji']} <b>{verb} {info['name']}</b>\n"
        f"────────────────\n"
        f"💵 قیمت هر {info['name']}: <b>{game.fa(info['cost'])}</b> سکه"
        f" | ⚔️ قدرت: {game.fa(info['power'])}{extra}\n"
        f"────────────────\n"
        f"🔢 چند {info['name']} می‌خواهی؟ عددی بین ۱ تا {game.fa(MAX_QTY)} بفرست.\n"
        f"💡 یا از دکمه‌های سریع زیر استفاده کن."
    )


def qty_ask_kb(flow: str, key: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for n in _BT_QUICK:
        b.button(text=f"×{game.fa(n)}", callback_data=f"army:conf:{flow}:{key}:{n}")
    b.button(text="❌ لغو", callback_data=f"army:back:{flow}")
    b.adjust(3, 3, 1)
    return b.as_markup()


async def confirm_view(uid: int, user: dict, flow: str, key: str,
                       qty: int) -> tuple[str, InlineKeyboardMarkup] | None:
    info = game.UNITS.get(key)
    if not info:
        return None
    valid = key in (game.EQUIPMENT_UNITS if flow == "eq" else game.GROUND_UNITS)
    if not valid or not (1 <= qty <= MAX_QTY):
        return None
    total = info["cost"] * qty
    secs = qty * info.get("train_sec", 0) if flow == "tr" else 0
    owned = (await _db.get_army(uid)).get(key, 0)
    coins = user.get("coins", 0)
    enough = await admin_core.can_pay(user, total)   # مدیر: همیشه True
    head = f"🧾 <b>تأیید {('خرید' if flow == 'eq' else 'آموزش')}</b>"
    lines = [
        head,
        "────────────────",
        f"{info['emoji']} {info['name']} × {game.fa(qty)}",
        f"💵 جمع قیمت: <b>{game.fa(total)}</b> سکه",
        f"💰 موجودی تو: {admin_core.coins_display(user)} سکه"
        + (f" ({game.fa(coins)})" if not admin_core.is_dev(uid) else ""),
        f"🗃 اکنون داری: {game.fa(owned)} عدد",
        f"⚔️ قدرت افزوده‌شده: {game.fa(qty * info['power'])}",
    ]
    if flow == "tr":
        lines.append(f"⏱ زمان آموزش: <b>{dur_text(secs)}</b> "
                     "(پس از پایان، خودکار به ارتش می‌پیوندند)")
    if not enough:
        lines.append("⚠️ سکهٔ کافی نداری! این سفارش تکمیل نمی‌شود.")
    lines.append("────────────────")
    b = InlineKeyboardBuilder()
    btn = "✅ تأیید خرید" if flow == "eq" else "✅ شروع آموزش"
    b.button(text=f"{btn} — {game.fa(total)}💰",
             callback_data=f"army:done:{flow}:{key}:{qty}")
    b.button(text="❌ انصراف", callback_data=f"army:back:{flow}")
    b.adjust(1, 1)
    return "\n".join(lines), b.as_markup()


def _arrival_line(user_id: int) -> str:
    """نیروهای تازه‌رسیدهٔ انبارشده را برمی‌دارد و یک خط اطلاع‌رسانی می‌سازد."""
    arrivals = _arrived.pop(user_id, [])
    if not arrivals:
        return ""
    parts = []
    for r in arrivals:
        info = game.UNITS.get(r["unit"], {})
        parts.append(f"{info.get('emoji', '')}×{game.fa(r['count'])} {info.get('name', '')}")
    return f"🎉 <b>نیروهای تازه‌رسیده به ارتش پیوستند:</b> {'، '.join(parts)}\n"


# ================================================================ هندلرها — ناوبری
@router.message(F.text == "🪖 ارتش")
async def on_army(message: Message) -> None:
    user = await _ensure_msg(message)
    army = await _db.get_army(user["user_id"])
    training = await _db.training_get(user["user_id"])
    extra = _arrival_line(user["user_id"])
    await message.answer(extra + army_landing_text(user, army, training),
                         reply_markup=army_landing_kb())


@router.callback_query(F.data == NAV_ARMY)
async def cb_nav_army(cb: CallbackQuery) -> None:
    user = await _ensure_cb(cb)
    army = await _db.get_army(user["user_id"])
    training = await _db.training_get(user["user_id"])
    extra = _arrival_line(user["user_id"])
    await cb.message.edit_text(extra + army_landing_text(user, army, training),
                               reply_markup=army_landing_kb())
    await cb.answer()


@router.callback_query(F.data == "army:my")
async def cb_army_my(cb: CallbackQuery) -> None:
    user = await _ensure_cb(cb)
    text, kb = await my_army_text(user)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "army:eq")
async def cb_army_eq(cb: CallbackQuery) -> None:
    user = await _ensure_cb(cb)
    text, kb = await equipment_text(user)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "army:tr")
async def cb_army_tr(cb: CallbackQuery) -> None:
    user = await _ensure_cb(cb)
    text, kb = await training_text(user)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


# ================================================================ هندلرها — انتخاب و تعداد
@router.callback_query(F.data.startswith("army:eqview:"))
async def cb_eq_view(cb: CallbackQuery) -> None:
    key = cb.data.split(":")[-1]
    user = await _ensure_cb(cb)
    view = await equipment_view(user["user_id"], key)
    if view is None:
        await cb.answer("❌ تجهیز ناشناخته!", show_alert=True)
        return
    text, kb = view
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("army:eqask:"))
async def cb_eq_ask(cb: CallbackQuery) -> None:
    key = cb.data.split(":")[-1]
    if key not in game.EQUIPMENT_UNITS:
        await cb.answer("❌ تجهیز ناشناخته!", show_alert=True)
        return
    await _ensure_cb(cb)
    _pending_qty[cb.from_user.id] = ("eq", key)
    await cb.message.edit_text(qty_prompt_text(game.UNITS[key], "eq"),
                               reply_markup=qty_ask_kb("eq", key))
    await cb.answer("🔢 منتظر عدد توأم…")


@router.callback_query(F.data.startswith("army:trask:"))
async def cb_tr_ask(cb: CallbackQuery) -> None:
    key = cb.data.split(":")[-1]
    user = await _ensure_cb(cb)
    if key not in game.GROUND_UNITS:
        await cb.answer("❌ یگان ناشناخته!", show_alert=True)
        return
    if await _training_active(user["user_id"]):
        text, kb = await training_text(user)
        await cb.message.edit_text(text, reply_markup=kb)
        await cb.answer("⏳ پادگان مشغول آموزش است!", show_alert=True)
        return
    _pending_qty[cb.from_user.id] = ("tr", key)
    await cb.message.edit_text(qty_prompt_text(game.UNITS[key], "tr"),
                               reply_markup=qty_ask_kb("tr", key))
    await cb.answer("🔢 منتظر عدد توأم…")


class ArmyQtyPending(BaseFilter):
    """فقط پیام‌های متنیِ کاربرانی که در انتظار ورود تعداد هستند."""

    async def __call__(self, event: Message) -> bool:
        if not event.from_user or event.from_user.id not in _pending_qty:
            return False
        text = (event.text or "").strip()
        if not text:
            return False
        from .menu import MENU_BUTTONS
        if text in MENU_BUTTONS:      # ناوبری پایین چت همیشه کار می‌کند
            return False
        return True


@router.message(ArmyQtyPending(), F.text)
async def on_qty_input(message: Message) -> None:
    uid = message.from_user.id
    flow, key = _pending_qty.get(uid, ("eq", ""))
    qty = parse_qty(message.text or "")
    if qty is None:
        await message.answer(
            f"❌ لطفاً فقط عدد صحیح بین ۱ تا {game.fa(MAX_QTY)} بفرست"
            " (ارقام فارسی هم قبول است) — یا «❌ لغو» را بزن.")
        return
    _pending_qty.pop(uid, None)
    user = await _ensure_msg(message)
    view = await confirm_view(uid, user, flow, key, qty)
    if view is None:
        await message.answer("❌ سفارش نامعتبر شد؛ دوباره از منوی ارتش اقدام کن.")
        return
    text, kb = view
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("army:conf:"))
async def cb_conf(cb: CallbackQuery) -> None:
    try:
        _, _, flow, key, qty_s = cb.data.split(":")
        qty = int(qty_s)
    except (ValueError, IndexError):
        await cb.answer("❌ درخواست نامعتبر!", show_alert=True)
        return
    _pending_qty.pop(cb.from_user.id, None)
    user = await _ensure_cb(cb)
    view = await confirm_view(user["user_id"], user, flow, key, qty)
    if view is None:
        await cb.answer("❌ یگان یا تعداد نامعتبر است!", show_alert=True)
        return
    text, kb = view
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("army:back:"))
async def cb_back(cb: CallbackQuery) -> None:
    flow = cb.data.split(":")[-1]
    _pending_qty.pop(cb.from_user.id, None)
    user = await _ensure_cb(cb)
    text, kb = (await equipment_text(user)) if flow == "eq" else (await training_text(user))
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


# ================================================================ هندلرها — اجرای عملیات
@router.callback_query(F.data.startswith("army:done:"))
async def cb_done(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    try:
        _, _, flow, key, qty_s = parts
        qty = int(qty_s)
    except (ValueError, IndexError):
        await cb.answer("❌ درخواست نامعتبر!", show_alert=True)
        return
    user = await _ensure_cb(cb)
    uid = user["user_id"]
    info = game.UNITS.get(key)
    valid_key = info and (
        (flow == "eq" and key in game.EQUIPMENT_UNITS)
        or (flow == "tr" and key in game.GROUND_UNITS))
    if not valid_key or not (1 <= qty <= MAX_QTY):
        await cb.answer("❌ یگان یا تعداد نامعتبر است!", show_alert=True)
        return
    total = info["cost"] * qty

    if flow == "eq":
        # ---- خرید فوری تجهیزات
        if not await admin_core.pay(user, total):
            await cb.answer(f"❌ سکه کافی نداری! لازم: {game.fa(total)}💰", show_alert=True)
            return
        army = await _db.get_army(uid)
        await _db.set_unit(uid, key, army.get(key, 0) + qty)
        await hooks.after_purchase(uid, qty, total)
        new_power = game.attack_power(await _db.get_army(uid))
        await cb.answer(f"✅ {info['name']} ×{game.fa(qty)} تحویل ارتش شد!", show_alert=True)
        user = await _db.get_user(uid)
        b = InlineKeyboardBuilder()
        b.button(text="🪖 ارتش من", callback_data="army:my")
        b.button(text="🛒 ادامه خرید", callback_data="army:eq")
        b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
        b.adjust(2, 1)
        await cb.message.edit_text(
            f"{info['emoji']} <b>{info['name']} × {game.fa(qty)}</b> خریداری شد!\n"
            f"💸 پرداخت: {game.fa(total)} سکه | 💰 موجودی: {admin_core.coins_display(user)}\n"
            f"⚔️ قدرت کل ارتش اکنون: <b>{game.fa(new_power)}</b>",
            reply_markup=b.as_markup())
        return

    # ---- آموزش نیروی زمینی
    if await _training_active(uid):
        user = await _db.get_user(uid)
        text, kb = await training_text(user)
        await cb.message.edit_text(text, reply_markup=kb)
        await cb.answer("⏳ پادگان مشغول است؛ اول آموزش قبلی تمام شود.", show_alert=True)
        return
    if not await admin_core.pay(user, total):
        await cb.answer(f"❌ سکه کافی نداری! لازم: {game.fa(total)}💰", show_alert=True)
        return
    now = int(time.time())
    secs = qty * info.get("train_sec", 0)
    if admin_core.no_cooldown(uid):
        secs = 0  # مدیر/تست‌کننده: بدون زمان انتظار (تست سریع)
    await _db.training_start(uid, key, qty, now, now + secs, total)
    await hooks.after_purchase(uid, 0, total)   # مأموریت «خرج سکه» همان لحظهٔ پرداخت
    user = await _db.get_user(uid)
    if secs <= 0:
        done = await _db.settle_training(uid)
        for r in done:
            await hooks.after_purchase(uid, r["count"], 0)
        await cb.message.edit_text(
            f"✅ {info['emoji']} ×{game.fa(qty)} {info['name']} فوراً آماده شد!\n"
            f"💸 پرداخت: {game.fa(total)} سکه | 💰 موجودی: {admin_core.coins_display(user)}",
            reply_markup=None)
    else:
        text, kb = await training_text(user)
        await cb.message.edit_text(text, reply_markup=kb)
        await cb.answer(f"🏗 آموزش آغاز شد! ⏱ {dur_text(secs)}", show_alert=True)
