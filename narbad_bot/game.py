"""منطق اصلی بازی «نبردگاه» — یگان‌ها، فرمول‌ها و شبیه‌ساز نبرد."""
from __future__ import annotations

import random
import time

# ---------------------------------------------------------------- ثابت‌ها
MAX_ENERGY = 100          # حداکثر انرژی
ENERGY_REGEN_SECONDS = 240  # هر ۴ دقیقه ۱ واحد انرژی
ATTACK_ENERGY_COST = 30   # هزینه انرژی هر حمله
START_COINS = 800         # سکه اولیه
START_SOLDIERS = 5        # سرباز اولیه
DAILY_BASE = 250          # پایه جایزه روزانه
SHIELD_COSTS = {6: 800, 24: 2500}   # هزینه سپر ۶ و ۲۴ ساعته
MAX_LOOT = 100_000        # سقف غنیمت هر نبرد

# ---------------------------------------------------------------- یگان‌ها
UNITS: dict[str, dict] = {
    "soldier": {"name": "سرباز",        "emoji": "🪖", "cost": 120,    "power": 10},
    "ranger":  {"name": "تکاور",        "emoji": "🔫", "cost": 320,    "power": 32},
    "tank":    {"name": "تانک",         "emoji": "🛡️", "cost": 800,    "power": 90},
    "heli":    {"name": "بالگرد جنگی",  "emoji": "🚁", "cost": 1_600,  "power": 185},
    "fighter": {"name": "جنگنده",       "emoji": "✈️", "cost": 3_200,  "power": 400},
    "missile": {"name": "موشک بالستیک", "emoji": "🚀", "cost": 6_000,  "power": 820},
    "drone":   {"name": "پهپاد تهاجمی", "emoji": "🛸", "cost": 11_000, "power": 1_600},
    "warship": {"name": "ناو جنگی",     "emoji": "🚢", "cost": 20_000, "power": 3_200},
    "bomber":  {"name": "بمب‌افکن",     "emoji": "💣", "cost": 36_000, "power": 6_000},
}

# ---------------------------------------------------------------- دفاعیات
DEFENSES: dict[str, dict] = {
    "wall":   {"name": "دیوار دفاعی",  "emoji": "🧱", "cost": 250,    "defense": 25},
    "castle": {"name": "قلعه",          "emoji": "🏰", "cost": 1_200,  "defense": 110},
    "tower":  {"name": "برج پدافندی",   "emoji": "🗼", "cost": 3_800,  "defense": 320},
    "radar":  {"name": "سامانه رادار",  "emoji": "📡", "cost": 10_000, "defense": 950},
}

SHOP = {**{f"u:{k}": v for k, v in UNITS.items()},
        **{f"d:{k}": v for k, v in DEFENSES.items()}}

# ---------------------------------------------------------------- درجات
RANKS = [
    (40, "ژنرال"), (30, "سرهنگ"), (20, "سرگرد"), (15, "سروان"),
    (10, "ستوان"), (5, "گروهبان"), (0, "سرباز"),
]


def rank_name(level: int) -> str:
    for need, name in RANKS:
        if level >= need:
            return name
    return "سرباز"


def xp_to_next(level: int) -> int:
    """تجربه لازم برای رفتن به سطح بعد."""
    return 100 + (level - 1) * 75


def add_xp(xp: int, level: int, amount: int) -> tuple[int, int, int, int]:
    """افزودن تجربه؛ خروجی: (xp جدید، سطح جدید، تعداد سطح‌ها، جایزه سکه)."""
    xp += max(0, amount)
    gained, reward = 0, 0
    while xp >= xp_to_next(level):
        xp -= xp_to_next(level)
        level += 1
        gained += 1
        reward += 150 + 50 * level
    return xp, level, gained, reward


# ---------------------------------------------------------------- انرژی
def effective_energy(user: dict) -> tuple[int, int]:
    """انرژی فعلی با احتساب بازتولید خودکار + زمان پایه جدید برای ذخیره."""
    now = int(time.time())
    energy, ts = user["energy"], user.get("energy_ts") or 0
    if energy >= MAX_ENERGY:
        return MAX_ENERGY, ts
    gained = (now - ts) // ENERGY_REGEN_SECONDS
    new_energy = min(MAX_ENERGY, energy + gained)
    if gained > 0:
        ts = ts + gained * ENERGY_REGEN_SECONDS
    return new_energy, ts


def daily_reward(level: int) -> int:
    return DAILY_BASE + level * 40


# ---------------------------------------------------------------- قدرت
def attack_power(army: dict[str, int]) -> int:
    """قدرت حمله = مجموع قدرت یگان‌های تهاجمی."""
    return sum(c * UNITS[u]["power"] for u, c in army.items() if u in UNITS)


