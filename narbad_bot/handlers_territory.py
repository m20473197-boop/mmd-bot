"""نقشهٔ قلمروها — حملات هم‌زمان چند بازیکن به قلمروهای مشترک."""
from __future__ import annotations

import html
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardMarkup, Message)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import admin_core, game
from .db import DB

router = Router(name="territory")

_db: DB | None = None


def setup(db: DB) -> None:
    global _db
    _db = db


def esc(t: str) -> str:
    return html.escape(str(t))


def name_of(u: dict) -> str:
    return u.get("first_name") or u.get("username") or "بازیکن"


@router.message(Command("territory"))
async def cmd_territory(message: Message) -> None:
    u = message.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    await message.answer(await map_text(), reply_markup=await map_kb(user))


@router.message(Command("map"))
async def cmd_map(message: Message) -> None:
    await cmd_territory(message)


async def map_text() -> str:
    ters = await _db.territories()
    lines = [
        "🗺 <b>نقشهٔ قلمروهای نبردگاه</b>",
        "────────────────",
        "هر قلمرو یک هدف مشترک است؛ همهٔ بازیکنان می‌توانند هم‌زمان "
        "به یک قلمرو حمله کنند! 💥",
        "────────────────",
        "🏆 هر ۲۴ ساعت، قلمروهایی که سقوط کنند به اتحادیهٔ صاحب بیشترین خسارت "
        "می‌رسند، سطح‌شان بالا می‌رود و جایزهٔ روزانه برداشت می‌شود.",
        "",
    ]
    for t in ters:
        pct = t["hp"] / t["max_hp"] * 100
        if t.get("owner_clan"):
            clan = await _db.get_clan(t["owner_clan"])
            owner = f"🏰 {esc(clan['name'])}" if clan else "—"
        else:
            owner = "🌫 بدون مالک"
        lines.append(
            f"{t['name']} — سطح {game.fa(t['level'])}\n"
            f"   ❤️ سلامت: {game.fa(t['hp'])}/{game.fa(t['max_hp'])} "
            f"({game.fa(round(pct))}٪) — {owner}"
        )
    return "\n".join(lines)


async def map_kb(user: dict) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    ters = await _db.territories()
    for t in ters:
        b.button(text=f"⚔️ {t['name']} ({game.fa(round(t['hp'] / t['max_hp'] * 100))}٪)",
                 callback_data=f"terr:view:{t['id']}")
    b.button(text="⬅️ بازگشت", callback_data="nav:clan")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(2)
    return b.as_markup()


@router.callback_query(F.data.startswith("terr:view:"))
async def cb_terr_view(cb: CallbackQuery) -> None:
    tid = int(cb.data.split(":")[2])
    t = await _db.get_territory(tid)
    if not t:
        await cb.answer("قلمرو یافت نشد!", show_alert=True)
        return
    top = await _db.terr_contribs(tid, 5)
    lines = [
        f"⚔️ <b>{t['name']}</b> (سطح {game.fa(t['level'])})",
        f"❤️ {game.fa(t['hp'])}/{game.fa(t['max_hp'])}",
        "────────────────",
        "💥 هر حمله به این قلمرو خسارت می‌زند و امتیازت ثبت می‌شود:",
    ]
    if top:
        lines.append("🏅 <b>بیشترین خسارت:</b>")
        for i, c in enumerate(top, 1):
            u = await _db.get_user(c["user_id"])
            lines.append(f"  {i}. {esc(name_of(c))} — {game.fa(c['damage'])} خسارت")
    else:
        lines.append("هنوز کسی حمله نکرده — تو اولین باش!")
    b = InlineKeyboardBuilder()
    b.button(text=f"💥 حمله ({game.fa(game.TERR_ATTACK_ENERGY)}⚡)",
             callback_data=f"terr:attack:{tid}")
    b.button(text="🗺 بازگشت به نقشه", callback_data="terr:map")
    b.button(text="⬅️ بازگشت", callback_data="nav:clan")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(1,2)
    await cb.message.edit_text("\n".join(lines), reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data == "terr:map")
async def cb_terr_map(cb: CallbackQuery) -> None:
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    await cb.message.edit_text(await map_text(), reply_markup=await map_kb(user))
    await cb.answer()


