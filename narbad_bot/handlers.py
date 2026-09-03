"""هندلرهای ربات نبردگاه — دستورات، دکمه‌ها و منطق نبرد."""
from __future__ import annotations

import html
import time

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import admin_core, game, hooks
from .db import DB

router = Router(name="game")

_db: DB | None = None

# مهاجم -> (مدافع -> زمان آخرین حمله) برای جلوگیری از اسپم
_cooldowns: dict[tuple[int, int], float] = {}


def setup(db: DB) -> None:
    global _db
    _db = db


# ================================================================ ابزارها
def esc(t: str) -> str:
    return html.escape(str(t))


def name_of(u: dict | None) -> str:
    if not u:
        return "بازیکن ناشناس"
    return u.get("first_name") or u.get("username") or "بازیکن ناشناس"


async def me(message: Message) -> dict:
    u = message.from_user
    return await _db.ensure_user(u.id, u.username or "", u.first_name or "")


async def me_cb(cb: CallbackQuery) -> dict:
    u = cb.from_user
    return await _db.ensure_user(u.id, u.username or "", u.first_name or "")


def coin(u: dict) -> int:
    return u.get("coins", 0)


def energy_line(u: dict) -> str:
    # مدیران «∞» می‌بینند (داینامیک؛ بدون تغییر در دیتابیس)
    return f"⚡ انرژی: {admin_core.energy_display(u)}"


# ================================================================ صفحه‌ها
def train_text(u: dict) -> str:
    return (
        f"⚔️ <b>لشکرکشی — آموزش یگان</b>\n"
        f"💰 موجودی: <b>{admin_core.coins_display(u)}</b> سکه\n"
        f"{energy_line(u)}\n"
        f"────────────────\n"
        "یگان مورد نظر را انتخاب کن، سپس تعداد و تأیید خرید را انجام بده:\n"
        "👑 مدیران: خریدها رایگان و نامحدود است."
    )


def defense_text(u: dict) -> str:
    return (
        f"🛡 <b>تجهیزات دفاعی</b>\n"
        f"💰 موجودی: <b>{admin_core.coins_display(u)}</b> سکه\n"
        f"{energy_line(u)}\n"
        f"────────────────\n"
        "سازه‌های دفاعی قدرت دفاع پایگاه شما را بالا می‌برند (هر بار ۱ عدد):\n"
        "👑 مدیران: خریدها رایگان و نامحدود است."
    )


def train_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, u_ in game.UNITS.items():
        b.button(
            text=f"{u_['emoji']} {u_['name']} — {game.fa(u_['cost'])}💰 هر عدد",
            callback_data=f"unit:select:{key}",
        )
    b.button(text="🛡 تجهیزات دفاعی", callback_data="nav:defense")
    b.button(text="⬅️ بازگشت", callback_data="nav:army")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(1)
    return b.as_markup()

