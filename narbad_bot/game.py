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
# ساختار نوین ارتش: یگان‌های زمینی (نیازمند آموزش زمان‌دار) + تجهیزات نظامی (خرید فوری)
# • train_sec: زمان آموزش هر نفر (فقط یگان‌های زمینی)
# • desc: توضیح کوتاه برای فروشگاه/پرشگاه یگان
UNITS: dict[str, dict] = {
    "soldier":  {"name": "سرباز",        "emoji": "🪖", "cost": 50,     "power": 10,
                 "train_sec": 4,  "desc": "پیاده‌نظام پایه؛ ارزان و سریع در آموزش، ستون اصلی هر ارتش"},
    "commando": {"name": "کماندو",       "emoji": "⚔️", "cost": 250,    "power": 50,
                 "train_sec": 20, "desc": "نیروی ویژه؛ ۵ برابر سرباز قدرت آتش دارد"},
    "tank":     {"name": "تانک",         "emoji": "🛡️", "cost": 800,    "power": 90,
                 "desc": "زره‌پوش سنگین؛ می‌شکند خطوط دفاعی حریف"},
    "missile":  {"name": "موشک بالستیک", "emoji": "🚀", "cost": 6_000,  "power": 820,
                 "desc": "ضربهٔ دوربرد ویرانگر؛ بدون نیاز به حضور در میدان"},
    "warship":  {"name": "ناو جنگی",     "emoji": "🚢", "cost": 20_000, "power": 3_200,
                 "desc": "غول دریاها؛ آتش پشتیبانی فراساحلی بی‌رحم"},
    "fighter":  {"name": "جنگنده",       "emoji": "✈️", "cost": 3_200,  "power": 400,
                 "desc": "برتری هوایی؛ سریع، چابک و مرگبار"},
    "bomber":   {"name": "بمب‌افکن",     "emoji": "💣", "cost": 36_000, "power": 6_000,
                 "desc": "قوی‌ترین یگان نبردگاه؛ بارِ انفجاری سنگین"},
    "drone":    {"name": "پهپاد تهاجمی", "emoji": "🛩", "cost": 11_000, "power": 1_600,
                 "desc": "شکارچی بی‌سرنشین؛ دقیق، تاب‌آور و بی‌رحم"},
    "heli":     {"name": "بالگرد جنگی",  "emoji": "🚁", "cost": 1_600,  "power": 185,
                 "desc": "پشتیبانی نزدیک هوایی؛ شکار زره‌پوش‌ها"},
}

# یگان‌های زمینی: از «پادگان آموزش» با زمان‌بندی ساخته می‌شوند
GROUND_UNITS: tuple[str, ...] = ("soldier", "commando")
# تجهیزات نظامی: از فروشگاه، خرید فوری (بدون زمان آموزش)
EQUIPMENT_UNITS: tuple[str, ...] = ("tank", "missile", "warship", "fighter",
                                    "bomber", "drone", "heli")
TRAIN_MAX_QTY = 500  # سقف تعداد در هر سفارش خرید / آموزش

# ---------------------------------------------------------------- دفاعیات
# ساختار نوین سامانه دفاعی پایگاه: ۴ سازه تخصصی با قابلیت ارتقای سطح و تعمیر خسارت
# • defense: قدرت پایه دفاع در سطح ۱
# • cost: هزینه احداث اولیه (سطح ۱)
# • desc: توضیح تاکتیکی سازه
DEFENSES: dict[str, dict] = {
    "wall": {
        "name": "دیوار دفاعی",
        "emoji": "🧱",
        "cost": 300,
        "defense": 30,
        "desc": "سپر بتنی مستحکم پایگاه؛ جذب ضربات سنگین دشمن و کاهش تلفات",
    },
    "tower": {
        "name": "برج دفاعی",
        "emoji": "🗼",
        "cost": 1_200,
        "defense": 120,
        "desc": "برج دیده‌بانی و آتش سنگین پدافندی علیه مهاجمان زمینی",
    },
    "air_defense": {
        "name": "سامانه پدافند هوایی",
        "emoji": "🚀",
        "cost": 4_500,
        "defense": 450,
        "desc": "سامانه موشکی رهگیر برای انهدام جنگنده‌ها و بمب‌افکن‌های دشمن",
    },
    "radar": {
        "name": "سامانه رادار",
        "emoji": "📡",
        "cost": 10_000,
        "defense": 1_000,
        "desc": "رادار آرایه‌فازی پیشرفته برای کشف زودهنگام و هدایت پدافند",
    },
}