def defense_power(army: dict[str, int], structures: dict[str, int]) -> int:
    """قدرت دفاع = یگان‌ها (۷۰٪ قدرت) + سازه‌های دفاعی."""
    unit_part = sum(c * UNITS[u]["power"] * 0.7 for u, c in army.items() if u in UNITS)
    struct_part = sum(c * DEFENSES[d]["defense"] for d, c in structures.items() if d in DEFENSES)
    return round(unit_part + struct_part)


# ---------------------------------------------------------------- نبرد
def simulate_battle(att_army: dict[str, int], def_army: dict[str, int],
                    def_struct: dict[str, int], att_coins: int,
                    def_coins: int, *, att_mult: float = 1.0,
                    def_mult: float = 1.0, loot_mult: float = 1.0,
                    xp_mult: float = 1.0, cas_mult: float = 1.0) -> dict:
    """شبیه‌سازی کامل یک نبرد. ورودی‌ها: ارتش مهاجم/مدافع، سازه‌های مدافع و سکه‌ها.

    att_mult/def_mult: ضریب قدرت (بافت‌ها)، loot_mult: ضریب غنیمت،
    xp_mult: ضریب تجربه، cas_mult: ضریب تلفات مهاجم (کیت تعمیر).
    """
    att_power = round(attack_power(att_army) * att_mult)
    def_power = round(defense_power(def_army, def_struct) * def_mult)

    a = att_power * random.uniform(0.85, 1.15)
    d = def_power * 1.2 * random.uniform(0.85, 1.15)  # مزیت دفاعی ۲۰٪
    att_wins = a >= d
    total = a + d

    # ---- تلفات (نسبتی به قدرت طرف مقابل)
    if att_wins:
        att_ratio = (d / total) * random.uniform(0.30, 0.55)
        def_ratio = (a / total) * random.uniform(0.45, 0.75)
    else:
        att_ratio = (d / total) * random.uniform(0.60, 0.95)
        def_ratio = (a / total) * random.uniform(0.30, 0.50)
    att_ratio *= cas_mult

    def _casualties(army: dict, ratio: float) -> dict[str, int]:
        out = {}
        for u, c in army.items():
            if c <= 0:
                continue
            loss = min(c, max(0, round(c * min(1.0, ratio))))
            if loss:
                out[u] = loss
        return out

    att_cas = _casualties(att_army, att_ratio)
    def_cas = _casualties(def_army, def_ratio)

    # ---- غنیمت سکه
    if att_wins:
        loot = min(MAX_LOOT, round(def_coins * random.uniform(0.18, 0.32) * loot_mult))
    else:
        loot = min(MAX_LOOT, round(att_coins * random.uniform(0.08, 0.18)))
    loot = max(0, loot)

    # ---- تجربه
    att_xp = min(1000, round((45 + def_power / 60) * xp_mult)) if att_wins else 15
    def_xp = min(1000, 45 + round(att_power / 60)) if not att_wins else 15

    return {
        "winner": "attacker" if att_wins else "defender",
        "att_power": att_power,
        "def_power": def_power,
        "att_cas": att_cas,
        "def_cas": def_cas,
        "loot": max(0, loot),
        "att_xp": att_xp,
        "def_xp": def_xp,
    }


# ---------------------------------------------------------------- ابزار قالب‌بندی
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

# نگاشت نمایشی برای همهٔ آیتم‌ها (یگان‌ها + سازه‌ها)
DISP: dict[str, dict] = {**UNITS, **DEFENSES}


def fa(value: int | float) -> str:
    """عدد با جداکنندهٔ هزارگان و ارقام فارسی."""
    if isinstance(value, float):
        value = int(round(value))
    return f"{value:,}".translate(_FA_DIGITS).replace(",", "٬")


def cas_text(casualties: dict[str, int]) -> str:
    """نمایش تلفات: 🪖×۳، 🚀×۱"""
    if not casualties:
        return "بدون تلفات"
    return "، ".join(
        f"{DISP[k]['emoji']}×{fa(c)}" for k, c in casualties.items()
    )


# ================================================================ مأموریت‌های روزانه
# هر مأموریت باید: emoji + name + target + coins + xp داشته باشد
MISSIONS: dict[str, dict] = {
    "attack3":   {"emoji": "⚔️", "name": "انجام ۳ حمله",                    "target": 3,    "coins": 500, "xp": 80},
    "win2":      {"emoji": "🏆", "name": "کسب ۲ پیروزی",                    "target": 2,    "coins": 700, "xp": 120},
    "buy5":      {"emoji": "🪖", "name": "آموزش ۵ یگان",                    "target": 5,    "coins": 450, "xp": 70},
    "spend2000": {"emoji": "💸", "name": "خرج ۲٬۰۰۰ سکه",                  "target": 2000, "coins": 650, "xp": 100},
    "mine1":     {"emoji": "⛏", "name": "جمع‌آوری معدن",                    "target": 1,    "coins": 500, "xp": 80},
    "donate500": {"emoji": "🏰", "name": "واریز ۵۰۰ سکه به خزانهٔ اتحادیه", "target": 500, "coins": 600, "xp": 90},
}