def qty_kb(unit_key: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for qty in [1, 5, 10, 25, 50, 100]:
        total = game.UNITS[unit_key]["cost"] * qty
        b.button(text=f"×{game.fa(qty)} — {game.fa(total)}💰", callback_data=f"unit:qty:{unit_key}:{qty}")
    b.button(text="⬅️ بازگشت", callback_data="unit:back")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(3, 3, 2)
    return b.as_markup()

def confirm_kb(unit_key: str, qty: int) -> InlineKeyboardMarkup:
    total = game.UNITS[unit_key]["cost"] * qty
    b = InlineKeyboardBuilder()
    b.button(text=f"✅ تأیید خرید — {game.fa(total)}💰", callback_data=f"unit:confirm:{unit_key}:{qty}")
    b.button(text="❌ انصراف", callback_data="unit:cancel")
    b.adjust(1)
    return b.as_markup()


def defense_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, d_ in game.DEFENSES.items():
        b.button(
            text=f"{d_['emoji']} {d_['name']} — {game.fa(d_['cost'])}💰",
            callback_data=f"buydef:{key}:1",
        )
    b.button(text="⚔️ خرید یگان", callback_data="nav:army")
    b.button(text="⬅️ بازگشت", callback_data="nav:defense")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(1)
    return b.as_markup()


# ================================================================ /start
@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    u = await me(message)
    from .menu import main_menu_kb
    welcome = (
        f"🎖 <b>به «نبردگاه» خوش آمدی {esc(name_of(u))}!</b>\n"
        f"اینجا یک میدان جنگ است؛ ارتش خودت را بساز، به رقیبان حمله کن و "
        "سکه غنیمت بگیر!\n"
        f"────────────────\n"
        f"💰 {game.fa(coin(u))} سکه و {game.fa(game.START_SOLDIERS)} 🪖 سرباز هدیه گرفتی.\n\n"
        f"🎮 <b>همه چیز از طریق منوی پایین قابل دسترسی است:</b>\n"
        f"🏠 پایگاه — پروفایل، جایزه، مأموریت، معدن، نمودار، رده‌بندی\n"
        f"🪖 ارتش — آموزش یگان، ارتقا، موجودی\n"
        f"🛡 دفاع — خرید و ارتقای سازه‌ها، سپر\n"
        f"⚔️ نبرد — نبرد تصادفی (تنها روش حمله)، تاریخچه\n"
        f"🏰 اتحادیه — قبیله، جنگ، قلمروها\n"
        f"🛒 فروشگاه — خرید آیتم، موجودی\n\n"
        f"💡 دستورات خاص: /attack (حمله تصادفی)، /gift (هدیه)، /myid"
    )
    await message.answer(welcome, reply_markup=main_menu_kb())


# ================================================================ /help
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await me(message)
    text = (
        "📜 <b>راهنمای نبردگاه</b>\n"
        "────────────────\n"
        "🎮 <b>منوی اصلی (پایین چت):</b>\n"
        "🏠 پایگاه — 👤 پروفایل، 🎁 جایزه روزانه، 🎯 مأموریت‌ها، ⛏ معدن، 📈 نمودار رشد، 🏆 رده‌بندی، 📜 تاریخچه، 🛡️ سپر\n"
        "🪖 ارتش — 🎓 آموزش یگان (۹ یگان)، 🗃️ ارتش من، ⬆️ ارتقای یگان\n"
        "🛡 دفاع — 🧱 خرید سازه، ⬆️ ارتقای دفاع (۴ سازه)، 🛡️ سپر\n"
        "⚔️ نبرد — 🎲 نبرد تصادفی، 🎯 منوی حمله، 📜 تاریخچه، 📊 اطلاعات نبرد\n"
        "🏰 اتحادیه — 🏰 اتحادیه من، 📋 لیست، ⚔️ جنگ، 💰 خزانه، 🗺 قلمروها\n"
        "🛒 فروشگاه — 🏅 فروشگاه ویژه، 🎒 موجودی، ✨ آیتم‌های فعال\n"
        "────────────────\n"
        "💬 <b>دستورات خاص:</b>\n"
        "• /start — شروع و نمایش منو\n"
        "• /menu — نمایش منوی اصلی\n"
        "• /hidemenu — پنهان کردن منو\n"
        "• /attack — حمله تصادفی به حریف (تنها روش حمله)\n"
        "• /gift @user مقدار — هدیه سکه\n"
        "• /myid — نمایش شناسه عددی\n"
        "────────────────\n"
        "💡 همه قابلیت‌های عادی بازی فقط با دکمه‌های منو قابل بازی هستند!"
    )
    await message.answer(text)


# ================================================================ پروفایل
async def cmd_profile(message: Message) -> None:  # (hidden)
    u = await me(message)
    army = await _db.get_army(u["user_id"])
    structures = {k: v for k, v in army.items() if k in game.DEFENSES}
    energy, _ = game.effective_energy(u)
    power = game.attack_power(army)
    defense = game.defense_power({k: v for k, v in army.items() if k in game.UNITS}, structures)
    next_xp = game.xp_to_next(u["level"])
    bar_len = 12
    filled = round(u["xp"] / next_xp * bar_len)
    bar = "🟩" * filled + "⬜" * (bar_len - filled)

    shield = ""
    if u["shield_until"] > time.time():
        hours = int((u["shield_until"] - time.time()) // 3600)
        shield = f"\n🕊 سپر: فعال تا {game.fa(hours)} ساعت دیگر"

    text = (
        f"🎖 <b>پروفایل نظامی {esc(name_of(u))}</b>\n"
        f"────────────────\n"
        f"🏅 درجه: {game.rank_name(u['level'])} (سطح {game.fa(u['level'])})\n"
        f"⭐ تجربه: {game.fa(u['xp'])}/{game.fa(next_xp)}\n"
        f"{bar}\n"
        f"💰 سکه: {game.fa(coin(u))}\n"
        f"⚡ انرژی: {game.fa(energy)}/{game.fa(game.MAX_ENERGY)}\n"
        f"────────────────\n"
        f"⚔️ قدرت حمله: <b>{game.fa(power)}</b>\n"
        f"🛡 قدرت دفاع: <b>{game.fa(defense)}</b>\n"
        f"🏆 پیروزی‌ها: {game.fa(u['wins'])} | شکست‌ها: {game.fa(u['losses'])}\n"
        f"🛡 دفع حمله: {game.fa(u['def_wins'])} | باخت در دفاع: {game.fa(u['def_losses'])}\n"
        f"{shield}"
    )
    await message.answer(text)


# ================================================================ فروشگاه
async def cmd_train(message: Message) -> None:  # (hidden)
    u = await me(message)
    await message.answer(train_text(u), reply_markup=train_kb())


async def cmd_defense(message: Message) -> None:  # (hidden)
    u = await me(message)
    await message.answer(defense_text(u), reply_markup=defense_kb())


@router.callback_query(F.data == "menu:train")
async def cb_menu_train(cb: CallbackQuery) -> None:
    u = await me_cb(cb)
    await cb.message.edit_text(train_text(u), reply_markup=train_kb())
    await cb.answer()


@router.callback_query(F.data == "menu:defense")
async def cb_menu_defense(cb: CallbackQuery) -> None:
    u = await me_cb(cb)
    await cb.message.edit_text(defense_text(u), reply_markup=defense_kb())
    await cb.answer()


@router.callback_query(F.data == "close")
async def cb_close(cb: CallbackQuery) -> None:
    await cb.message.delete()
    await cb.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(cb: CallbackQuery) -> None:
    _, key, cnt = cb.data.split(":")
    cnt = int(cnt)
    u = await me_cb(cb)
    unit = game.UNITS[key]
    cost = unit["cost"] * cnt
    # مدیر: خرید رایگان/نامحدود (بدون کسر از دیتابیس)؛
    # دیگران: کسر عادی سکه
    if not await admin_core.pay(u, cost):
        await cb.answer("سکه کافی نداری! 🪙 با /daily جایزه بگیر.", show_alert=True)
        return
    army = await _db.get_army(u["user_id"])
    await _db.set_unit(u["user_id"], key, army.get(key, 0) + cnt)
    await hooks.after_purchase(u["user_id"], cnt, cost)
    await cb.answer(f"✅ {unit['emoji']} {unit['name']} × {game.fa(cnt)} به ارتش تو اضافه شد!")
    u = await me_cb(cb)
    await cb.message.edit_text(train_text(u), reply_markup=train_kb())


@router.callback_query(F.data.startswith("buydef:"))
async def cb_buydef(cb: CallbackQuery) -> None:
    _, key, cnt = cb.data.split(":")
    cnt = int(cnt)
    u = await me_cb(cb)
    structure = game.DEFENSES[key]
    cost = structure["cost"] * cnt
    # مدیر: رایگان؛ دیگران: کسر عادی
    if not await admin_core.pay(u, cost):
        await cb.answer("سکه کافی نداری! 🪙", show_alert=True)
        return
    army = await _db.get_army(u["user_id"])
    await _db.set_unit(u["user_id"], key, army.get(key, 0) + cnt)
    await hooks.after_purchase(u["user_id"], 0, cost)
    await cb.answer(f"✅ {structure['emoji']} {structure['name']} ساخته شد!")
    u = await me_cb(cb)
    await cb.message.edit_text(defense_text(u), reply_markup=defense_kb())

# ================================================================ خرید یگان با انتخاب تعداد و تأیید
@router.callback_query(F.data.startswith("unit:select:"))
async def cb_unit_select(cb: CallbackQuery) -> None:
    key = cb.data.split(":")[2]
    if key not in game.UNITS:
        await cb.answer("یگان نامعتبر!", show_alert=True)
        return
    u = await me_cb(cb)
    unit = game.UNITS[key]
    text = (
        f"{unit['emoji']} <b>{unit['name']}</b>\n"
        f"────────────────\n"
        f"💰 قیمت هر عدد: <b>{game.fa(unit['cost'])}</b> سکه\n"
        f"⚔️ قدرت هر عدد: <b>{game.fa(unit['power'])}</b>\n"
        f"💰 موجودی تو: {admin_core.coins_display(u)} سکه\n"
        f"────────────────\n"
        f"تعداد مورد نظر را انتخاب کن:"
    )
    await cb.message.edit_text(text, reply_markup=qty_kb(key))
    await cb.answer()

@router.callback_query(F.data.startswith("unit:qty:"))
async def cb_unit_qty(cb: CallbackQuery) -> None:
    _, _, key, qty = cb.data.split(":")
    qty = int(qty)
    if key not in game.UNITS:
        await cb.answer("یگان نامعتبر!", show_alert=True)
        return
    u = await me_cb(cb)
    unit = game.UNITS[key]
    total = unit["cost"] * qty
    text = (
        f"{unit['emoji']} <b>{unit['name']} × {game.fa(qty)}</b>\n"
        f"────────────────\n"
        f"💰 قیمت واحد: {game.fa(unit['cost'])} سکه\n"
        f"🔢 تعداد: <b>{game.fa(qty)}</b> عدد\n"
        f"💳 قیمت کل: <b>{game.fa(total)}</b> سکه\n"
        f"💰 موجودی تو: {admin_core.coins_display(u)} سکه\n"
        f"────────────────\n"
        f"آیا خرید را تأیید می‌کنی؟"
    )
    await cb.message.edit_text(text, reply_markup=confirm_kb(key, qty))
    await cb.answer()

@router.callback_query(F.data.startswith("unit:confirm:"))
async def cb_unit_confirm(cb: CallbackQuery) -> None:
    _, _, key, qty = cb.data.split(":")
    qty = int(qty)
    if key not in game.UNITS:
        await cb.answer("یگان نامعتبر!", show_alert=True)
        return
    u = await me_cb(cb)
    unit = game.UNITS[key]
    cost = unit["cost"] * qty
    if not await admin_core.pay(u, cost):
        await cb.answer("سکه کافی نداری! 🪙 با /daily جایزه بگیر.", show_alert=True)
        return
    army = await _db.get_army(u["user_id"])
    await _db.set_unit(u["user_id"], key, army.get(key, 0) + qty)
    await hooks.after_purchase(u["user_id"], qty, cost)
    await cb.answer(f"✅ {unit['emoji']} {unit['name']} × {game.fa(qty)} به ارتش تو اضافه شد!")
    u = await me_cb(cb)
    await cb.message.edit_text(train_text(u), reply_markup=train_kb())

@router.callback_query(F.data == "unit:back")
async def cb_unit_back(cb: CallbackQuery) -> None:
    u = await me_cb(cb)
    await cb.message.edit_text(train_text(u), reply_markup=train_kb())
    await cb.answer()

@router.callback_query(F.data == "unit:cancel")
async def cb_unit_cancel(cb: CallbackQuery) -> None:
    u = await me_cb(cb)
    await cb.message.edit_text(train_text(u), reply_markup=train_kb())
    await cb.answer()
    # keep menu open, return to train list


# ================================================================ سپر
async def cmd_shield(message: Message) -> None:  # (hidden)
    u = await me(message)
    if u["shield_until"] > time.time():
        hours = int((u["shield_until"] - time.time()) // 3600)
        await message.answer(f"🕊 سپر تو فعاله و تا {game.fa(hours)} ساعت دیگه ادامه داره!")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🕊 سپر ۶ ساعته — {game.fa(game.SHIELD_COSTS[6])}💰",
                              callback_data="shield:6")],
        [InlineKeyboardButton(text=f"🕊 سپر ۲۴ ساعته — {game.fa(game.SHIELD_COSTS[24])}💰",
                              callback_data="shield:24")],
    ])
    await message.answer(
        f"🕊 <b>سپر محافظتی</b>\n"
        f"تا وقتی سپر داری هیچ‌کس نمی‌تونه به تو حمله کنه!\n"
        f"💰 موجودی: {game.fa(coin(u))} سکه",
        reply_markup=kb,
    )