@router.callback_query(F.data.startswith("terr:attack:"))
async def cb_terr_attack(cb: CallbackQuery) -> None:
    tid = int(cb.data.split(":")[2])
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")

    t = await _db.get_territory(tid)
    if not t:
        await cb.answer("قلمرو یافت نشد!", show_alert=True)
        return

    # --- محدودیت ۳۰ ثانیه‌ای (مدیر/تست‌کننده: بدون محدودیت)
    now = time.time()
    if not admin_core.no_cooldown(user["user_id"]):
        last = _terr_cooldown.get(user["user_id"], 0)
        if now - last < game.TERR_COOLDOWN:
            await cb.answer(f"⏳ {game.fa(int(game.TERR_COOLDOWN - (now - last)))} "
                            "ثانیه صبر کن!", show_alert=True)
            return

    # --- بررسی انرژی (مدیر: نامحدود)
    if not admin_core.can_pay_energy(user, game.TERR_ATTACK_ENERGY):
        await cb.answer("⚡ انرژی کافی نداری!", show_alert=True)
        return

    # --- قدرت
    army = await _db.get_army(user["user_id"])
    power = game.attack_power(army)
    if power <= 0:
        await cb.answer("🪖 اول با /train یگان بخر!", show_alert=True)
        return

    # --- مصرف انرژی پس از عبور از همهٔ بررسی‌ها (مدیر: بدون کسر)
    if not await admin_core.try_spend_energy(user, game.TERR_ATTACK_ENERGY):
        await cb.answer("⚡ انرژی کافی نداری!", show_alert=True)
        return
    _terr_cooldown[user["user_id"]] = now

    # --- خسارت
    damage = max(25, round(power * 0.12 * (1 + user["level"] * 0.05)))
    loot = round(damage * 1.6 + user["level"] * 10)

    new_hp = t["hp"] - damage
    fell = new_hp <= 0

    if fell:
        # --- قلمرو سقوط کرد: اتحادیهٔ بهترین مهاجم صاحبش می‌شود
        contribs = await _db.terr_contribs(tid, top=1000)
        best = max(contribs, key=lambda c: c["damage"]) if contribs else None
        owner_clan = best.get("clan_id") if best else None
        new_level = t["level"] + 1
        new_max = game.territory_hp(new_level)
        await _db.update_territory(tid, hp=new_max, max_hp=new_max,
                                   level=new_level, owner_clan=owner_clan)
        await _db.clear_terr_contribs(tid)
        await _db.add_terr_contrib(tid, user["user_id"], damage)
    else:
        await _db.update_territory(tid, hp=new_hp)
        await _db.add_terr_contrib(tid, user["user_id"], damage)

    # --- جایزه و تجربه
    xp_gain = max(15, damage // 20)
    xp, lvl, gained, bonus = game.add_xp(user["xp"], user["level"], xp_gain)
    total = loot + (bonus if gained else 0)
    await _db.update_user(user["user_id"], coins=user["coins"] + total, xp=xp, level=lvl)

    t = await _db.get_territory(tid)
    msg = (
        f"💥 <b>حمله به قلمرو!</b>\n"
        f"🗺 {t['name']} — سطح {game.fa(t['level'])}\n"
        f"────────────────\n"
        f"🎯 خسارت: <b>{game.fa(damage)}</b> | "
        f"❤️ باقی‌مانده: {game.fa(t['hp'])}/{game.fa(t['max_hp'])}\n"
        f"💰 جایزه: {game.fa(total)} سکه | ⭐ تجربه: +{game.fa(xp_gain)}"
    )
    if fell:
        if owner_clan:
            clan = await _db.get_clan(owner_clan)
            oname = esc(clan["name"]) if clan else "—"
        else:
            oname = "—"
        msg += (f"\n🏴 <b>قلمرو سقوط کرد و بازسازی شد!</b>\n"
                f"📍 مالک جدید: {oname} — سطح به {game.fa(new_level)} رسید.")
        # اعلان به اعضای مالک جدید
        if owner_clan:
            for mid in await _db.member_ids(owner_clan):
                try:
                    await cb.message.bot.send_message(
                        mid, f"🏴 اتحادیهٔ شما قلمرو «{t['name']}» را تصرف کرد!")
                except Exception:
                    pass

    await cb.answer(f"💥 {game.fa(damage)} خسارت زدی!")
    await cb.message.edit_text(msg, reply_markup=await map_kb(await _db.get_user(user["user_id"])))


_terr_cooldown: dict[int, float] = {}