DEFENSE_KEYS: tuple[str, ...] = ("wall", "tower", "air_defense", "radar")

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


# ---------------------------------------------------------------- قدرت و دفاعیات
def attack_power(army: dict[str, int]) -> int:
    """قدرت حمله = مجموع قدرت یگان‌های تهاجمی."""
    return sum(c * UNITS[u]["power"] for u, c in army.items() if u in UNITS)


def struct_defense_power(key: str, level: int, health: int = 100) -> int:
    """قدرت دفاعی یک سازه بر اساس سطح و درصد سلامت."""
    if key not in DEFENSES or level <= 0:
        return 0
    base_def = DEFENSES[key]["defense"]
    # هر سطح بالاتر از ۱، ۶۰٪ به قدرت پایه می‌افزاید: سطح ۱ = ۱۰۰٪، سطح ۲ = ۱۶۰٪، سطح ۳ = ۲۲۰٪ ...
    power_at_level = base_def * (1 + 0.6 * (level - 1))
    # سلامت کمتر از ۱۰۰٪ به همان نسبت قدرت دفاعی مؤثر را کاهش می‌دهد
    eff_health = max(0, min(100, health)) / 100.0
    return round(power_at_level * eff_health)


def struct_upgrade_cost(key: str, current_level: int) -> int:
    """هزینه ارتقای سازه از سطح فعلی به سطح بعدی."""
    if key not in DEFENSES or current_level <= 0:
        return 0
    base_cost = DEFENSES[key]["cost"]
    # هزینه با هر سطح ۱٫۵ برابر می‌شود
    return round(base_cost * (1.5 ** current_level))


def struct_repair_cost(key: str, level: int, health: int) -> int:
    """هزینه تعمیر سازه و رساندن سلامت به ۱۰۰٪."""
    if key not in DEFENSES or level <= 0 or health >= 100:
        return 0
    base_cost = DEFENSES[key]["cost"]
    missing = max(0, 100 - health)
    cost_per_pct = max(1, round(base_cost * 0.002 * level))
    return max(10, round(cost_per_pct * missing))


def defense_power(army: dict[str, int], structures: dict | None = None,
                  base_level: int = 1) -> int:
    """قدرت کل دفاع = یگان‌های ارتش (۷۰٪ قدرت) + سازه‌های دفاعی + پاداش سطح پایگاه."""
    structures = structures or {}
    unit_part = sum(c * UNITS[u]["power"] * 0.7 for u, c in army.items() if u in UNITS)

    struct_part = 0
    for k, val in structures.items():
        if isinstance(val, dict):
            lvl = val.get("level", 0)
            hlth = val.get("health", 100)
            struct_part += struct_defense_power(k, lvl, hlth)
        elif isinstance(val, (int, float)) and val > 0:
            if k in DEFENSES:
                struct_part += struct_defense_power(k, int(val), 100)
            elif k == "castle":
                # سازگاری با کدهای تستی پیشین
                struct_part += struct_defense_power("air_defense", int(val), 100)

    base_bonus = max(0, (base_level - 1) * 15)
    return round(unit_part + struct_part + base_bonus)


# ---------------------------------------------------------------- نبرد
def simulate_battle(att_army: dict[str, int], def_army: dict[str, int],
                    def_struct: dict | None, att_coins: int,
                    def_coins: int, *, def_base_level: int = 1,
                    att_mult: float = 1.0, def_mult: float = 1.0,
                    loot_mult: float = 1.0, xp_mult: float = 1.0,
                    cas_mult: float = 1.0) -> dict:
    """شبیه‌سازی کامل یک نبرد. ورودی‌ها: ارتش مهاجم/مدافع، سازه‌های مدافع و سکه‌ها."""
    def_struct = def_struct or {}
    att_power = round(attack_power(att_army) * att_mult)
    def_power = round(defense_power(def_army, def_struct, base_level=def_base_level) * def_mult)

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