@router.callback_query(F.data == "shield:menu")
async def cb_shield_menu(cb: CallbackQuery) -> None:
    u = await me_cb(cb)
    if u["shield_until"] > time.time():
        hours = int((u["shield_until"] - time.time()) // 3600)
        await cb.message.edit_text(
            f"🕊 سپر تو فعاله و تا {game.fa(hours)} ساعت دیگه ادامه داره!")
        await cb.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🕊 سپر ۶ ساعته — {game.fa(game.SHIELD_COSTS[6])}💰",
                              callback_data="shield:6")],
        [InlineKeyboardButton(text=f"🕊 سپر ۲۴ ساعته — {game.fa(game.SHIELD_COSTS[24])}💰",
                              callback_data="shield:24")],
    ])
    await cb.message.edit_text(
        f"🕊 <b>سپر محافظتی</b>\n"
        f"تا وقتی سپر داری هیچ‌کس نمی‌تونه به تو حمله کنه!\n"
        f"💰 موجودی: {admin_core.coins_display(u)} سکه",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("shield:"))
async def cb_shield(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    if len(parts) != 2 or not parts[1].isdigit():
        return  # منوی دکمه‌ای «shield:menu» توسط هندلر دقیق پاسخ داده می‌شود
    hours = int(parts[1])
    u = await me_cb(cb)
    cost = game.SHIELD_COSTS[hours]
    # مدیر: سپر رایگان؛ دیگران: کسر عادی
    if not await admin_core.pay(u, cost):
        await cb.answer("سکه کافی نداری! 🪙", show_alert=True)
        return
    await _db.update_user(u["user_id"],
                          shield_until=int(time.time()) + hours * 3600)
    await cb.answer(f"✅ سپر {game.fa(hours)} ساعته فعال شد! 🕊")
    u = await me_cb(cb)
    await cb.message.edit_text(
        f"🕊 سپر {game.fa(hours)} ساعته فعال شد!\n"
        f"💰 موجودی: {admin_core.coins_display(u)} سکه"
    )


# ================================================================ جایزه روزانه
async def cmd_daily(message: Message) -> None:  # (hidden)
    u = await me(message)
    now = int(time.time())
    if now - u["last_daily"] < 86400:
        remaining = 86400 - (now - u["last_daily"])
        hours, minutes = divmod(remaining // 60, 60)
        await message.answer(
            f"⏳ جایزهٔ بعدی تا {game.fa(hours)} ساعت و {game.fa(minutes)} دقیقهٔ دیگه!"
        )
        return
    reward = game.daily_reward(u["level"])
    await _db.update_user(u["user_id"], coins=coin(u) + reward, last_daily=now)
    await message.answer(
        f"🎁 <b>جایزهٔ روزانه!</b>\n"
        f"💰 {game.fa(reward)} سکه به حسابت اضافه شد.\n"
        f"💡 با +{game.fa(u['level'] * 40)} سکهٔ بیشتر هر سطح بالاتر می‌ری!"
    )


# ================================================================ رده‌بندی
async def cmd_top(message: Message) -> None:  # (hidden)
    await me(message)
    entries = await _db.top_power(10)
    text = top_text(entries, "power")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ قدرتمندترین", callback_data="top:power"),
         InlineKeyboardButton(text="💰 ثروتمندترین", callback_data="top:coins")],
    ])
    await message.answer(text, reply_markup=kb)


