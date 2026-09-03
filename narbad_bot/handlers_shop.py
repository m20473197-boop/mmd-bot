"""فروشگاه آیتم‌های ویژه و موجودی کاربر."""
from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import admin_core, game, hooks
from .db import DB

router = Router(name="shop")

_db: DB | None = None


def setup(db: DB) -> None:
    global _db
    _db = db


def _user_coin(cb: CallbackQuery, u: dict) -> int:
    return u.get("coins", 0)


# ================================================================ /shop
@router.message(Command("shop"))
async def cmd_shop(message: Message) -> None:
    u = await message.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    await message.answer(shop_text(user), reply_markup=shop_kb())


def shop_text(u: dict) -> str:
    return (
        "🏅 <b>فروشگاه ویژهٔ نبردگاه</b>\n"
        f"💰 موجودی: <b>{admin_core.coins_display(u)}</b> سکه\n"
        f"────────────────\n"
        "💡 با هر خرید، مأموریت «خرج سکه» هم پیش می‌رود!\n"
        "👑 مدیران: خریدها رایگان و نامحدود است."
        "\nبرای دیدن آیتم‌های خریده‌شده: /inventory"
    )


def shop_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, item in game.ITEMS.items():
        b.button(
            text=f"{item['emoji']} {item['name']} — {game.fa(item['price'])}💰",
            callback_data=f"shopbuy:{key}",
        )
    b.button(text="🎒 موجودی من", callback_data="inventory")
    b.button(text="⬅️ بازگشت", callback_data="nav:shop")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(1)
    return b.as_markup()


@router.callback_query(F.data == "inventory")
async def cb_inventory(cb: CallbackQuery) -> None:
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    await cb.message.edit_text(inventory_text(user), reply_markup=inventory_kb(user))
    await cb.answer()


