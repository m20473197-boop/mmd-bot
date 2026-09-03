"""🛠 هستهٔ اختیارات مدیران — اعمال داینامیک امتیازهای تست.

مهم‌ترین اصل: هیچ مقدار «بی‌نهایت» در دیتابیس ذخیره نمی‌شود.
به‌جای آن، در لحظهٔ هر بررسی، نوع کاربر از روی admins.DEVELOPER_IDS /
TESTER_IDS خوانده می‌شود و رفتار مناسب اعمال می‌گردد:

    • Developer → سکه/انرژی/خرید بی‌نهایت (بدون کسر از دیتابیس)
    • Tester    → هدیهٔ تست یک‌باره + تجربهٔ ×۲ + بدون کول‌داون
    • سایر      → اقتصاد عادی (بدون هیچ تغییری)
"""
from __future__ import annotations

import time

from . import admins, game
from .db import DB

_db: DB | None = None


def setup(db: DB) -> None:
    """اتصال هسته به دیتابیس + ثبت هوکِ هدیهٔ تست‌کننده‌ها.

    هوک روی DB.ensure_user سوار می‌شود تا هر جایی از بازی که کاربر
    «بازیابی» می‌شود، هدیهٔ تست به‌صورت خودکار و فقط یک‌بار اعمال شود.
    """
    global _db
    _db = db
    db.user_hook = _user_hook


# ─────────────────────────────── ثابت‌های هدیهٔ تست ─────────────────────────
TESTER_GIFT_COINS = 100_000          # سکهٔ هدیهٔ اولین ورود
TESTER_GIFT_XP = 20_000              # تجربهٔ هدیه (چند سطح بالا می‌برد)
TESTER_GIFT_ARMY = {                 # یگان‌های هدیه
    "soldier": 50, "commando": 10, "tank": 5, "heli": 3,
    "fighter": 2, "missile": 2, "drone": 1,
}
TESTER_GIFT_DEFENSES = {"wall": 5, "air_defense": 2}
TESTER_GIFT_ITEMS = {"energy_pack": 3, "lucky": 1, "magnet": 1, "repair": 2}


# ─────────────────────────────── بررسی‌های دسترسی ───────────────────────────
def is_dev(user_id: int) -> bool:
    return admins.is_developer(user_id)


def is_tester(user_id: int) -> bool:
    return admins.is_tester(user_id)


def no_cooldown(user_id: int) -> bool:
    """مدیر و تست‌کننده کول‌داون حمله ندارند (تست سریع)."""
    return admins.is_privileged(user_id)


def xp_multiplier(user_id: int) -> float:
    """ضریب تجربه: تست‌کننده ×۲ (پیشرفت سریع‌تر)، مدیر و عادی ×۱."""
    return 2.0 if admins.is_tester(user_id) else 1.0


# ─────────────────────────────── سکه (بی‌نهایت داینامیک) ────────────────────
def coins_display(user: dict) -> str:
    """نمایش موجودی: مدیر «∞» می‌بیند ولی در دیتابیس چیزی تغییر نمی‌کند."""
    if admins.is_developer(user["user_id"]):
        return "∞"
    return game.fa(user.get("coins", 0))


def energy_display(user: dict) -> str:
    """نمایش انرژی: مدیر «∞» می‌بیند."""
    if admins.is_developer(user["user_id"]):
        return "∞"
    energy, _ = game.effective_energy(user)
    return f"{game.fa(energy)}/{game.fa(game.MAX_ENERGY)}"


async def can_pay(user: dict, amount: int) -> bool:
    """آیا کاربر توان پرداخت دارد؟ (مدیر همیشه بله)"""
    if admins.is_developer(user["user_id"]):
        return True
    return user.get("coins", 0) >= amount


async def pay(user: dict, amount: int) -> bool:
    """کسر سکه با حفظ اقتصاد سالم.

    • مدیر → بدون کسر (خرید رایگان/نامحدود)
    • دیگران → اگر سکه کافی بود کسر می‌شود؛ در غیر این صورت False
    """
    uid = user["user_id"]
    if admins.is_developer(uid):
        return True
    coins = user.get("coins", 0)
    if coins < amount:
        return False
    await _db.update_user(uid, coins=coins - amount)
    return True


# ─────────────────────────────── انرژی (نامحدود داینامیک) ───────────────────
def can_pay_energy(user: dict, cost: int) -> bool:
    """بررسی تأمین انرژی (بدون تغییر) — مدیر همیشه بله."""
    if admins.is_developer(user["user_id"]):
        return True
    energy, _ = game.effective_energy(user)
    return energy >= cost


async def try_spend_energy(user: dict, cost: int) -> bool:
    """مصرف انرژی؛ مدیر هرگز انرژی کم نمی‌آورد و چیزی از او کم نمی‌شود.

    خروجی: True یعنی انرژی تأمین شد (و برای غیر مدیر از دیتابیس کم شد).
    """
    uid = user["user_id"]
    if admins.is_developer(uid):
        return True
    energy, ts = game.effective_energy(user)
    if energy < cost:
        return False
    await _db.update_user(uid, energy=energy - cost, energy_ts=int(time.time()))
    return True


# ─────────────────────────────── هدیهٔ تست‌کننده ─────────────────────────────
async def _user_hook(user: dict) -> dict:
    """هوک ثبت‌شده روی DB.ensure_user — هدیهٔ تست فقط یک‌بار و فقط برای Tester."""
    uid = user["user_id"]
    if not admins.is_tester(uid):
        return user
    if user.get("tester_granted"):
        return user

    # --- اعمال هدیه به‌صورت مقادیر واقعی و محدود در دیتابیس
    coins = user["coins"] + TESTER_GIFT_COINS
    xp, lvl, _, _ = game.add_xp(user["xp"], user["level"], TESTER_GIFT_XP)
    await _db.update_user(uid, coins=coins, xp=xp, level=lvl,
                          tester_granted=1)

    army = await _db.get_army(uid)
    for unit_key, count in {**TESTER_GIFT_ARMY, **TESTER_GIFT_DEFENSES}.items():
        await _db.set_unit(uid, unit_key, army.get(unit_key, 0) + count)
    for item_key, qty in TESTER_GIFT_ITEMS.items():
        await _db.inv_add(uid, item_key, qty)

    user = await _db.get_user(uid)
    return user


# ─────────────────────────────── آزمایش نبرد امن ─────────────────────────────
async def simulate_test_battle(attacker_id: int, defender_id: int) -> dict:
    """نبرد آزمایشی کاملاً امن — هیچ تغییری در دیتابیس ایجاد نمی‌کند.

    فقط دو ارتش را می‌خواند و شبیه‌سازی را گزارش می‌دهد تا مدیر بتواند
    تعادل بازی را بدون آسیب‌رساندن به بازیکنان بسنجد.
    """
    a = await _db.get_user(attacker_id)
    d = await _db.get_user(defender_id)
    if not a or not d:
        return {"ok": False, "reason": "یکی از بازیکنان وجود ندارد"}

    att_army = await _db.get_army(attacker_id)
    def_army = await _db.get_army(defender_id)
    def_struct = await _db.get_defenses(defender_id)

    if game.attack_power(att_army) <= 0:
        return {"ok": False, "reason": "مهاجم یگان تهاجمی ندارد"}

    res = game.simulate_battle(att_army, def_army, def_struct,
                               a["coins"], d["coins"],
                               def_base_level=d.get("level", 1))
    return {"ok": True, **res}