def top_text(entries: list, mode: str) -> str:
    medals = ["🥇", "🥈", "🥉"] + ["🔸"] * 7
    title = "⚔️ قدرتمندترین فرماندهان" if mode == "power" else "💰 ثروتمندترین فرماندهان"
    lines = [f"🏆 <b>جدول رده‌بندی — {title}</b>", "────────────────"]
    for i, e in enumerate(entries):
        if mode == "power":
            u, val = e["user"], e["power"]
            lines.append(f"{medals[i]} {esc(name_of(u))} — قدرت: {game.fa(val)}")
        else:
            u = e
            lines.append(f"{medals[i]} {esc(name_of(u))} — {game.fa(coin(u))}💰")
    if not entries:
        lines.append("هنوز بازیکنی ثبت نشده! تو اولین نفر باش 😎")
    lines.append("────────────────")
    lines.append("🎲 برای نبرد تصادفی: /attack یا از منوی «⚔️ نبرد» استفاده کن")
    return "\n".join(lines)


@router.callback_query(F.data.startswith("top:"))
async def cb_top(cb: CallbackQuery) -> None:
    mode = cb.data.split(":")[1]
    if mode == "coins":
        entries = await _db.top_coins(10)
    else:
        entries = await _db.top_power(10)
    await cb.message.edit_text(top_text(entries, mode))
    await cb.answer()


