"""منوی پایین ربات — صفحه‌کلید سفارشی شیشه‌ای در انتهای چت تلگرام.

ساختار جدید بر اساس قانون:
- 5 دسته اصلی در ReplyKeyboard پایین چت (همیشه قابل مشاهده)
- تمام زیرمنوها InlineKeyboard با دکمه ⬅️ بازگشت و 🏠 منوی اصلی
- همه قابلیت‌های عادی بازی داخل منو، فقط دستورات خاص (/gift, /attack, /admin, /myid, /start, /menu, /hidemenu) به صورت دستوری باقی می‌مانند
- منطق بازی دست‌نخورده، فقط UI بازطراحی شده
"""
from __future__ import annotations

import html
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup, ReplyKeyboardRemove)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import admin_core, admins, game
from .db import DB

router = Router(name="menu")

_db: DB | None = None

# ── برچسب دکمه‌های منوی اصلی (ReplyKeyboard پایین چت) ─────────────────
BTN_BASE = "🏠 پایگاه"
BTN_ARMY = "🪖 ارتش"
BTN_DEFENSE = "🛡 دفاع"
BTN_BATTLE = "⚔️ نبرد"
BTN_CLAN = "🏰 اتحادیه"

MENU_BUTTONS = (BTN_BASE, BTN_ARMY, BTN_DEFENSE, BTN_BATTLE, BTN_CLAN)

# ── Callback های ناوبری ────────────────────────────────────────────────
NAV_BASE = "nav:base"
NAV_ARMY = "nav:army"
NAV_DEFENSE = "nav:defense"
NAV_BATTLE = "nav:battle"
NAV_CLAN = "nav:clan"
NAV_MAIN = "nav:main"

def setup(db: DB) -> None:
    global _db
    _db = db

