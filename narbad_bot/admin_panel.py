"""👑 پنل مدیریت ربات نبردگاه — فقط برای شناسه‌های DEVELOPER_IDS.

دستورها:
    /admin            → باز کردن پنل مدیریت
    /myid             → نمایش شناسهٔ عددی خودت (برای افزودن به admins.py)

جریان هر عملیات به این شکل است:
    ۱) دکمهٔ عملیات → ربات «قالب ورودی» را می‌پرسد
    ۲) مدیر پیام متنی می‌فرستد (مثلاً: 123456789 50000)
    ۳) ربات اعتبارسنجی کرده، عملیات را اجرا و نتیجه را گزارش می‌دهد

امنیت: تمام بررسی‌های دسترسی داینامیک است (admin_core.is_dev) و هیچ
مقدار بی‌نهایتی در دیتابیس نوشته نمی‌شود؛ بازیکنان عادی تحت تأثیر قرار
نمی‌گیرند.
"""
from __future__ import annotations

import logging
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import admins, admin_core, game
from .db import DB

router = Router(name="admin")

_db: DB | None = None
log = logging.getLogger(__name__)

# عملیات در انتظار ورودی (فقط در حافظه — با ری‌استارت پاک می‌شود)
_pending: dict[int, str] = {}

# سقف‌های ایمن برای جلوگیری از خرابی دیتابیس
MAX_COINS = 1_000_000_000
MAX_XP = 10_000_000
MAX_LEVEL = 200
MAX_COUNT = 100_000

GIVEABLE_UNITS = list(game.UNITS) + list(game.DEFENSES)
GIVEABLE_ITEMS = [k for k, v in game.ITEMS.items() if v["kind"] != "pack"]


def setup(db: DB) -> None:
    global _db
    _db = db


# ────────────────────────────── ابزارهای اعتبارسنجی ─────────────────────────
def parse_two_ints(text: str) -> tuple[int, int] | None:
    parts = text.split()
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def parse_three(text: str) -> tuple[int, str, int] | None:
    """فرمت: <شناسه> <کلید> <تعداد>"""
    parts = text.split()
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), parts[1].lower(), int(parts[2])
    except ValueError:
        return None


def resolve_user_id(text_part: str) -> int:
    """شناسهٔ عددی یا یوزرنیم (@name) را به user_id تبدیل می‌کند.

    ناموفق → ۰ (بالادستی رد می‌کند)
    """
    t = text_part.strip().replace("@", "")
    try:
        return int(t)
    except ValueError:
        return 0