# ================================================================ استخراج منابع
MINE_RATE = 3          # سکه به ازای هر سرباز در ساعت
MINE_MAX_HOURS = 8     # حداکثر زمان استخراج
MINE_WORKER_CAP = 60   # حداکثر سرباز معدن‌چی


def mine_gain(workers: int, elapsed_seconds: float) -> int:
    """سکهٔ حاصل از استخراج: هر سرباز ۳ سکه در ساعت تا سقف ۸ ساعت."""
    hours = min(MINE_MAX_HOURS, max(0.0, elapsed_seconds / 3600))
    return int(workers * MINE_RATE * hours)


# ================================================================ آیتم‌های ویژه
ITEMS: dict[str, dict] = {
    "energy_pack": {"name": "بستهٔ انرژي‌زا",  "emoji": "⚡", "price": 900,
                    "kind": "instant", "value": 40,
                    "desc": "+۴۰ انرژی فوری"},
    "lucky":       {"name": "طلسم پیروزی",     "emoji": "🍀", "price": 3000,
                    "kind": "buff", "duration": 1800,
                    "desc": "+۲۰٪ قدرت حمله به مدت ۳۰ دقیقه"},
    "magnet":      {"name": "آهنربای غنیمت",   "emoji": "🧲", "price": 2200,
                    "kind": "buff", "duration": 1800,
                    "desc": "+۳۰٪ غنیمت سکه به مدت ۳۰ دقیقه"},
    "xp_boost":    {"name": "کتاب آموزش",      "emoji": "📚", "price": 1500,
                    "kind": "buff", "duration": 1800,
                    "desc": "+۵۰٪ تجربه به مدت ۳۰ دقیقه"},
    "repair":      {"name": "کیت تعمیر",       "emoji": "🛠", "price": 2500,
                    "kind": "consumable",
                    "desc": "در نبرد بعدی تلفاتت نصف می‌شود"},
    "tank_pack":   {"name": "جعبه تانک",       "emoji": "🛡️", "price": 3600,
                    "kind": "pack", "unit": "tank", "count": 5,
                    "desc": "۵ تانک — با ۱۰٪ تخفیف"},
    "rocket_pack": {"name": "جعبه موشک",       "emoji": "🚀", "price": 10800,
                    "kind": "pack", "unit": "missile", "count": 2,
                    "desc": "۲ موشک بالستیک — با ۱۰٪ تخفیف"},
}

BUFF_DURATION = 1800    # ۳۰ دقیقه
# ضریب‌های بافتی که در نبرد اعمال می‌شوند
BUFF_MULT = {"lucky": ("att_mult", 1.2), "magnet": ("loot_mult", 1.3),
             "xp_boost": ("xp_mult", 1.5)}


# ================================================================ قلمروهای نقشه
TERRITORIES_SEED = [
    ("fire",     "🔥 دشت آتش"),
    ("iron",     "⛰ تنگهٔ آهنین"),
    ("bay",      "🌊 خلیج نبرد"),
    ("mountain", "🏔 کوهستان سرد"),
    ("desert",   "🏜 بیابان سرخ"),
    ("harbor",   "⚓ بندرگاه مرکزی"),
]

TERR_ATTACK_ENERGY = 25   # انرژی لازم برای حمله به قلمرو
TERR_COOLDOWN = 30        # ثانیه بین حملات به قلمرو


def territory_hp(level: int) -> int:
    """سلامت قلمرو بر اساس سطح: ۱۵۰۰ × سطح^۱٫۵"""
    return int(1500 * (level ** 1.5) / 50) * 50


# ================================================================ جنگ اتحادیه‌ها
WAR_DURATION = 86400        # ۲۴ ساعت
WAR_START_COST = 3000       # هزینهٔ شروع جنگ از خزانه
WAR_TREASURY_CUT = 0.25     # سهم برنده از خزانهٔ بازنده
WAR_BONUS_XP = 150          # جایزهٔ عضویت برنده
WAR_BONUS_COINS = 250


def war_points(won: bool, att_power: int) -> int:
    """امتیاز جنگ: برنده ۱۲۰ + قدرت÷۳۰۰، بازنده ۳۰."""
    return 120 + att_power // 300 if won else 30