# ================================================================ تاریخچه
async def cmd_log(message: Message) -> None:  # (hidden)
    u = await me(message)
    rows = await _db.battle_history(u["user_id"], 10)
    if not rows:
        await message.answer("📜 هنوز نبردی انجام ندادی! با /war شروع کن ⚔️")
        return
    lines = ["📜 <b>تاریخچهٔ آخرین نبردها</b>", "────────────────"]
    for r in rows:
        when = time.strftime("%m/%d %H:%M", time.localtime(r["ts"]))
        if r["attacker_id"] == u["user_id"]:
            lines.append(f"{when} — {r['att_summary']}")
        else:
            lines.append(f"{when} — {r['def_summary']}")
    await message.answer("\n".join(lines))


# ================================================================ هدیه
@router.message(Command("gift"))
async def cmd_gift(message: Message, command: CommandObject) -> None:
    u = await me(message)
    parts = (command.args or "").split()

    target = None
    amount = None
    if message.reply_to_message and parts:
        target = message.reply_to_message.from_user
        amount = parts[0]
    elif len(parts) >= 2 and parts[0].lstrip("@").replace("-", "").isdigit():
        target_id = int(parts[0].lstrip("@"))
        target = await _db.get_user(target_id)
        amount = parts[1]
    elif len(parts) >= 2:
        target = await _db.find_by_username(parts[0])
        amount = parts[1]

    if target is None:
        await message.answer(
            "🎁 روش استفاده: به پیام کسی ریپلای کن و بنویس <code>/gift 500</code>\n"
            "یا: <code>/gift @username 500</code>"
        )
        return
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        await message.answer("❌ مبلغ هدیه باید عدد باشه!")
        return

    if amount < 100:
        await message.answer("❌ حداقل هدیه ۱۰۰ سکه است.")
        return
    if amount > coin(u):
        await message.answer("❌ به اندازهٔ کافی سکه نداری!")
        return
    if target["user_id"] == u["user_id"]:
        await message.answer("😅 نمی‌تونی به خودت هدیه بدی!")
        return

    tax = round(amount * 0.05)
    received = amount - tax
    await _db.update_user(u["user_id"], coins=coin(u) - amount)
    await _db.update_user(target["user_id"],
                          coins=target["coins"] + received)
    await message.answer(
        f"🎁 <b>هدیه ارسال شد!</b>\n"
        f"👤 به: {esc(name_of(target))}\n"
        f"💰 مبلغ: {game.fa(received)} سکه (مالیات {game.fa(tax)})"
    )
    try:
        await message.bot.send_message(
            target["user_id"],
            f"🎁 {esc(name_of(u))} به تو {game.fa(received)} سکه هدیه داد! 🥳",
        )
    except Exception:
        pass