def main_menu_kb() -> ReplyKeyboardMarkup:
    """صفحه‌کلید اصلی پایین چت — بدون فروشگاه و قلمرو"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_BASE),
             KeyboardButton(text=BTN_ARMY),
             KeyboardButton(text=BTN_DEFENSE)],
            [KeyboardButton(text=BTN_BATTLE),
             KeyboardButton(text=BTN_CLAN)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="از منوی نبردگاه انتخاب کنید…",
    )

def nav_row(back_cb: str) -> list:
    """ردیف ناوبری مشترک: بازگشت + منوی اصلی"""
    return [
        InlineKeyboardButton(text="⬅️ بازگشت", callback_data=back_cb),
        InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NAV_MAIN),
    ]

def with_nav(kb: InlineKeyboardMarkup, back_cb: str) -> InlineKeyboardMarkup:
    """افزودن ردیف ناوبری به یک کیبورد موجود"""
    kb.inline_keyboard.append(nav_row(back_cb))
    return kb

# ════════════════════════════════════════════════════════════════════
#  دستورات مجاز (فقط این‌ها به صورت دستوری باقی می‌مانند)
# ════════════════════════════════════════════════════════════════════
@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    u = message.from_user
    await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    await message.answer(
        "🎮 <b>منوی نبردگاه فعال شد!</b>\n"
        "حالا فقط با دکمه‌های پایین چت بازی کن ⬇️\n"
        "────────────\n"
        "🏠 پایگاه — پروفایل، جایزه، مأموریت، معدن، نمودار، رده‌بندی\n"
        "🪖 ارتش — آموزش یگان، ارتقا، موجودی\n"
        "🛡 دفاع — خرید و ارتقای سازه‌ها، سپر\n"
        "⚔️ نبرد — نبرد تصادفی، حمله، تاریخچه\n"
        "🏰 اتحادیه — قبیله، جنگ\n"
        "────────────\n"
        "برای مخفی‌کردن منو: /hidemenu",
        reply_markup=main_menu_kb(),
    )

@router.message(Command("hidemenu"))
async def cmd_hidemenu(message: Message) -> None:
    await message.answer("🚫 منو مخفی شد. برای نمایش دوباره: /menu",
                         reply_markup=ReplyKeyboardRemove())

# ════════════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════════════
def _name_of(u: dict) -> str:
    return u.get("first_name") or u.get("username") or "بازیکن ناشناس"

async def _base_overview_text(user: dict) -> str:
    from .handlers import energy_line
    army = await _db.get_army(user["user_id"])
    defenses = await _db.get_defenses(user["user_id"])
    units = {k: v for k, v in army.items() if k in game.UNITS}
    power = game.attack_power(army)
    defense = game.defense_power(units, defenses, base_level=user["level"])
    next_xp = game.xp_to_next(user["level"])
    bar_len = 12
    filled = round(user["xp"] / next_xp * bar_len)
    bar = "🟩" * filled + "⬜" * (bar_len - filled)
    extra = ""
    if user.get("clan_id"):
        clan = await _db.get_clan(user["clan_id"])
        if clan:
            extra += f" | 🏰 {html.escape(clan['name'])}"
    if user["shield_until"] > time.time():
        hours = int((user["shield_until"] - time.time()) // 3600)
        extra += f" | 🕊 سپر ({game.fa(hours)}س)"
    role_badge = " 👑" if admin_core.is_dev(user["user_id"]) else (" 🧪" if admin_core.is_tester(user["user_id"]) else "")
    return (
        f"🏠 <b>پایگاه {_name_of(user)}</b>{role_badge}\n"
        f"────────────────\n"
        f"🏅 درجه: {game.rank_name(user['level'])} (سطح {game.fa(user['level'])})\n"
        f"{bar}\n"
        f"💰 سکه: {admin_core.coins_display(user)} | ⚡ انرژی: {admin_core.energy_display(user)}\n"
        f"⚔️ قدرت: <b>{game.fa(power)}</b> | 🛡 دفاع: <b>{game.fa(defense)}</b>\n"
        f"🏆 برد: {game.fa(user['wins'])} | باخت: {game.fa(user['losses'])}"
        f"{extra}\n"
        f"────────────────\n"
        f"از منوی زیر پایگاهت را مدیریت کن:"
    )

# ════════════════════════════════════════════════════════════════════
#  🏠 پایگاه — منو و زیرمنوها
# ════════════════════════════════════════════════════════════════════
def base_menu_kb(user: dict | None = None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👤 پروفایل", callback_data="base:profile")
    b.button(text="🎁 جایزه روزانه", callback_data="base:daily")
    b.button(text="🎯 مأموریت‌ها", callback_data="base:missions")
    b.button(text="⛏ معدن", callback_data="base:mine")
    b.button(text="📈 نمودار رشد", callback_data="base:growth")
    b.button(text="🏆 رده‌بندی", callback_data="base:top")
    b.button(text="📜 تاریخچه نبردها", callback_data="base:log")
    b.button(text="🛡️ سپر محافظتی", callback_data="base:shield")
    if user and admins.is_developer(user["user_id"]):
        b.button(text="👑 پنل مدیریت", callback_data="admin:panel")
    b.button(text="⬅️ بازگشت", callback_data="nav:main")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(2)
    return b.as_markup()

@router.message(F.text == BTN_BASE)
async def on_base(message: Message) -> None:
    u = message.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    text = await _base_overview_text(user)
    await message.answer(text, reply_markup=base_menu_kb(user))

@router.callback_query(F.data == NAV_BASE)
async def cb_nav_base(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    text = await _base_overview_text(u)
    await cb.message.edit_text(text, reply_markup=base_menu_kb(u))
    await cb.answer()

# --- Base sub handlers ---
@router.callback_query(F.data == "base:profile")
async def cb_base_profile(cb: CallbackQuery) -> None:
    from .handlers import esc, name_of, coin, energy_line
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    army = await _db.get_army(u["user_id"])
    defenses = await _db.get_defenses(u["user_id"])
    units_only = {k: v for k, v in army.items() if k in game.UNITS}
    energy, _ = game.effective_energy(u)
    power = game.attack_power(army)
    defense = game.defense_power(units_only, defenses, base_level=u["level"])
    total_units = sum(units_only.values())
    total_structs = sum(s.get("level", 0) for s in defenses.values())
    next_xp = game.xp_to_next(u["level"])
    bar_len = 14
    filled = round(u["xp"] / next_xp * bar_len) if next_xp else bar_len
    bar = "🟩" * filled + "⬜" * (bar_len - filled)
    pct = round(u["xp"] / next_xp * 100) if next_xp else 100

    # Clan info
    clan_line = "🏰 اتحادیه: — (بدون اتحادیه)"
    if u.get("clan_id"):
        clan = await _db.get_clan(u["clan_id"])
        if clan:
            lvl = await _db.clan_level(clan["id"])
            clan_line = f"🏰 اتحادیه: <b>{html.escape(clan['name'])}</b> (سطح {game.fa(lvl)}) — 💰 خزانه: {game.fa(clan['treasury'])} سکه"
            if clan.get("group_id"):
                clan_line += f" \n📍 گروه: {html.escape(clan.get('group_title') or str(clan['group_id']))}"

    # Shield
    shield_line = "🕊 سپر: غیرفعال ⚪"
    if u["shield_until"] > time.time():
        hours = int((u["shield_until"] - time.time()) // 3600)
        mins = int((u["shield_until"] - time.time()) % 3600 // 60)
        shield_line = f"🕊 سپر: فعال 🟢 — {game.fa(hours)}س {game.fa(mins)}د دیگر"

    # Achievements
    achievements = []
    if u["wins"] >= 1:
        achievements.append("🏆 اولین پیروزی")
    if u["wins"] >= 10:
        achievements.append("⚔️ جنگجوی کهنه‌کار (۱۰ برد)")
    if u["level"] >= 10:
        achievements.append("🎖 کهنه‌سرباز (سطح ۱۰)")
    if u["level"] >= 20:
        achievements.append("👑 فرمانده ارشد (سطح ۲۰)")
    if total_units >= 100:
        achievements.append("🪖 ارتش بزرگ (۱۰۰ یگان)")
    if power >= 5000:
        achievements.append("💥 قدرت مهیب (۵۰۰۰+)")
    if u.get("clan_id"):
        achievements.append("🏰 عضو اتحادیه")
    ach_line = "✨ دستاوردها: " + ("، ".join(achievements) if achievements else "در حال پیشرفت...")

    # Rank badge
    rank = game.rank_name(u["level"])
    rank_emoji = {"ژنرال": "🎖", "سرهنگ": "🎖", "سرگرد": "🎖", "سروان": "⭐", "ستوان": "⭐", "گروهبان": "🔰", "سرباز": "🪖"}.get(rank, "🎖")

    text = (
        f"╔════════════════════════╗\n"
        f"║  {rank_emoji} <b>پروفایل فرماندهی</b> {rank_emoji}  ║\n"
        f"╚════════════════════════╝\n"
        f"👤 <b>{esc(name_of(u))}</b>  •  🆔 <code>{u['user_id']}</code>\n"
        f"────────────────\n"
        f"{rank_emoji} درجه: <b>{rank}</b>  |  🎚 سطح: <b>{game.fa(u['level'])}</b>\n"
        f"⭐ تجربه: <b>{game.fa(u['xp'])}/{game.fa(next_xp)}</b> ({game.fa(pct)}٪)\n"
        f"{bar}\n"
        f"────────────────\n"
        f"💰 سکه: <b>{game.fa(coin(u))}</b>  |  {energy_line(u)}\n"
        f"⚔️ قدرت حمله: <b>{game.fa(power)}</b>  |  🛡 قدرت دفاع: <b>{game.fa(defense)}</b>\n"
        f"🪖 اندازه ارتش: <b>{game.fa(total_units)}</b> یگان  |  🏰 سازه دفاعی: <b>{game.fa(total_structs)}</b>\n"
        f"{clan_line}\n"
        f"{shield_line}\n"
        f"────────────────\n"
        f"📊 <b>آمار نبرد</b>\n"
        f"🏆 پیروزی: {game.fa(u['wins'])}  |  💀 شکست: {game.fa(u['losses'])}  |  ⚔️ نسبت: {game.fa(round(u['wins']/max(1,u['wins']+u['losses'])*100))}٪\n"
        f"🛡 دفع موفق: {game.fa(u['def_wins'])}  |  🔥 باخت دفاع: {game.fa(u['def_losses'])}\n"
        f"────────────────\n"
        f"{ach_line}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="📈 نمودار رشد", callback_data="base:growth")
    b.button(text="🏆 رده‌بندی", callback_data="base:top")
    b.button(text="🛡️ سپر", callback_data="base:shield")
    b.button(text="🎯 مأموریت‌ها", callback_data="base:missions")
    b.button(text="⬅️ بازگشت", callback_data=NAV_BASE)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2,2,2)
    await cb.message.edit_text(text, reply_markup=b.as_markup())
    await cb.answer()

@router.callback_query(F.data == "base:daily")
async def cb_base_daily(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    now = int(time.time())
    if now - u["last_daily"] < 86400:
        remaining = 86400 - (now - u["last_daily"])
        hours, minutes = divmod(remaining // 60, 60)
        b = InlineKeyboardBuilder()
        b.button(text="⬅️ بازگشت", callback_data=NAV_BASE)
        b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
        b.adjust(2)
        await cb.message.edit_text(f"⏳ جایزهٔ بعدی تا {game.fa(hours)} ساعت و {game.fa(minutes)} دقیقهٔ دیگه!", reply_markup=b.as_markup())
        await cb.answer()
        return
    reward = game.daily_reward(u["level"])
    await _db.update_user(u["user_id"], coins=u["coins"] + reward, last_daily=now)
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ بازگشت", callback_data=NAV_BASE)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2)
    await cb.message.edit_text(f"🎁 <b>جایزهٔ روزانه!</b>\n💰 {game.fa(reward)} سکه به حسابت اضافه شد.\n💡 با +{game.fa(u['level'] * 40)} سکهٔ بیشتر هر سطح بالاتر می‌ری!", reply_markup=b.as_markup())
    await cb.answer()

@router.callback_query(F.data == "base:shield")
async def cb_base_shield(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    if u["shield_until"] > time.time():
        hours = int((u["shield_until"] - time.time()) // 3600)
        b = InlineKeyboardBuilder()
        b.button(text="⬅️ بازگشت", callback_data=NAV_BASE)
        b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
        b.adjust(2)
        await cb.message.edit_text(f"🕊 سپر تو فعاله و تا {game.fa(hours)} ساعت دیگه ادامه داره!", reply_markup=b.as_markup())
        await cb.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🕊 سپر ۶ ساعته — {game.fa(game.SHIELD_COSTS[6])}💰", callback_data="shield:6")],
        [InlineKeyboardButton(text=f"🕊 سپر ۲۴ ساعته — {game.fa(game.SHIELD_COSTS[24])}💰", callback_data="shield:24")],
        nav_row(NAV_BASE),
    ])
    await cb.message.edit_text(f"🕊 <b>سپر محافظتی</b>\nتا وقتی سپر داری هیچ‌کس نمی‌تونه به تو حمله کنه!\n💰 موجودی: {admin_core.coins_display(u)} سکه", reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "base:missions")
async def cb_base_missions(cb: CallbackQuery) -> None:
    from .handlers_missions import render_missions
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    text, kb = await render_missions(u["user_id"])
    # missions_kb already has nav (Back to Base + Main), no need to add again
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "base:mine")
async def cb_base_mine(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    from .handlers_missions import mine_status_text, mine_kb
    state = await _db.mine_get(u["user_id"])
    if state is None:
        army = await _db.get_army(u["user_id"])
        workers = min(game.MINE_WORKER_CAP, army.get("soldier", 0))
        if workers <= 0:
            b = InlineKeyboardBuilder()
            b.button(text="🪖 آموزش سرباز", callback_data=NAV_ARMY)
            b.button(text="⬅️ بازگشت", callback_data=NAV_BASE)
            b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
            b.adjust(1,2)
            await cb.message.edit_text("⛏ اول با «🪖 ارتش → آموزش یگان» سرباز بخر تا معدنچی داشته باشی!", reply_markup=b.as_markup())
            await cb.answer()
            return
        await _db.mine_start(u["user_id"], int(time.time()), workers)
        b = InlineKeyboardBuilder()
        b.button(text="⬅️ بازگشت", callback_data=NAV_BASE)
        b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
        b.adjust(2)
        await cb.message.edit_text(f"⛏ <b>استخراج آغاز شد!</b>\n🪖 {game.fa(workers)} سرباز به معدن رفتند.\n💰 نرخ: هر سرباز {game.fa(game.MINE_RATE)} سکه در ساعت (تا سقف {game.fa(game.MINE_MAX_HOURS)} ساعت)\n📊 دوباره از همین منو وضعیت را ببین.", reply_markup=b.as_markup())
        await cb.answer()
        return
    gain = game.mine_gain(state["workers"], int(time.time()) - state["start_ts"])
    from .handlers_missions import mine_status_text, mine_kb
    kb = mine_kb()
    await cb.message.edit_text(mine_status_text(state, gain), reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "base:growth")
async def cb_base_growth(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    from . import charts
    from .handlers import name_of
    rows = await _db.growth_history(u["user_id"], 30)
    png = charts.growth_chart_png(rows, f"رشد قدرت {name_of(u)} — سطح {game.fa(u['level'])}")
    if png is None:
        b = InlineKeyboardBuilder()
        b.button(text="⚔️ نبرد تصادفی", callback_data="battle:random")
        b.button(text="⬅️ بازگشت", callback_data=NAV_BASE)
        b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
        b.adjust(1,2)
        await cb.message.edit_text("📈 برای دیدن نمودار رشدت باید حداقل ۲ نبرد انجام بدهی! از «⚔️ نبرد» شروع کن.", reply_markup=b.as_markup())
        await cb.answer()
        return
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ بازگشت", callback_data=NAV_BASE)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2)
    # send as photo with nav in caption's keyboard? Instead edit with photo
    await cb.message.answer_photo(BufferedInputFile(png, filename="growth.png"), caption=f"📈 <b>نمودار رشد قدرت</b>\n🎖 {name_of(u)} — سطح {game.fa(u['level'])}", reply_markup=b.as_markup())
    await cb.answer()

@router.callback_query(F.data == "base:top")
async def cb_base_top(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    from .handlers import top_text
    entries = await _db.top_power(10)
    text = top_text(entries, "power")
    b = InlineKeyboardBuilder()
    b.button(text="⚔️ قدرتمندترین", callback_data="base:top:power")
    b.button(text="💰 ثروتمندترین", callback_data="base:top:coins")
    b.button(text="⬅️ بازگشت", callback_data=NAV_BASE)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2,2)
    await cb.message.edit_text(text, reply_markup=b.as_markup())
    await cb.answer()

@router.callback_query(F.data.startswith("base:top:"))
async def cb_base_top_sub(cb: CallbackQuery) -> None:
    mode = cb.data.split(":")[-1]
    from .handlers import top_text
    if mode == "coins":
        entries = await _db.top_coins(10)
    else:
        entries = await _db.top_power(10)
    b = InlineKeyboardBuilder()
    b.button(text="⚔️ قدرتمندترین", callback_data="base:top:power")
    b.button(text="💰 ثروتمندترین", callback_data="base:top:coins")
    b.button(text="⬅️ بازگشت", callback_data=NAV_BASE)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2,2)
    await cb.message.edit_text(top_text(entries, mode), reply_markup=b.as_markup())
    await cb.answer()

@router.callback_query(F.data == "base:log")
async def cb_base_log(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    rows = await _db.battle_history(u["user_id"], 10)
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ بازگشت", callback_data=NAV_BASE)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2)
    if not rows:
        await cb.message.edit_text("📜 هنوز نبردی انجام ندادی! از «⚔️ نبرد → نبرد تصادفی» شروع کن ⚔️", reply_markup=b.as_markup())
        await cb.answer()
        return
    import time as _time
    lines = ["📜 <b>تاریخچهٔ آخرین نبردها</b>", "────────────────"]
    for r in rows:
        when = _time.strftime("%m/%d %H:%M", _time.localtime(r["ts"]))
        if r["attacker_id"] == u["user_id"]:
            lines.append(f"{when} — {r['att_summary']}")
        else:
            lines.append(f"{when} — {r['def_summary']}")
    await cb.message.edit_text("\n".join(lines), reply_markup=b.as_markup())
    await cb.answer()

# ════════════════════════════════════════════════════════════════════
#  🪖 ارتش — به ماژول handlers_army.py منتقل شد (سیستم نوین ارتش)
#  دکمهٔ پایین چت «🪖 ارتش» و ناوبری nav:army در هندلرهای همان ماژول پاسخ داده می‌شوند
# ════════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════════
#  🛡 دفاع — به ماژول handlers_defense.py منتقل شد (سیستم نوین دفاع)
#  دکمهٔ پایین چت «🛡 دفاع» و ناوبری nav:defense در هندلرهای همان ماژول پاسخ داده می‌شوند
# ════════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════════
#  ⚔️ نبرد
# ════════════════════════════════════════════════════════════════════
def battle_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🎲 نبرد تصادفی", callback_data="battle:random")
    b.button(text="🎯 منوی حمله", callback_data="battle:attack")
    b.button(text="📜 تاریخچه نبردها", callback_data="battle:log")
    b.button(text="📊 اطلاعات نبرد", callback_data="battle:info")
    b.button(text="⬅️ بازگشت", callback_data=NAV_MAIN)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2,2,2)
    return b.as_markup()

def battle_menu_text(user: dict) -> str:
    from .handlers import energy_line
    return (
        f"⚔️ <b>مرکز نبرد</b>\n"
        f"{energy_line(user)} — هر حمله {game.fa(game.ATTACK_ENERGY_COST)}⚡\n"
        f"────────────────\n"
        f"🎯 <b>نبرد تصادفی</b> — تنها روش حمله در نبردگاه!\n"
        f"🎲 حریف به‌صورت خودکار و تصادفی از بین بازیکنان فعال انتخاب می‌شود.\n"
        f"🏰 اگر اتحادیه‌ات در جنگ باشد، هر پیروزی امتیاز جنگ می‌آورد.\n"
        f"────────────────\n"
        f"از منوی زیر انتخاب کن:"
    )

@router.message(F.text == BTN_BATTLE)
async def on_battle(message: Message) -> None:
    u = await _db.ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    await message.answer(battle_menu_text(u), reply_markup=battle_menu_kb())

@router.callback_query(F.data == NAV_BATTLE)
async def cb_nav_battle(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    await cb.message.edit_text(battle_menu_text(u), reply_markup=battle_menu_kb())
    await cb.answer()

@router.callback_query(F.data == "battle:random")
async def cb_battle_random(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    from .handlers import run_attack
    target = await _db.random_opponent(u["user_id"])
    if target is None:
        b = InlineKeyboardBuilder()
        b.button(text="⬅️ بازگشت", callback_data=NAV_BATTLE)
        b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
        b.adjust(2)
        await cb.message.edit_text("🌙 هنوز بازیکن دیگه‌ای نیست! دوستات رو دعوت کن ⚔️", reply_markup=b.as_markup())
        await cb.answer()
        return
    await cb.answer("⚔️ در حال یافتن حریف...")
    # run_attack will send new message, keep menu alive by editing with nav
    await run_attack(cb.message, int(target["user_id"]), target)

@router.callback_query(F.data == "battle:attack")
async def cb_battle_attack(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    from .handlers import energy_line
    b = InlineKeyboardBuilder()
    b.button(text="🎲 نبرد تصادفی", callback_data="battle:random")
    b.button(text="⬅️ بازگشت", callback_data=NAV_BATTLE)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(1,2)
    text = (
        f"🎯 <b>منوی نبرد تصادفی</b>\n"
        f"{energy_line(u)} — هر حمله {game.fa(game.ATTACK_ENERGY_COST)}⚡\n"
        f"────────────────\n"
        f"⚔️ <b>تنها روش حمله:</b> نبرد تصادفی\n"
        f"🎲 حریف به‌صورت کاملاً تصادفی از بین بازیکنان انتخاب می‌شود — عادلانه و هیجان‌انگیز!\n"
        f"• با «🎲 نبرد تصادفی» یا دستور <code>/attack</code> حمله کن\n"
        f"────────────────\n"
        f"💡 اگر اتحادیه‌ات در جنگ باشد، هر پیروزی امتیاز جنگ می‌آورد."
    )
    await cb.message.edit_text(text, reply_markup=b.as_markup())
    await cb.answer()

@router.callback_query(F.data == "battle:log")
async def cb_battle_log(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    rows = await _db.battle_history(u["user_id"], 10)
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ بازگشت", callback_data=NAV_BATTLE)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2)
    if not rows:
        await cb.message.edit_text("📜 هنوز نبردی انجام ندادی! از «🎲 نبرد تصادفی» شروع کن ⚔️", reply_markup=b.as_markup())
        await cb.answer()
        return
    import time as _time
    lines = ["📜 <b>تاریخچهٔ آخرین نبردها</b>", "────────────────"]
    for r in rows:
        when = _time.strftime("%m/%d %H:%M", _time.localtime(r["ts"]))
        if r["attacker_id"] == u["user_id"]:
            lines.append(f"{when} — {r['att_summary']}")
        else:
            lines.append(f"{when} — {r['def_summary']}")
    await cb.message.edit_text("\n".join(lines), reply_markup=b.as_markup())
    await cb.answer()

@router.callback_query(F.data == "battle:info")
async def cb_battle_info(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    army = await _db.get_army(u["user_id"])
    defenses = await _db.get_defenses(u["user_id"])
    power = game.attack_power(army)
    defense = game.defense_power({k: v for k, v in army.items() if k in game.UNITS}, defenses, base_level=u["level"])
    b = InlineKeyboardBuilder()
    b.button(text="🎲 نبرد تصادفی", callback_data="battle:random")
    b.button(text="📜 تاریخچه نبردها", callback_data="battle:log")
    b.button(text="⬅️ بازگشت", callback_data=NAV_BATTLE)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2,2)
    text = (
        f"📊 <b>اطلاعات نبرد</b>\n"
        f"────────────────\n"
        f"⚔️ قدرت حمله: <b>{game.fa(power)}</b>\n"
        f"🛡 قدرت دفاع: <b>{game.fa(defense)}</b>\n"
        f"🏆 پیروزی‌ها: {game.fa(u['wins'])} | شکست‌ها: {game.fa(u['losses'])}\n"
        f"🛡 دفع موفق: {game.fa(u['def_wins'])} | باخت دفاع: {game.fa(u['def_losses'])}\n"
        f"⚡ انرژی هر حمله: {game.fa(game.ATTACK_ENERGY_COST)}\n"
        f"💰 حداکثر غنیمت: {game.fa(game.MAX_LOOT)} سکه\n"
        f"────────────────\n"
        f"💡 قدرت حمله از مجموع یگان‌ها، و قدرت دفاع از ۷۰٪ یگان‌ها + سازه‌ها محاسبه می‌شود."
    )
    await cb.message.edit_text(text, reply_markup=b.as_markup())
    await cb.answer()

# ════════════════════════════════════════════════════════════════════
#  🏰 اتحادیه
# ════════════════════════════════════════════════════════════════════
def clan_menu_kb(is_member: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if is_member:
        b.button(text="🏰 اتحادیه من", callback_data="clan:my")
        b.button(text="💰 خزانه", callback_data="clan:treasury")
        b.button(text="⚔️ جنگ اتحادیه", callback_data="clan:war")
        b.button(text="📊 وضعیت جنگ", callback_data="clan:warstatus")
    else:
        b.button(text="🏰 ساخت اتحادیه", callback_data="clan:create_prompt")
        b.button(text="📋 پیوستن به اتحادیه", callback_data="clan:list")
    b.button(text="📋 لیست اتحادیه‌ها", callback_data="clan:list")
    b.button(text="⬅️ بازگشت", callback_data=NAV_MAIN)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2,2,2,2)
    return b.as_markup()

def clan_menu_text(is_member: bool) -> str:
    if is_member:
        return (
            f"🏰 <b>اتحادیه</b>\n"
            f"────────────────\n"
            f"اتحادیهٔ خود را مدیریت کن، به جنگ برو.\n"
            f"از منوی زیر انتخاب کن:"
        )
    return (
        f"🏰 <b>اتحادیه</b>\n"
        f"────────────────\n"
        f"هنوز عضو اتحادیه‌ای نیستی!\n"
        f"با اتحادیه می‌توانی خزانهٔ مشترک داشته باشی و جنگ ۲۴ ساعته راه بیندازی.\n"
        f"از منوی زیر انتخاب کن:"
    )

@router.message(F.text == BTN_CLAN)
async def on_clan(message: Message) -> None:
    u = await _db.ensure_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    is_member = bool(u.get("clan_id"))
    await message.answer(clan_menu_text(is_member), reply_markup=clan_menu_kb(is_member))

@router.callback_query(F.data == NAV_CLAN)
async def cb_nav_clan(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    is_member = bool(u.get("clan_id"))
    await cb.message.edit_text(clan_menu_text(is_member), reply_markup=clan_menu_kb(is_member))
    await cb.answer()

@router.callback_query(F.data == "clan:my")
async def cb_clan_my(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    if not u.get("clan_id"):
        await cb.message.edit_text(clan_menu_text(False), reply_markup=clan_menu_kb(False))
        await cb.answer()
        return
    from .handlers_clan import clan_panel_text, clan_panel_kb
    text = await clan_panel_text(u["clan_id"], u)
    kb = await clan_panel_kb(u["clan_id"], u)
    # add nav row
    kb.inline_keyboard.append(nav_row(NAV_CLAN))
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "clan:treasury")
async def cb_clan_treasury(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    if not u.get("clan_id"):
        await cb.answer("عضو اتحادیه‌ای نیستی!", show_alert=True)
        return
    clan = await _db.get_clan(u["clan_id"])
    b = InlineKeyboardBuilder()
    b.button(text="💰 واریز به خزانه", callback_data=f"clan:deposit:{clan['id']}")
    b.button(text="⬅️ بازگشت", callback_data=NAV_CLAN)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(1,2)
    await cb.message.edit_text(f"💰 <b>خزانهٔ اتحادیهٔ {html.escape(clan['name'])}</b>\n────────────────\n💰 موجودی خزانه: <b>{game.fa(clan['treasury'])}</b> سکه\n💰 موجودی شما: {admin_core.coins_display(u)} سکه\n────────────────\nبا «واریز به خزانه» به اتحادیه کمک کن.", reply_markup=b.as_markup())
    await cb.answer()

@router.callback_query(F.data == "clan:war")
async def cb_clan_war_menu(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    if not u.get("clan_id"):
        await cb.answer("عضو اتحادیه‌ای نیستی!", show_alert=True)
        return
    from .handlers_clan import clan_panel_kb
    # reuse war logic
    war = await _db.active_war_for_clan(u["clan_id"])
    b = InlineKeyboardBuilder()
    if war:
        b.button(text="📊 وضعیت جنگ", callback_data=f"clan:warstatus:{u['clan_id']}")
    else:
        b.button(text="⚔️ شروع جنگ اتحادیه", callback_data=f"clan:war:{u['clan_id']}")
    b.button(text="⬅️ بازگشت", callback_data=NAV_CLAN)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(1,2)
    clan = await _db.get_clan(u["clan_id"])
    if war:
        a = await _db.get_clan(war["clan_a"])
        b_clan = await _db.get_clan(war["clan_b"])
        text = f"⚔️ <b>جنگ اتحادیه</b>\n────────────────\n{a['name']} ({game.fa(war['points_a'])}) vs {b_clan['name']} ({game.fa(war['points_b'])})\n⏱ تا {game.fa((war['end_ts'] - time.time())//3600)} ساعت دیگر"
    else:
        text = f"⚔️ <b>جنگ اتحادیه</b>\n────────────────\nاتحادیهٔ «{html.escape(clan['name'])}» در حال جنگ نیست.\nبا «شروع جنگ» به اتحادیهٔ رقیب حمله کن! (هزینه از خزانه)"
    await cb.message.edit_text(text, reply_markup=b.as_markup())
    await cb.answer()

@router.callback_query(F.data == "clan:warstatus")
async def cb_clan_warstatus_menu(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    if not u.get("clan_id"):
        await cb.answer("عضو اتحادیه‌ای نیستی!", show_alert=True)
        return
    war = await _db.active_war_for_clan(u["clan_id"])
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ بازگشت", callback_data=NAV_CLAN)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2)
    if not war:
        await cb.message.edit_text("🏰 جنگ فعالی برای اتحادیه‌ات نیست.", reply_markup=b.as_markup())
        await cb.answer()
        return
    a = await _db.get_clan(war["clan_a"])
    b_clan = await _db.get_clan(war["clan_b"])
    left = war["end_ts"] - time.time()
    await cb.message.edit_text(f"🔥 <b>وضعیت جنگ</b>\n⚔️ {html.escape(a['name'])} ({game.fa(war['points_a'])}) در برابر {html.escape(b_clan['name'])} ({game.fa(war['points_b'])})\n⏱ باقی‌مانده: {game.fa(int(left // 3600))} ساعت و {game.fa(int((left % 3600)//60))} دقیقه", reply_markup=b.as_markup())
    await cb.answer()

@router.callback_query(F.data == "clan:create_prompt")
async def cb_clan_create_prompt(cb: CallbackQuery) -> None:
    u = await _db.ensure_user(cb.from_user.id, cb.from_user.username or "", cb.from_user.first_name or "")
    if u.get("clan_id"):
        await cb.answer("تو الان عضو اتحادیه‌ای!", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ بازگشت", callback_data=NAV_CLAN)
    b.button(text="🏠 منوی اصلی", callback_data=NAV_MAIN)
    b.adjust(2)
    await cb.message.edit_text("🏰 <b>ساخت اتحادیه</b>\nنام اتحادیه را بفرست (مثلاً):\n<code>/clan_create شیران</code>", reply_markup=b.as_markup())
    await cb.answer()

# ════════════════════════════════════════════════════════════════════
#  ناوبری عمومی
# ════════════════════════════════════════════════════════════════════
@router.callback_query(F.data == NAV_MAIN)
async def cb_nav_main(cb: CallbackQuery) -> None:
    await cb.message.delete()
    await cb.answer("🏠 به منوی اصلی برگشتی — از دکمه‌های پایین انتخاب کن")

@router.callback_query(F.data == "close")
async def cb_close(cb: CallbackQuery) -> None:
    await cb.message.delete()
    await cb.answer()

# ─────────────────────────────────────────────────────────────────
#  سازگاری با تست‌های قدیمی (base_text / base_kb / attack_kb)
# ─────────────────────────────────────────────────────────────────
async def base_text(user: dict) -> str:
    """پروکسی قدیمی: برای تست‌ها — همان _base_overview_text"""
    return await _base_overview_text(user)

def base_kb(user: dict | None = None) -> InlineKeyboardMarkup:
    """پروکسی قدیمی: base_kb برای تست ادمین — همان base_menu_kb"""
    return base_menu_kb(user)

def attack_kb() -> InlineKeyboardMarkup:
    """پروکسی قدیمی: attack_kb → battle_menu_kb"""
    return battle_menu_kb()

# Alias برای تست‌هایی که به on_attack ارجاع می‌دهند
on_attack = on_battle  # برای سازگاری نام قدیمی

