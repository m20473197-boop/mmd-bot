"""اتحادیه‌ها، جنگ بین اتحادیه‌ها و قلمروهای نقشه."""
from __future__ import annotations

import html
import time

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (CallbackQuery, InlineKeyboardMarkup, Message)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import game, hooks
from .db import DB

router = Router(name="clan")

_db: DB | None = None


def setup(db: DB) -> None:
    global _db
    _db = db


def esc(t: str) -> str:
    return html.escape(str(t))


def name_of(u: dict) -> str:
    return u.get("first_name") or u.get("username") or "بازیکن"


# ================================================================ /clan
@router.message(Command("clan"))
async def cmd_clan(message: Message) -> None:
    u = message.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    if not user.get("clan_id"):
        await message.answer(
            "🏰 <b>اتحادیه</b>\n"
            "هنوز عضو اتحادیه نیستی!\n"
            "• ساخت: <code>/clan_create نام</code>\n"
            "• پیوستن: <code>/clan_join نام</code>\n"
            "• لیست: <code>/clans</code>",
            reply_markup=_join_kb())
        return
    await message.answer(clan_panel_text(user["clan_id"], user),
                         reply_markup=await clan_panel_kb(user["clan_id"], user))


def _join_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📋 لیست اتحادیه‌ها", callback_data="clan:list")
    b.button(text="⬅️ بازگشت", callback_data="nav:clan")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(1,2)
    return b.as_markup()


async def clan_panel_text(clan_id: int, member: dict) -> str:
    clan = await _db.get_clan(clan_id)
    members = await _db.clan_members(clan_id)
    power = await _db.clan_power(clan_id)
    lvl = await _db.clan_level(clan_id)
    war = await _db.active_war_for_clan(clan_id)

    m = member
    role = next((x["role"] for x in members if x["user_id"] == m["user_id"]), "member")
    role_fa = {"leader": "👑 رهبر", "member": "🎖 عضو"}.get(role, role)

    lines = [
        f"🏰 <b>اتحادیهٔ {esc(clan['name'])}</b> (سطح {game.fa(lvl)})",
        f"{role_fa} — {esc(name_of(m))}",
        "────────────────",
        f"👥 اعضا: {game.fa(len(members))}  |  ⚔️ قدرت: {game.fa(power)}",
        f"💰 خزانه: {game.fa(clan['treasury'])} سکه",
        f"🏆 پیروزی‌های جنگ: {game.fa(clan['war_wins'])} | شکست‌ها: {game.fa(clan['war_losses'])}",
    ]
    if war:
        lines += ["────────────────",
                  f"⚔️ <b>جنگ فعال اتحادیه‌ای!</b> (تا {game.fa((war['end_ts'] - time.time()) // 3600)} ساعت دیگه)",
                  f"امتیاز: {game.fa(war['points_a'])} vs {game.fa(war['points_b'])}",
                  "💡 با حمله به اعضای اتحادیهٔ رقیب، امتیاز بگیر!"]
    return "\n".join(lines)


async def clan_panel_kb(clan_id: int, member: dict) -> InlineKeyboardMarkup:
    members = await _db.clan_members(clan_id)
    me_row = next((x for x in members if x["user_id"] == member["user_id"]), None)
    is_leader = bool(me_row and me_row["role"] == "leader")
    war = await _db.active_war_for_clan(clan_id)

    b = InlineKeyboardBuilder()
    b.button(text="📋 اعضای اتحادیه", callback_data=f"clan:members:{clan_id}")
    b.button(text="💰 واریز به خزانه", callback_data=f"clan:deposit:{clan_id}")
    if is_leader:
        b.button(text="⚔️ شروع جنگ اتحادیه", callback_data=f"clan:war:{clan_id}")
        b.button(text="🚪 اخراج عضو", callback_data="clan:kickmenu")
    if not war:
        pass
    else:
        b.button(text="⚔️ وضعیت جنگ", callback_data=f"clan:warstatus:{clan_id}")
    b.button(text="🚪 ترک اتحادیه", callback_data="clan:leave")
    b.adjust(1)
    return b.as_markup()


