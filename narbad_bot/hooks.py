"""هوک‌های فرعی بازی — اتصال رویدادها به مأموریت‌ها، جنگ اتحادیه و رشد."""
from __future__ import annotations

from . import game
from .db import DB

_db: DB | None = None


def setup(db: DB) -> None:
    global _db
    _db = db


# ---------------------------------------------------------------- مأموریت‌ها
async def bump_mission(user_id: int, key: str, amount: int = 1) -> None:
    if _db:
        await _db.bump_mission(user_id, key, amount)


async def after_purchase(user_id: int, units_bought: int, coins_spent: int) -> None:
    """بعد از هر خرید از فروشگاه/آموزشگاه."""
    await bump_mission(user_id, "buy5", units_bought)
    await bump_mission(user_id, "spend2000", coins_spent)


async def after_mine_claim(user_id: int) -> None:
    await bump_mission(user_id, "mine1", 1)


async def after_clan_deposit(user_id: int, amount: int) -> None:
    await bump_mission(user_id, "donate500", amount)


async def after_battle(user_id: int, won: bool) -> None:
    """بعد از هر نبرد."""
    await bump_mission(user_id, "attack3", 1)
    if won:
        await bump_mission(user_id, "win2", 1)


# ---------------------------------------------------------------- جنگ اتحادیه
async def process_war(att_id: int, def_id: int, att_won: bool,
                      att_power: int, loot: int) -> tuple[str | None, str | None]:
    """اگر دو طرف در جنگ اتحادیه باشند، امتیاز ثبت می‌شود.

    خروجی: (پیام برای مهاجم، پیام برای مدافع) — یا None اگر جنگ فعال نباشد.
    """
    if not _db:
        return None, None
    a = await _db.get_user(att_id)
    d = await _db.get_user(def_id)
    if not a or not d or not a.get("clan_id") or not d.get("clan_id"):
        return None, None
    if a["clan_id"] == d["clan_id"]:
        return None, None

    war = await _db.active_war_for_clan(a["clan_id"])
    if not war:
        return None, None
    if war["clan_a"] not in (a["clan_id"], d["clan_id"]) or \
       war["clan_b"] not in (a["clan_id"], d["clan_id"]):
        return None, None

    pts = game.war_points(att_won, att_power)
    side_a = "A" if war["clan_a"] == a["clan_id"] else "B"
    side_d = "A" if war["clan_a"] == d["clan_id"] else "B"
    await _db.add_war_points(war["id"], side_a, pts)
    await _db.add_war_points(war["id"], side_d, game.war_points(not att_won, att_power))

    return (
        f"🏰 امتیاز جنگ اتحادیهٔ تو: <b>+{game.fa(pts)}</b>",
        f"🏰 امتیاز جنگ اتحادیهٔ تو: <b>+{game.fa(game.war_points(not att_won, att_power))}</b>",
    )


# ---------------------------------------------------------------- رشد
async def snapshot_growth(user_id: int, power: int) -> None:
    if _db:
        await _db.growth_snapshot(user_id, power)


# ---------------------------------------------------------------- جایزهٔ مأموریت
async def claim_mission_rewards(user_id: int, key: str) -> tuple[int, int] | None:
    """ادعای جایزهٔ مأموریت؛ خروجی: (سکه، تجربه) یا None.

    اتمی است: اگر مأموریت کامل نباشد یا قبلاً گرفته شده باشد None
    برمی‌گرداند و جایزه‌ای داده نمی‌شود. (جلوگیری از جایزهٔ دوباره)
    """
    if not _db:
        return None
    spec = game.MISSIONS.get(key)
    if not spec:
        return None
    # ثبت اتمی ادعا (UPDATE ... WHERE claimed=0 AND progress>=target)
    if not await _db.claim_mission_atomic(user_id, key, spec["target"]):
        return None
    u = await _db.get_user(user_id)
    if not u:
        return None
    xp, lvl, gained, bonus = game.add_xp(u["xp"], u["level"], spec["xp"])
    total_coins = spec["coins"] + (bonus if gained else 0)
    await _db.update_user(user_id, coins=u["coins"] + total_coins, xp=xp, level=lvl)
    return total_coins, spec["xp"]