# ────────────────────────────────── دستورها ─────────────────────────────────
@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    """نمایش شناسهٔ عددی — برای افزودن به admins.py"""
    u = message.from_user
    is_dev = admins.is_developer(u.id)
    is_tst = admins.is_tester(u.id)
    await message.answer(
        f"🆔 شناسهٔ عددی شما: <code>{u.id}</code>\n"
        f"👑 مدیر کل: {'بله ✅' if is_dev else 'خیر'}\n"
        f"🧪 تست‌کننده: {'بله ✅' if is_tst else 'خیر'}\n"
        "برای افزودن خود به مدیران، این عدد را در "
        "<code>narbad_bot/admins.py</code> → <code>DEVELOPER_IDS</code> بگذارید."
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    u = message.from_user
    if not admins.is_developer(u.id):
        await message.answer("⛔ دسترسی غیرمجاز! این دستور فقط برای مدیران است.")
        return
    await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    await message.answer(admin_panel_text(), reply_markup=admin_panel_kb())


@router.callback_query(F.data == "admin:panel")
async def cb_admin_panel(cb: CallbackQuery) -> None:
    u = cb.from_user
    if not admins.is_developer(u.id):
        await cb.answer("⛔ دسترسی غیرمجاز!", show_alert=True)
        return
    await cb.message.edit_text(admin_panel_text(), reply_markup=admin_panel_kb())
    await cb.answer()


def admin_panel_text() -> str:
    return (
        "👑 <b>پنل مدیریت نبردگاه</b>\n"
        "────────────────\n"
        "هر دکمه را بزن، سپس طبق قالبِ خواسته‌شده پیام بفرست.\n"
        "• شناسهٔ کاربران را از /myid یا پروفایل می‌گیرید.\n"
        "• این پنل فقط برای DEVELOPER_IDS فعال است.\n"
        "• هیچ مقدار بی‌نهایتی در دیتابیس ذخیره نمی‌شود.\n"
        "================================\n"
        f"👑 مدیران فعال: {len(admins.DEVELOPER_IDS)} نفر\n"
        f"🧪 تست‌کننده‌ها: {len(admins.TESTER_IDS)} نفر"
    )


def admin_panel_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💵 افزودن سکه", callback_data="adm:coins")
    b.button(text="⭐ افزودن تجربه", callback_data="adm:xp")
    b.button(text="🎚 تغییر سطح", callback_data="adm:level")
    b.button(text="🪖 دادن یگان", callback_data="adm:unit")
    b.button(text="🎒 بازکردن آیتم", callback_data="adm:item")
    b.button(text="🧪 نبرد آزمایشی", callback_data="adm:battle")
    b.button(text="👤 اطلاعات بازیکن", callback_data="adm:info")
    b.button(text="🧹 ریست حساب تست", callback_data="adm:reset")
    b.button(text="📜 راهنمای قالب‌ها", callback_data="adm:help")
    b.adjust(2)
    return b.as_markup()


# ────────────────────────────── انتخاب عملیات ───────────────────────────────
_PROMPTS = {
    "adm:coins":  "💵 <b>افزودن سکه</b>\nقالب: <code>&lt;شناسه&gt; &lt;مقدار&gt;</code>\nمثال: <code>123456789 50000</code>\nسقف مجاز: ۱٬۰۰۰٬۰۰۰٬۰۰۰",
    "adm:xp":     "⭐ <b>افزودن تجربه</b>\nقالب: <code>&lt;شناسه&gt; &lt;مقدار&gt;</code>\nمثال: <code>123456789 1500</code>",
    "adm:level":  "🎚 <b>تغییر سطح</b>\nقالب: <code>&lt;شناسه&gt; &lt;سطح&gt;</code>\nمثال: <code>123456789 20</code> (سقف ۲۰۰)",
    "adm:unit":   (f"🪖 <b>دادن یگان</b>\nقالب: <code>&lt;شناسه&gt; &lt;کلید&gt; &lt;تعداد&gt;</code>\n"
                   f"کلیدها: {', '.join(GIVEABLE_UNITS)}\nمثال: <code>123456789 tank 10</code>"),
    "adm:item":   (f"🎒 <b>بازکردن آیتم</b>\nقالب: <code>&lt;شناسه&gt; &lt;کلید&gt; &lt;تعداد&gt;</code>\n"
                   f"کلیدها: {', '.join(GIVEABLE_ITEMS)}\nمثال: <code>123456789 energy_pack 5</code>"),
    "adm:battle": "🧪 <b>نبرد آزمایشی</b>\nقالب: <code>&lt;مهاجم&gt; &lt;مدافع&gt;</code>\nمثال: <code>123456789 987654321</code>\n⚠️ این نبرد فقط شبیه‌سازی است؛ چیزی از بازیکنان کم یا زیاد نمی‌شود.",
    "adm:info":   "👤 <b>اطلاعات بازیکن</b>\nقالب: <code>&lt;شناسه یا یوزرنیم&gt;</code>\nمثال: <code>123456789</code> یا <code>@username</code>",
    "adm:reset":  "🧹 <b>ریست حساب تست</b>\nقالب: <code>&lt;شناسه&gt;</code>\n⚠️ کل ارتش، سکه، سطح، آیتم و مأموریت‌ها به حالت اولیه برمی‌گردد.",
}

_ACTIONS = {"adm:coins", "adm:xp", "adm:level", "adm:unit",
            "adm:item", "adm:battle", "adm:info", "adm:reset"}


@router.callback_query(F.data.startswith("adm:"))
async def cb_adm(cb: CallbackQuery) -> None:
    u = cb.from_user
    if not admins.is_developer(u.id):
        await cb.answer("⛔ دسترسی غیرمجاز!", show_alert=True)
        return
    action = cb.data
    if action == "adm:help":
        await cb.answer("برای هر عملیات: دکمه را بزن → قالب را ببین → پیام بفرست",
                        show_alert=True)
        return
    if action not in _ACTIONS:
        return
    _pending[u.id] = action
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 لغو عملیات", callback_data="adm:cancel")]
    ])
    await cb.message.edit_text(_PROMPTS[action], reply_markup=cancel_kb)
    await cb.answer()


@router.callback_query(F.data == "adm:cancel")
async def cb_adm_cancel(cb: CallbackQuery) -> None:
    u = cb.from_user
    if not admins.is_developer(u.id):
        return
    _pending.pop(u.id, None)
    await cb.message.edit_text("🚫 عملیات لغو شد.", reply_markup=None)
    await cb.answer()