@router.callback_query(F.data == "clan:list")
async def cb_clan_list(cb: CallbackQuery) -> None:
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    clans = await _db.all_clans()
    if not clans:
        await cb.message.edit_text("هنوز اتحادیه‌ای ساخته نشده! اول تو بساز: "
                                   "<code>/clan_create نام</code>")
        await cb.answer()
        return
    b = InlineKeyboardBuilder()
    lines = ["🏰 <b>اتحادیه‌های موجود</b>", "────────────────"]
    for c in clans[:10]:
        lines.append(f"👥 {esc(c['name'])} — {game.fa(c['members'])} عضو — "
                     f"💰 {game.fa(c['treasury'])} خزانه")
        if not user.get("clan_id"):
            b.button(text=f"➕ پیوستن: {esc(c['name'])}",
                     callback_data=f"clan:join:{c['id']}")
    b.button(text="⬅️ بازگشت", callback_data="nav:clan")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(1)
    await cb.message.edit_text("\n".join(lines), reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("clan:join:"))
async def cb_clan_join(cb: CallbackQuery) -> None:
    clan_id = int(cb.data.split(":")[2])
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    if user.get("clan_id"):
        await cb.answer("اول باید از اتحادیهٔ فعلی خارج شوی!", show_alert=True)
        return
    clan = await _db.get_clan(clan_id)
    if not clan:
        await cb.answer("اتحادیه یافت نشد!", show_alert=True)
        return
    await _db.add_member(clan_id, user["user_id"])
    await cb.answer(f"✅ به {clan['name']} پیوستی!", show_alert=True)
    await cb.message.edit_text(clan_panel_text(clan_id, user),
                               reply_markup=await clan_panel_kb(clan_id, user))


@router.callback_query(F.data.startswith("clan:members:"))
async def cb_clan_members(cb: CallbackQuery) -> None:
    clan_id = int(cb.data.split(":")[2])
    members = await _db.clan_members(clan_id)
    lines = ["📋 <b>اعضای اتحادیه</b>", "────────────────"]
    for m in members:
        role = "👑" if m["role"] == "leader" else "🎖"
        lines.append(f"{role} {esc(name_of(m))} — سطح {game.fa(m['level'])}")
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ بازگشت", callback_data="nav:clan")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(2)
    await cb.message.edit_text("\n".join(lines), reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("clan:deposit:"))