def inventory_text(user: dict) -> str:
    lines = ["🎒 <b>موجودی و بافت‌های فعال</b>", "────────────────"]
    inv = inv_cache.get(user["user_id"], {})
    buffs = buff_cache.get(user["user_id"], {})
    now = int(time.time())
    for key, qty in inv.items():
        item = game.ITEMS.get(key)
        if item:
            lines.append(f"{item['emoji']} {item['name']} × {game.fa(qty)} — {item['desc']}")
    for buff, until in buffs.items():
        item = game.ITEMS.get(buff)
        if item and until > now:
            mins = int((until - now) // 60)
            lines.append(f"✨ {item['emoji']} {item['name']} فعال ({game.fa(mins)} دقیقه)")
    if len(lines) == 2:
        lines.append("هنوز چیزی نداری! از /shop بخر 🛍")
    return "\n".join(lines)


# کش‌های سبک برای ساخت پیام (در هر فراخوانی تازه می‌شوند)
inv_cache: dict[int, dict[str, int]] = {}
buff_cache: dict[int, dict[str, int]] = {}


def inventory_kb(user: dict) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    inv = inv_cache.get(user["user_id"], {})
    for key, qty in inv.items():
        item = game.ITEMS.get(key)
        if not item or qty <= 0:
            continue
        if item["kind"] in ("buff", "instant"):
            b.button(text=f"✨ استفاده: {item['emoji']} {item['name']}",
                     callback_data=f"use:{key}")
    b.button(text="🏅 فروشگاه", callback_data="nav:shop")
    b.button(text="⬅️ بازگشت", callback_data="nav:shop")
    b.button(text="🏠 منوی اصلی", callback_data="nav:main")
    b.adjust(1)
    return b.as_markup()


# ================================================================ خرید آیتم
@router.callback_query(F.data.startswith("shopbuy:"))
async def cb_shopbuy(cb: CallbackQuery) -> None:
    key = cb.data.split(":", 1)[1]
    item = game.ITEMS.get(key)
    if not item:
        await cb.answer("آیتم نامعتبر!", show_alert=True)
        return
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    # مدیر: خرید رایگان/نامحدود؛ دیگران: کسر عادی
    if not await admin_core.pay(user, item["price"]):
        await cb.answer("سکه کافی نداری! 🪙", show_alert=True)
        return

    if item["kind"] == "pack":
        # جعبهٔ یگان → مستقیم به ارتش
        army = await _db.get_army(user["user_id"])
        await _db.set_unit(user["user_id"], item["unit"],
                           army.get(item["unit"], 0) + item["count"])
        msg = (f"✅ {item['emoji']} {item['name']} باز شد!\n"
               f"✨ {game.DISP[item['unit']]['emoji']} ×{game.fa(item['count'])} "
               f"{game.DISP[item['unit']]['name']} به ارتشت اضافه شد.")
    else:
        await _db.inv_add(user["user_id"], key, 1)
        msg = f"✅ {item['emoji']} {item['name']} به موجودی‌ات اضافه شد."

    await hooks.after_purchase(user["user_id"], 0, item["price"])

    user = await _db.get_user(user["user_id"])
    await cb.answer(msg.replace("\n", " ")[:190])
    keep_menu = admin_core.is_dev(user["user_id"]) or user["coins"] >= 900
    await cb.message.edit_text(
        f"{msg}\n💰 موجودی: {admin_core.coins_display(user)} سکه",
        reply_markup=shop_kb() if keep_menu else None,
    )


# ================================================================ استفاده از آیتم
@router.callback_query(F.data.startswith("use:"))
async def cb_use(cb: CallbackQuery) -> None:
    key = cb.data.split(":", 1)[1]
    item = game.ITEMS.get(key)
    if not item:
        await cb.answer("آیتم نامعتبر!", show_alert=True)
        return
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    inv = await _db.inv_get(user["user_id"])
    if inv.get(key, 0) <= 0:
        await cb.answer("این آیتم را نداری!", show_alert=True)
        return

    if item["kind"] == "buff":
        await _db.set_buff(user["user_id"], key,
                           int(time.time()) + item.get("duration", game.BUFF_DURATION))
        await _db.inv_take(user["user_id"], key)
        msg = f"✨ {item['emoji']} {item['name']} فعال شد! ({item['desc']})"
    elif item["kind"] == "instant":
        energy, ts = game.effective_energy(user)
        new_energy = min(game.MAX_ENERGY, energy + item.get("value", 40))
        await _db.update_user(user["user_id"], energy=new_energy,
                              energy_ts=int(time.time()) if energy >= game.MAX_ENERGY else ts)
        await _db.inv_take(user["user_id"], key)
        msg = f"⚡ {game.fa(item.get('value', 40))} انرژی گرفتی! (اکنون: {game.fa(new_energy)})"
    else:
        await cb.answer("این آیتم به‌صورت خودکار در نبرد مصرف می‌شود! 🛠", show_alert=True)
        return

    user = await _db.get_user(user["user_id"])
    inv = await _db.inv_get(user["user_id"])
    buffs = await _db.buffs_active(user["user_id"])
    inv_cache[user["user_id"]] = inv
    buff_cache[user["user_id"]] = buffs
    await cb.answer("✅")
    await cb.message.edit_text(
        f"{msg}\n\n" + inventory_text(user), reply_markup=inventory_kb(user))


@router.callback_query(F.data == "menu:shop")
async def cb_menu_shop(cb: CallbackQuery) -> None:
    u = cb.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    await cb.message.edit_text(shop_text(user), reply_markup=shop_kb())
    await cb.answer()


# ================================================================ /inventory
@router.message(Command("inventory"))
async def cmd_inventory(message: Message) -> None:
    u = message.from_user
    user = await _db.ensure_user(u.id, u.username or "", u.first_name or "")
    inv = await _db.inv_get(user["user_id"])
    buffs = await _db.buffs_active(user["user_id"])
    inv_cache[user["user_id"]] = inv
    buff_cache[user["user_id"]] = buffs
    await message.answer(inventory_text(user), reply_markup=inventory_kb(user))
