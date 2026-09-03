"""مأموریت‌های روزانه و استخراج منابع (معدن)."""
from __future__ import annotations

import logging
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardMarkup, Message)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import game, hooks
from .db import DB

router = Router(name="missions")

_db: DB | None = None

log = logging.getLogger(__name__)


def setup(db: DB) -> None:
    global _db
    _db = db


# ================================================================ مأموریت‌ها
async def render_missions(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """متن و صفحه‌کلید پنل مأموریت‌ها — یک منبع واحد برای همهٔ مسیرهای نمایش.

    همیشه از دیتابیس تازه می‌خواند تا وضعیت (در حال انجام / آماده / دریافت‌شده)
    دقیق و صحیح باشد.
    """
    rows = await _db.missions_today(user_id)
    return missions_text(rows), missions_kb(user_id, rows)


def missions_text(rows: dict[str, dict]) -> str:
    lines = ["⛏ <b>مأموریت‌های روزانه</b>", "────────────────",
             "هر روز نیمه‌شب ریست می‌شوند:"]
    for key, spec in game.MISSIONS.items():
        row = rows.get(key)
        progress = row["progress"] if row else 0
        claimed = bool(row and row.get("claimed"))
        if claimed:
            status = "✅ دریافت شد"
        elif progress >= spec["target"]:
            status = "🟢 آمادهٔ دریافت — پایین را بزن!"
        else:
            status = "🔸 ادامه بده"
        lines.append(
            f"{spec.get('emoji', '')} {spec['name']}\n"
            f"   پیشرفت: {game.fa(min(progress, spec['target']))}/"
            f"{game.fa(spec['target'])} — جایزه: "
            f"{game.fa(spec['coins'])}💰 + {game.fa(spec['xp'])}⭐ — {status}"
        )
    lines.append("────────────────")
    lines.append("💡 برای استخراج منابع: /mine")
    return "\n".join(lines)


def missions_kb(user_id: int, rows: dict[str, dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, spec in game.MISSIONS.items():
        row = rows.get(key)
        progress = row["progress"] if row else 0
        claimed = bool(row and row.get("claimed"))
        if not claimed and progress >= spec["target"]:
            b.button(text=f"🎁 دریافت: {spec.get('emoji', '')} {spec['name']}",
                     callback_data=f"claim:{key}")
    b.button(text="⛏ معدن / استخراج", callback_data="mine:panel")
    b.button(text="⬅️ بازگشت", callback_data="nav:base")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(1)
    return b.as_markup()


@router.message(Command("missions"))
async def cmd_missions(message: Message) -> None:
    u = message.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    text, kb = await render_missions(user["user_id"])
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "missions:show")
async def cb_missions_show(cb: CallbackQuery) -> None:
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    try:
        text, kb = await render_missions(user["user_id"])
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:  # noqa: BLE001 — اگر پیام قابل ویرایش نبود، پیام تازه بفرست
        log.exception("عدم توانایی در ویرایش پنل مأموریت‌ها")
        text, kb = await render_missions(user["user_id"])
        await cb.message.answer(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("claim:"))
async def cb_claim(cb: CallbackQuery) -> None:
    key = cb.data.split(":", 1)[1]
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")

    if key not in game.MISSIONS:
        await cb.answer("❌ مأموریت ناشناخته!", show_alert=True)
        return

    # ۱) گرفتن جایزه (اتمی؛ دوبار لمس یا رقابت هم‌زمان جایزهٔ دوباره نمی‌دهد)
    result = await hooks.claim_mission_rewards(user["user_id"], key)
    if result is None:
        await cb.answer("این مأموریت هنوز کامل نشده یا قبلاً گرفته شده!",
                        show_alert=True)
        return
    coins, xp = result

    # ۲) تازه‌سازی منو از دیتابیس؛ اگر ویرایش نشد، پیام تازه بفرست تا
    #    منو هرگز از دست نرود.
    try:
        text, kb = await render_missions(user["user_id"])
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:  # noqa: BLE001
        log.exception("عدم توانایی در ویرایش منوی مأموریت‌ها پس از دریافت جایزه")
        try:
            text, kb = await render_missions(user["user_id"])
            await cb.message.answer(text, reply_markup=kb)
        except Exception:  # noqa: BLE001
            log.exception("عدم توانایی در نمایش مجدد منوی مأموریت‌ها")

    await cb.answer(f"🎁 جایزه دریافت شد! {game.fa(coins)}💰 + {game.fa(xp)}⭐")


# ================================================================ معدن
@router.message(Command("mine"))
async def cmd_mine(message: Message) -> None:
    u = message.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    state = await _db.mine_get(user["user_id"])
    if state is None:
        army = await _db.get_army(user["user_id"])
        workers = min(game.MINE_WORKER_CAP, army.get("soldier", 0))
        if workers <= 0:
            await message.answer("⛏ اول با /train سرباز بخر تا معدنچی داشته باشی!")
            return
        await _db.mine_start(user["user_id"], int(time.time()), workers)
        await message.answer(
            f"⛏ <b>استخراج آغاز شد!</b>\n"
            f"🪖 {game.fa(workers)} سرباز به معدن رفتند.\n"
            f"💰 نرخ: هر سرباز {game.fa(game.MINE_RATE)} سکه در ساعت "
            f"(تا سقف {game.fa(game.MINE_MAX_HOURS)} ساعت)\n"
            f"📊 دوباره /mine بزن تا وضعیت و برداشت را ببینی."
        )
        return

    gain = game.mine_gain(state["workers"], int(time.time()) - state["start_ts"])
    await message.answer(mine_status_text(state, gain), reply_markup=mine_kb())


def mine_status_text(state: dict, gain: int) -> str:
    elapsed = int(time.time()) - state["start_ts"]
    hours = min(game.MINE_MAX_HOURS, elapsed / 3600)
    full = gain >= state["workers"] * game.MINE_RATE * game.MINE_MAX_HOURS
    return (
        f"⛏ <b>معدن در حال کار است</b>\n"
        f"🪖 معدنچی‌ها: {game.fa(state['workers'])} سرباز\n"
        f"⏱ گذشت: {game.fa(int(hours * 60))} دقیقه از "
        f"{game.fa(game.MINE_MAX_HOURS * 60)} دقیقه\n"
        f"💰 آمادهٔ برداشت: <b>{game.fa(gain)}</b> سکه"
        + ("\n🔒 به سقف ۸ ساعت رسیدی!" if full else "")
        + "\n\nبرای برداشت روی دکمهٔ زیر بزن:"
    )


def mine_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💰 برداشت سکه‌ها", callback_data="mine:claim")
    b.button(text="⬅️ بازگشت", callback_data="nav:base")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(1)
    return b.as_markup()


@router.callback_query(F.data == "mine:panel")
async def cb_mine_panel(cb: CallbackQuery) -> None:
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    state = await _db.mine_get(user["user_id"])
    if state is None:
        await cb.message.edit_text(
            "⛏ <b>معدن</b>\nبا /mine سربازهایت را به معدن بفرست "
            "تا به‌مرور سکه استخراج کنند.\n"
            "💡 هر سرباز در ساعت ۳ سکه می‌سازد (سقف ۸ ساعت).",
            reply_markup=mine_kb())
    else:
        gain = game.mine_gain(state["workers"], int(time.time()) - state["start_ts"])
        await cb.message.edit_text(mine_status_text(state, gain),
                                   reply_markup=mine_kb())
    await cb.answer()


@router.callback_query(F.data == "mine:claim")
async def cb_mine_claim(cb: CallbackQuery) -> None:
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    state = await _db.mine_get(user["user_id"])
    if state is None:
        await cb.answer("معدن فعالی نداری!", show_alert=True)
        return
    gain = game.mine_gain(state["workers"], int(time.time()) - state["start_ts"])
    if gain <= 0:
        await cb.answer("هنوز چیزی استخراج نشده! کمی صبر کن ⏳", show_alert=True)
        return

    await _db.mine_clear(user["user_id"])
    xp_gain = max(5, gain // 40)
    xp, lvl, gained, bonus = game.add_xp(user["xp"], user["level"], xp_gain)
    total = gain + (bonus if gained else 0)
    await _db.update_user(user["user_id"], coins=user["coins"] + total, xp=xp, level=lvl)
    await hooks.after_mine_claim(user["user_id"])

    user = await _db.get_user(user["user_id"])
    await cb.answer(f"💰 {game.fa(gain)} سکه برداشت شد!")
    await cb.message.edit_text(
        f"💰 <b>برداشت موفق!</b>\n"
        f"⛏ سکهٔ استخراج‌شده: <b>{game.fa(gain)}</b>\n"
        f"⭐ تجربه: +{game.fa(xp_gain)}"
        + (f"\n🎉 ارتقا سطح! سطح {game.fa(lvl)}" if gained else "")
        + f"\n💰 موجودی: {game.fa(user['coins'])}",
        reply_markup=None)