# ─────────────────────────────── پردازش ورودی ───────────────────────────────
@router.message()
async def on_admin_input(message: Message) -> None:
    """دریافت ورودی متنی مدیر وقتی عملیاتی در انتظار است.

    ⚠️  این هندلر به‌عنوان آخرین گزینه ثبت شده؛ اگر عملیاتِ در انتظار
    نباشد، بدون هیچ کاری برمی‌گردد تا بقیهٔ بازی مختل نشود.
    """
    u = message.from_user
    if not u or u.id not in _pending:
        return
    if not admins.is_developer(u.id):
        _pending.pop(u.id, None)
        return

    action = _pending.pop(u.id)
    text = (message.text or "").strip()
    if not text:
        await message.answer("❌ ورودی خالی بود!")
        return

    try:
        if action in ("adm:coins", "adm:xp", "adm:level", "adm:info", "adm:reset"):
            await _handle_simple(action, message, text)
        elif action in ("adm:unit", "adm:item"):
            await _handle_give(action, message, text)
        elif action == "adm:battle":
            await _handle_battle(message, text)
    except Exception:  # noqa: BLE001 — گزارش ولی نکشتن ربات
        log.exception("خطا در اجرای عملیات مدیریتی %s", action)
        await message.answer("❌ خطای غیرمنتظره! لاگ را بررسی کن.")


async def _handle_simple(action: str, message: Message, text: str) -> None:
    parts = text.split()
    if action in ("adm:info", "adm:reset") and len(parts) == 1:
        uid = resolve_user_id(parts[0])
        if not uid:
            # شاید یوزرنیم باشد
            user = await _db.find_by_username(parts[0])
            uid = user["user_id"] if user else 0
        if action == "adm:info":
            await _show_info(message, uid)
        else:
            await _do_reset(message, uid)
        return

    pair = parse_two_ints(text)
    if not pair:
        await message.answer("❌ قالب اشتباه! راهنمای قالب‌ها را با /admin ببین.")
        return
    uid, value = pair
    user = await _db.get_user(uid)
    if not user:
        await message.answer("❌ بازیکنی با این شناسه پیدا نشد!")
        return

    if action == "adm:coins":
        if not (0 <= value <= MAX_COINS):
            await message.answer(f"❌ مقدار مجاز بین ۰ تا {game.fa(MAX_COINS)} است.")
            return
        await _db.update_user(uid, coins=user["coins"] + value)
        await message.answer(
            f"✅ {game.fa(value)} سکه به {game.fa(uid)} اضافه شد.\n"
            f"💰 موجودی جدید: {game.fa(user['coins'] + value)}")
    elif action == "adm:xp":
        if not (0 <= value <= MAX_XP):
            await message.answer(f"❌ مقدار مجاز بین ۰ تا {game.fa(MAX_XP)} است.")
            return
        xp, lvl, gained, bonus = game.add_xp(user["xp"], user["level"], value)
        await _db.update_user(uid, xp=xp, level=lvl)
        await message.answer(
            f"✅ {game.fa(value)} تجربه اضافه شد.\n"
            f"⭐ تجربه: {game.fa(xp)} | سطح: {game.fa(lvl)}"
            + (f" | 🎉 {game.fa(gained)} ارتقا!" if gained else ""))
    elif action == "adm:level":
        if not (1 <= value <= MAX_LEVEL):
            await message.answer(f"❌ سطح مجاز بین ۱ تا {game.fa(MAX_LEVEL)} است.")
            return
        await _db.update_user(uid, level=value)
        await message.answer(f"✅ سطح {game.fa(uid)} به {game.fa(value)} تغییر کرد.")


async def _handle_give(action: str, message: Message, text: str) -> None:
    triple = parse_three(text)
    if not triple:
        await message.answer("❌ قالب اشتباه! قالب: <شناسه> <کلید> <تعداد>")
        return
    uid, key, count = triple
    if not (0 < count <= MAX_COUNT):
        await message.answer(f"❌ تعداد مجاز بین ۱ تا {game.fa(MAX_COUNT)} است.")
        return
    user = await _db.get_user(uid)
    if not user:
        await message.answer("❌ بازیکنی با این شناسه پیدا نشد!")
        return

    if action == "adm:unit":
        if key not in GIVEABLE_UNITS:
            await message.answer(f"❌ کلید یگان نامعتبر! کلیدها: {', '.join(GIVEABLE_UNITS)}")
            return
        if key in game.DEFENSES:
            await _db.set_defense(uid, key, count, 100)
            disp = game.DISP.get(key, {})
            await message.answer(
                f"✅ {disp.get('emoji', '')} سازه دفاعی {disp.get('name', key)} "
                f"(سطح {game.fa(count)}) برای {game.fa(uid)} تنظیم شد.")
            return
        army = await _db.get_army(uid)
        await _db.set_unit(uid, key, army.get(key, 0) + count)
        disp = game.DISP.get(key, {})
        await message.answer(
            f"✅ {disp.get('emoji', '')} {game.fa(count)} عدد "
            f"{disp.get('name', key)} به ارتش {game.fa(uid)} اضافه شد.")
    else:
        if key not in GIVEABLE_ITEMS:
            await message.answer(f"❌ کلید آیتم نامعتبر! کلیدها: {', '.join(GIVEABLE_ITEMS)}")
            return
        await _db.inv_add(uid, key, count)
        item = game.ITEMS[key]
        await message.answer(
            f"✅ {item['emoji']} {game.fa(count)} عدد {item['name']} "
            f"برای {game.fa(uid)} باز شد.")