# ================================================================ حمله
@router.message(Command("attack"))
async def cmd_attack(message: Message, command: CommandObject) -> None:
    """تنها حمله تصادفی — حمله با نام کاربری/آیدی حذف شد."""
    await me(message)
    target_user = await _db.random_opponent(message.from_user.id)
    if target_user is None:
        await message.answer("🌙 هنوز حریف مناسبی پیدا نشد! کمی بعد دوباره امتحان کن ⚔️")
        return
    await run_attack(message, int(target_user["user_id"]), target_user)


async def cmd_war(message: Message) -> None:  # (hidden)
    await me(message)
    target = await _db.random_opponent(message.from_user.id)
    if target is None:
        await message.answer("🌙 هنوز بازیکن دیگه‌ای نیست! دوستات رو دعوت کن ⚔️")
        return
    await run_attack(message, int(target["user_id"]), target)


async def run_attack(message: Message, target_id: int, target: dict) -> None:
    u = await me(message)

    # --- بررسی‌ها
    if target_id == u["user_id"]:
        await message.answer("😅 نمی‌تونی به خودت حمله کنی!")
        return

    defender = await _db.ensure_user(target_id, target.get("username", ""),
                                     target.get("first_name", ""))

    # --- بررسی انرژی (مدیر: نامحدود؛ فقط بررسی، مصرف بعد از عبور از همهٔ بررسی‌ها)
    energy, _ = game.effective_energy(u)
    if not admin_core.can_pay_energy(u, game.ATTACK_ENERGY_COST):
        wait_min = (game.ATTACK_ENERGY_COST - energy) * game.ENERGY_REGEN_SECONDS // 60
        await message.answer(
            f"⚡ انرژی کافی نداری! ({game.fa(energy)}/{game.fa(game.MAX_ENERGY)})\n"
            f"⏳ حدود {game.fa(max(1, wait_min))} دقیقه دیگه بیا."
        )
        return

    if defender["shield_until"] > time.time():
        hours = int((defender["shield_until"] - time.time()) // 3600)
        await message.answer(
            f"🕊 {esc(name_of(defender))} الان سپر داره و نمی‌تونی حمله‌اش کنی!\n"
            f"(حدود {game.fa(hours)} ساعت دیگه دوباره امتحان کن)"
        )
        return

    # --- کول‌داون ۹۰ ثانیه‌ای (مدیر و تست‌کننده: بدون کول‌داون)
    now = time.time()
    if not admin_core.no_cooldown(u["user_id"]):
        last = _cooldowns.get((u["user_id"], target_id), 0)
        if now - last < 90:
            wait = int(90 - (now - last))
            await message.answer(f"⏳ برای حملهٔ دوباره به همین حریف {game.fa(wait)} ثانیه صبر کن!")
            return
    _cooldowns[(u["user_id"], target_id)] = now

    att_army = await _db.get_army(u["user_id"])
    if game.attack_power(att_army) <= 0:
        await message.answer("🪖 اول یگان بخر! با /train ارتش بساز.")
        return

    def_army = await _db.get_army(target_id)
    def_struct = {k: v for k, v in def_army.items() if k in game.DEFENSES}

    # --- بافت‌ها و آیتم‌های فعال
    buffs = await _db.buffs_active(u["user_id"])
    inv = await _db.inv_get(u["user_id"])
    att_mult, loot_mult, xp_mult, cas_mult = 1.0, 1.0, 1.0, 1.0
    buff_names = []
    if "lucky" in buffs:
        att_mult *= game.BUFF_MULT["lucky"][1]
        buff_names.append(game.ITEMS["lucky"]["emoji"])
    if "magnet" in buffs:
        loot_mult *= game.BUFF_MULT["magnet"][1]
        buff_names.append(game.ITEMS["magnet"]["emoji"])
    if "xp_boost" in buffs:
        xp_mult *= game.BUFF_MULT["xp_boost"][1]
        buff_names.append(game.ITEMS["xp_boost"]["emoji"])
    repair_used = False
    if inv.get("repair", 0) > 0:
        cas_mult = 0.5
        repair_used = True
        await _db.inv_take(u["user_id"], "repair")

    # --- مصرف انرژی (بعد از رد شدن از همهٔ بررسی‌ها؛ مدیر: بدون کسر)
    if not await admin_core.try_spend_energy(u, game.ATTACK_ENERGY_COST):
        return  # عملاً غیرممکن است (بالا بررسی شده)؛ فقط برای ایمنی

    # --- نبرد
    res = game.simulate_battle(att_army, def_army, def_struct,
                               coin(u), coin(defender),
                               att_mult=att_mult, loot_mult=loot_mult,
                               xp_mult=xp_mult, cas_mult=cas_mult)

    # --- اعمال تلفات
    for unit_key, loss in res["att_cas"].items():
        await _db.set_unit(u["user_id"], unit_key, att_army.get(unit_key, 0) - loss)
    for unit_key, loss in res["def_cas"].items():
        await _db.set_unit(target_id, unit_key, def_army.get(unit_key, 0) - loss)

    # --- اعمال سکه، تجربه و آمار
    # (انرژی قبلاً در try_spend_energy مصرف شد؛ مدیرها اصلاً انرژی کم نمی‌شود)
    att_won = res["winner"] == "attacker"
    xp_gained = res["att_xp"] if att_won else res["def_xp"]
    # تست‌کننده‌ها تجربهٔ ×۲ می‌گیرند (پیشرفت سریع‌تر)
    xp_gained = round(xp_gained * admin_core.xp_multiplier(u["user_id"]))
    new_xp, new_level, levels, level_reward = game.add_xp(
        u["xp"], u["level"], xp_gained)

    if att_won:
        await _db.update_user(
            u["user_id"], coins=coin(u) + res["loot"],
            xp=new_xp, level=new_level,
            wins=u["wins"] + 1)
        await _db.update_user(
            target_id, coins=defender["coins"] - res["loot"],
            def_losses=defender["def_losses"] + 1)
    else:
        await _db.update_user(
            u["user_id"], coins=coin(u) - res["loot"],
            xp=new_xp, level=new_level,
            losses=u["losses"] + 1)
        await _db.update_user(
            target_id, coins=defender["coins"] + res["loot"],
            def_wins=defender["def_wins"] + 1)

    # --- لاگ نبرد
    att_name = esc(name_of(u))
    def_name = esc(name_of(defender))
    att_summary = (f"⚔️ پیروزی مقابل {def_name} — غنیمت {game.fa(res['loot'])}💰"
                   if att_won else f"❌ شکست مقابل {def_name}")
    def_summary = (f"🛡 دفع حملهٔ {att_name} — غنیمت {game.fa(res['loot'])}💰"
                   if not att_won else f"⚠️ باخت در برابر {att_name}")
    await _db.log_battle(int(time.time()), u["user_id"], target_id,
                         u["user_id"] if att_won else target_id,
                         res["loot"], res["att_power"], res["def_power"],
                         att_summary, def_summary)

    # --- هوک‌ها: مأموریت‌ها، جنگ اتحادیه، رشد
    await hooks.after_battle(u["user_id"], att_won)
    war_att, war_def = await hooks.process_war(
        u["user_id"], target_id, att_won, res["att_power"], res["loot"])
    await hooks.snapshot_growth(u["user_id"], res["att_power"])

    # --- گزارش برای مهاجم
    verdict = "🏆 <b>پیروزی در نبرد!</b>" if att_won else "💀 <b>شکست در نبرد!</b>"
    xp_gain = xp_gained  # با ضریب تست‌کننده‌ها
    report = (
        f"{verdict}\n"
        f"🔻 حریف: {def_name}\n"
        f"────────────────\n"
        f"⚔️ قدرت حملهٔ تو: <b>{game.fa(res['att_power'])}</b>\n"
        f"🛡 قدرت دفاع حریف: <b>{game.fa(res['def_power'])}</b>\n"
        f"💥 تلفات تو: {game.cas_text(res['att_cas'])}\n"
        f"💥 تلفات حریف: {game.cas_text(res['def_cas'])}\n"
        f"────────────────\n"
    )
    if buff_names:
        report += f"✨ بافت فعال: {' '.join(buff_names)}\n"
    if repair_used:
        report += "🛠 کیت تعمیر مصرف شد (تلفات نصف شد)\n"
    if att_won:
        report += f"💰 غنیمت: <b>{game.fa(res['loot'])}</b> سکه\n"
    else:
        report += f"💸 سکهٔ از دست رفته: <b>{game.fa(res['loot'])}</b>\n"
    report += f"⭐ تجربه: +{game.fa(xp_gain)}"
    if levels:
        report += f"\n🎉 <b>ارتقا سطح!</b> سطح {game.fa(new_level)} + {game.fa(level_reward)}💰 جایزه"
    if war_att:
        report += f"\n{war_att}"

    await message.answer(report)

    # --- اعلان به مدافع
    def_badge = "🎉 <b>حمله دفع شد!</b>" if not att_won else "⚠️ <b>پایگاهت مورد حمله قرار گرفت!</b>"
    def_report = (
        f"{def_badge}\n"
        f"🔻 مهاجم: {att_name}\n"
        f"────────────────\n"
        f"⚔️ قدرت مهاجم: <b>{game.fa(res['att_power'])}</b>\n"
        f"🛡 قدرت دفاع تو: <b>{game.fa(res['def_power'])}</b>\n"
        f"💥 تلفات تو: {game.cas_text(res['def_cas'])}\n"
    )
    if not att_won:
        def_report += f"💰 غنیمت تو: <b>{game.fa(res['loot'])}</b> سکه\n⭐ تجربه: +{game.fa(res['def_xp'])}"
    else:
        def_report += f"💸 سکهٔ از دست رفته: <b>{game.fa(res['loot'])}</b>\n"
        def_report += "💡 با /shield از خودت محافظت کن!"
    if war_def:
        def_report += f"\n{war_def}"
    try:
        await message.bot.send_message(target_id, def_report)
    except Exception:
        pass


# ================================================================ نمودار رشد
async def cmd_growth(message: Message) -> None:  # (hidden)
    u = await me(message)
    rows = await hooks_growth_rows(u["user_id"])
    from . import charts
    png = charts.growth_chart_png(
        rows,
        f"📈 رشد قدرت {esc(name_of(u))} — سطح {game.fa(u['level'])}",
    )
    if png is None:
        await message.answer(
            "📈 برای دیدن نمودار رشدت باید حداقل ۲ نبرد انجام بدهی! "
            "با /war یا /attack شروع کن. ⚔️"
        )
        return
    from aiogram.types import BufferedInputFile
    await message.answer_photo(
        BufferedInputFile(png, filename="growth.png"),
        caption=(
            f"📈 <b>نمودار رشد قدرت</b>\n"
            f"🎖 {esc(name_of(u))} — سطح {game.fa(u['level'])}\n"
            f"⚔️ قدرت فعلی: <b>{game.fa(rows[-1]['power'])}</b>"
        ),
    )


async def hooks_growth_rows(user_id: int) -> list[dict]:
    return await _db.growth_history(user_id, 30)