async def cb_clan_deposit(cb: CallbackQuery) -> None:
    clan_id = int(cb.data.split(":")[2])
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    if user["coins"] < 100:
        await cb.answer("حداقل واریز ۱۰۰ سکه است!", show_alert=True)
        return
    amount = min(user["coins"], max(100, user["coins"] // 4))
    clan = await _db.get_clan(clan_id)
    await _db.update_user(user["user_id"], coins=user["coins"] - amount)
    await _db.update_clan(clan_id, treasury=clan["treasury"] + amount)
    await hooks.after_clan_deposit(user["user_id"], amount)
    await cb.answer(f"💰 {game.fa(amount)} سکه به خزانه واریز شد!")
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ بازگشت", callback_data="nav:clan")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(2)
    await cb.message.edit_text(
        f"💰 واریز شد: {game.fa(amount)} سکه\n"
        f"🏰 خزانهٔ «{esc(clan['name'])}»: {game.fa(clan['treasury'] + amount)}",
        reply_markup=b.as_markup())


@router.callback_query(F.data == "clan:leave")
async def cb_clan_leave(cb: CallbackQuery) -> None:
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    if not user.get("clan_id"):
        await cb.answer("عضو اتحادیه‌ای نیستی!", show_alert=True)
        return
    clan_id = user["clan_id"]
    res = await _db.remove_member(user["user_id"])
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ بازگشت", callback_data="nav:clan")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(2)
    if res and res.get("disbanded"):
        await cb.answer("اتحادیه خالی شد و منحل گردید!", show_alert=True)
        await cb.message.edit_text("🏰 از اتحادیه خارج شدی.", reply_markup=b.as_markup())
    else:
        await cb.answer("از اتحادیه خارج شدی!")
        await cb.message.edit_text("🚪 از اتحادیه خارج شدی.\nبرای پیوستن دوباره: /clan", reply_markup=b.as_markup())


@router.callback_query(F.data == "clan:kickmenu")
async def cb_kick_menu(cb: CallbackQuery) -> None:
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    if not user.get("clan_id"):
        await cb.answer("عضو اتحادیه نیستی!", show_alert=True)
        return
    members = await _db.clan_members(user["clan_id"])
    leader = next((m for m in members if m["role"] == "leader"), None)
    if not leader or leader["user_id"] != user["user_id"]:
        await cb.answer("فقط رهبر می‌تواند عضو اخراج کند!", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    for m in members:
        if m["user_id"] == user["user_id"]:
            continue
        b.button(text=f"🚪 {esc(name_of(m))}",
                 callback_data=f"clan:kick:{m['user_id']}")
    if not b.buttons:
        await cb.answer("عضو دیگری نیست!", show_alert=True)
        return
    await cb.message.edit_text("کدام عضو را اخراج کنم؟",
                               reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("clan:kick:"))
async def cb_clan_kick(cb: CallbackQuery) -> None:
    victim_id = int(cb.data.split(":")[2])
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    members = await _db.clan_members(user["clan_id"])
    victim = next((m for m in members if m["user_id"] == victim_id), None)
    leader = next((m for m in members if m["role"] == "leader"), None)
    if not victim or not leader or leader["user_id"] != user["user_id"]:
        await cb.answer("اجازه نداری!", show_alert=True)
        return
    await _db.remove_member(victim_id)
    await cb.answer(f"{victim['first_name']} اخراج شد!")
    try:
        await cb.message.bot.send_message(victim_id, "🚪 از اتحادیه اخراج شدی!")
    except Exception:
        pass
    await cb.message.edit_text("✅ اخراج انجام شد.", reply_markup=None)


# ================================================================ جنگ اتحادیه
@router.callback_query(F.data.startswith("clan:war:"))
async def cb_clan_war(cb: CallbackQuery) -> None:
    clan_id = int(cb.data.split(":")[2])
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    members = await _db.clan_members(clan_id)
    is_leader = any(m["user_id"] == user["user_id"] and m["role"] == "leader"
                    for m in members)
    if not is_leader:
        await cb.answer("فقط رهبر می‌تواند جنگ را شروع کند!", show_alert=True)
        return
    clan = await _db.get_clan(clan_id)
    if clan["treasury"] < game.WAR_START_COST:
        await cb.answer(f"خزانه کافی نیست! شروع جنگ {game.fa(game.WAR_START_COST)} سکه "
                        "می‌خواهد.", show_alert=True)
        return
    enemy = await _db.random_enemy_clan(clan_id)
    if not enemy:
        await cb.answer("اتحادیهٔ رقیب آماده‌ای نیست!", show_alert=True)
        return
    await _db.update_clan(clan_id, treasury=clan["treasury"] - game.WAR_START_COST)
    war = await _db.create_war(clan_id, enemy["id"])
    await cb.answer("🔥 جنگ اتحادیه‌ای آغاز شد!")
    text = (
        "🔥 <b>جنگ اتحادیه‌ای آغاز شد!</b>\n"
        f"⚔️ «{esc(clan['name'])}» علیه «{esc(enemy['name'])}»\n"
        f"⏱ ۲۴ ساعت برای امتیاز گرفتن!\n"
        "💡 با حملهٔ تصادفی به اعضای اتحادیهٔ رقیب امتیاز بگیر!\n"
        "🏆 برنده ۲۵٪ خزانهٔ بازنده را تصاحب می‌کند!"
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="📊 وضعیت جنگ", callback_data="nav:clan")
    b.button(text="⬅️ بازگشت", callback_data="nav:clan")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(1,2)
    await cb.message.edit_text(text, reply_markup=b.as_markup())
    for mid in await _db.member_ids(enemy["id"]):
        try:
            await cb.message.bot.send_message(
                mid,
                f"⚠️ اتحادیهٔ «{esc(clan['name'])}» به شما اعلام جنگ داد!\n"
                f"🔥 جنگ ۲۴ ساعته شروع شد. با حمله به اعضایشان امتیاز بگیرید!")
        except Exception:
            pass


@router.callback_query(F.data.startswith("clan:warstatus:"))
async def cb_war_status(cb: CallbackQuery) -> None:
    clan_id = int(cb.data.split(":")[2])
    war = await _db.active_war_for_clan(clan_id)
    if not war:
        clan = await _db.get_clan(clan_id)
        await cb.message.edit_text(
            f"🏰 جنگ فعالی برای «{esc(clan['name'])}» نیست.\n"
            "با /clan_status ببین یا رهبرت جنگ جدیدی شروع کند!",
        )
        await cb.answer()
        return
    a = await _db.get_clan(war["clan_a"])
    b = await _db.get_clan(war["clan_b"])
    left = war["end_ts"] - time.time()
    await cb.message.edit_text(
        f"🔥 <b>جنگ اتحادیه‌ای</b>\n"
        f"⚔️ {esc(a['name'])} ({game.fa(war['points_a'])}) "
        f"در برابر {esc(b['name'])} ({game.fa(war['points_b'])})\n"
        f"⏱ باقی‌مانده: {game.fa(int(left // 3600))} ساعت و "
        f"{game.fa(int((left % 3600) // 60))} دقیقه",
    )
    await cb.answer()


@router.message(Command("clan_status"))
async def cmd_clan_status(message: Message) -> None:
    u = message.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    if not user.get("clan_id"):
        await message.answer("عضو اتحادیه‌ای نیستی! با /clan شروع کن.")
        return
    war = await _db.active_war_for_clan(user["clan_id"])
    if not war:
        await message.answer("جنگ فعالی نداری.")
        return
    a = await _db.get_clan(war["clan_a"])
    b = await _db.get_clan(war["clan_b"])
    left = war["end_ts"] - time.time()
    await message.answer(
        f"🔥 <b>وضعیت جنگ</b>\n"
        f"⚔️ {esc(a['name'])} ({game.fa(war['points_a'])}) "
        f"در برابر {esc(b['name'])} ({game.fa(war['points_b'])})\n"
        f"⏱ باقی‌مانده: {game.fa(int(left // 3600))} ساعت و "
        f"{game.fa(int((left % 3600) // 60))} دقیقه",
    )


# ================================================================ ساخت/پیوستن
@router.message(Command("clan_create"))
async def cmd_clan_create(message: Message, command: CommandObject) -> None:
    # محدودیت: فقط در گروه‌ها
    chat = message.chat
    if chat.type == "private":
        await message.answer(
            "⛔ <b>ساخت اتحادیه فقط در گروه‌ها امکان‌پذیر است!</b>\n"
            "────────────────\n"
            "لطفاً این دستور را در یک گروه تلگرامی اجرا کن — اتحادیه به همان گروه تعلق خواهد داشت.\n"
            "👑 اتحادیه‌های موجود را با /clans یا از منوی «🏰 اتحادیه» ببین."
        )
        return
    u = message.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    if user.get("clan_id"):
        await message.answer("تو الان عضو اتحادیه‌ای! اول با /clan و ترک، خارج شو.")
        return
    name = (command.args or "").strip().strip('"')
    if not name or len(name) > 20:
        await message.answer("❌ نام معتبر بده (حداکثر ۲۰ حرف): /clan_create نام")
        return
    if await _db.clan_by_name(name):
        await message.answer("❌ اتحادیه‌ای با این نام وجود دارد!")
        return
    group_title = getattr(chat, "title", "") or ""
    clan = await _db.create_clan(name, user["user_id"], group_id=chat.id, group_title=group_title)
    await message.answer(
        f"🏰 <b>اتحادیهٔ «{esc(clan['name'])}» ساخته شد!</b>\n"
        f"👑 تو رهبر هستی.\n"
        f"💡 با /clan مدیریت کن — اعضا را با /clans دعوت کن."
    )


@router.message(Command("clan_join"))
async def cmd_clan_join(message: Message, command: CommandObject) -> None:
    u = message.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    if user.get("clan_id"):
        await message.answer("تو الان عضو اتحادیه‌ای! با کردن /clan ببین.")
        return
    name = (command.args or "").strip()
    clan = await _db.clan_by_name(name) if name else None
    if not clan:
        await message.answer("❌ اتحادیه‌ای با این نام پیدا نشد. /clans را ببین.")
        return
    await _db.add_member(clan["id"], user["user_id"])
    await message.answer(
        f"🎉 به اتحادیهٔ «{esc(clan['name'])}» پیوستی!\n"
        "با /clan وضعیت و خزانه را ببین."
    )


@router.message(Command("clans"))
async def cmd_clans(message: Message) -> None:
    u = message.from_user
    await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    clans = await _db.all_clans()
    if not clans:
        await message.answer("هنوز اتحادیه‌ای ساخته نشده! اولین نفر باش: "
                             "<code>/clan_create نام</code>")
        return
    lines = ["🏰 <b>اتحادیه‌های نبردگاه</b>", "────────────────"]
    medals = ["🥇", "🥈", "🥉"] + ["🔸"] * 7
    for i, c in enumerate(clans[:10]):
        lines.append(f"{medals[i]} {esc(c['name'])} — {game.fa(c['members'])} عضو — "
                     f"💰 {game.fa(c['treasury'])} خزانه — "
                     f"🏆 {game.fa(c['war_wins'])}/⚔️ {game.fa(c['war_losses'])}")
    await message.answer("\n".join(lines))