async def _handle_battle(message: Message, text: str) -> None:
    pair = parse_two_ints(text)
    if not pair:
        await message.answer("❌ قالب: <شناسه مهاجم> <شناسه مدافع>")
        return
    att_id, def_id = pair
    result = await admin_core.simulate_test_battle(att_id, def_id)
    if not result.get("ok"):
        await message.answer(f"❌ {result.get('reason', 'نامشخص')}")
        return
    winner = "مهاجم 🏆" if result["winner"] == "attacker" else "مدافع 🛡"
    await message.answer(
        f"🧪 <b>نتیجهٔ نبرد آزمایشی</b> (بدون تغییر در دیتابیس)\n"
        f"────────────────\n"
        f"⚔️ قدرت مهاجم: {game.fa(result['att_power'])}\n"
        f"🛡 قدرت مدافع: {game.fa(result['def_power'])}\n"
        f"💥 تلفات مهاجم: {game.cas_text(result['att_cas'])}\n"
        f"💥 تلفات مدافع: {game.cas_text(result['def_cas'])}\n"
        f"💰 غنیمت احتمالی: {game.fa(result['loot'])} سکه\n"
        f"🏆 برنده: {winner}")


async def _show_info(message: Message, uid: int) -> None:
    user = await _db.get_user(uid)
    if not user:
        await message.answer("❌ بازیکنی با این شناسه پیدا نشد!")
        return
    army = await _db.get_army(uid)
    defenses = await _db.get_defenses(uid)
    power = game.attack_power(army)
    defense = game.defense_power(army, defenses, base_level=user["level"])
    inv = await _db.inv_get(uid)
    buffs = await _db.buffs_active(uid)
    missions = await _db.missions_today(uid)
    claimed = sum(1 for m in missions.values() if m["claimed"])
    energy, _ = game.effective_energy(user)
    clan_name = ""
    if user.get("clan_id"):
        clan = await _db.get_clan(user["clan_id"])
        clan_name = f" — 🏰 {clan['name']}" if clan else ""

    await message.answer(
        f"👤 <b>اطلاعات بازیکن</b>\n"
        f"────────────────\n"
        f"🆔 شناسه: <code>{uid}</code> | یوزرنیم: @{user.get('username') or '—'}\n"
        f"🎖 نام: {user.get('first_name') or '—'}\n"
        f"🏅 سطح: {game.fa(user['level'])} | ⭐ تجربه: {game.fa(user['xp'])}\n"
        f"💰 سکه: {game.fa(user['coins'])} | ⚡ انرژی: {game.fa(energy)}"
        f"{clan_name}\n"
        f"⚔️ قدرت: {game.fa(power)} | 🛡 دفاع: {game.fa(defense)}\n"
        f"🏆 برد: {game.fa(user['wins'])} | باخت: {game.fa(user['losses'])}\n"
        f"🔒 دفع: {game.fa(user['def_wins'])} | باخت دفاع: {game.fa(user['def_losses'])}\n"
        f"🎒 آیتم‌ها: {game.fa(len(inv))} نوع | ✨ بافت فعال: {game.fa(len(buffs))}\n"
        f"🎯 مأموریت‌های امروز: {game.fa(claimed)}/{game.fa(len(game.MISSIONS))} دریافت‌شده\n"
        f"🛡 سپر: {'فعال 🟢' if user['shield_until'] > time.time() else 'غیرفعال ⚪'}"
    )


async def _do_reset(message: Message, uid: int) -> None:
    user = await _db.get_user(uid)
    if not user:
        await message.answer("❌ بازیکنی با این شناسه پیدا نشد!")
        return
    await _db.reset_player(uid)
    await message.answer(
        f"🧹 <b>حساب {game.fa(uid)} ریست شد!</b>\n"
        f"💰 سکه: {game.fa(game.START_COINS)} | سطح ۱ | ۵ 🪖 سرباز\n"
        "آیتم/بافت/مأموریت/معدن/رشد پاک شد و هدیهٔ تست‌کننده دوباره اعمال می‌شود."
    )
