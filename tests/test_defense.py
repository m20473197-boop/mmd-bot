"""تست‌های جامع سامانه نوین پدافند و دفاع پایگاه (handlers_defense) —

پوشش داده‌شده:
  • ساختار سازه‌های دفاعی (۴ سازه: دیوار، برج، پدافند هوایی، رادار)
  • فرمول‌های قدرت دفاعی سازه‌ها، هزینه ارتقا و هزینه تعمیر
  • عملیات دیتابیس (get_defenses, set_defense, upgrade_defense, damage_defenses, repair_defense)
  • مایگریشن سازه‌های قدیمی از جدول army به جدول defenses (تبدیل قلعه به پدافند هوایی)
  • جریان‌های کامل ۵ صفحه منوی دفاع:
    ۱) 🏰 دفاع پایگاه من (My Base Defense)
    ۲) 🛒 خرید تجهیزات دفاعی (Buy Defense Equipment)
    ۳) ⬆️ ارتقای دفاع (Upgrade Defense)
    ۴) 🔧 تعمیر دفاع (Repair Defense)
    ۵) 📊 گزارش دفاع (Defense Report)
  • نبرد و آسیب‌پذیری سازه‌ها (کاهش قدرت در اثر خسارت نبرد، بازیابی قدرت پس از تعمیر)
"""
import os
import tempfile
import time
import unittest

from narbad_bot import admin_core, game, handlers_defense, hooks
from narbad_bot.db import DB


# ─────────────────────────────────────────────────────────── اشیای تقلبی
class FakeUser:
    is_bot = False

    def __init__(self, uid: int, first_name="فرمانده", username="defender"):
        self.id = uid
        self.first_name = first_name
        self.username = username


class FakeMessage:
    def __init__(self, user: FakeUser):
        self.from_user = user
        self.text = None
        self.sent: list[tuple[str, dict]] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.sent.append((text, kwargs))


class FakeCallbackMessage(FakeMessage):
    def __init__(self, user: FakeUser):
        super().__init__(user)
        self.edited: list[tuple[str, dict]] = []

    async def edit_text(self, text: str, **kwargs) -> None:
        self.edited.append((text, kwargs))


class FakeCallback:
    def __init__(self, data: str, user: FakeUser):
        self.data = data
        self.from_user = user
        self.message = FakeCallbackMessage(user)
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text=None, show_alert=False, **kwargs) -> None:
        self.answers.append((text, show_alert))


# ─────────────────────────────────────────────────────────── ساختار و فرمول‌ها
class TestDefenseRosterAndFormulas(unittest.TestCase):
    def test_four_defense_structures(self):
        self.assertEqual(len(game.DEFENSES), 4)
        self.assertEqual(set(game.DEFENSES), {"wall", "tower", "air_defense", "radar"})
        self.assertEqual(game.DEFENSE_KEYS, ("wall", "tower", "air_defense", "radar"))

    def test_defense_fields_complete(self):
        for key, info in game.DEFENSES.items():
            for field in ("name", "emoji", "cost", "defense", "desc"):
                self.assertIn(field, info, f"{key}.{field}")
                self.assertTrue(info[field])
            self.assertGreater(info["cost"], 0)
            self.assertGreater(info["defense"], 0)

    def test_struct_defense_power_levels(self):
        # دیوار: پایه ۳۰؛ سطح ۱ = ۳۰، سطح ۲ = ۳۰ × ۱٫۶ = ۴۸، سطح ۳ = ۳۰ × ۲٫۲ = ۶۶
        self.assertEqual(game.struct_defense_power("wall", 1, 100), 30)
        self.assertEqual(game.struct_defense_power("wall", 2, 100), 48)
        self.assertEqual(game.struct_defense_power("wall", 3, 100), 66)
        self.assertEqual(game.struct_defense_power("wall", 0, 100), 0)

    def test_struct_defense_power_health_scaling(self):
        # سطح ۲ (۴۸) با ۵۰٪ سلامت → ۲۴
        self.assertEqual(game.struct_defense_power("wall", 2, 50), 24)
        # ۰٪ سلامت → ۰
        self.assertEqual(game.struct_defense_power("wall", 2, 0), 0)
        # ۷۵٪ سلامت
        self.assertEqual(game.struct_defense_power("wall", 2, 75), 36)

    def test_struct_upgrade_cost_progression(self):
        # دیوار: پایه ۳۰۰؛ سطح ۱->۲ = ۴۵۰، سطح ۲->۳ = ۶۷۵
        self.assertEqual(game.struct_upgrade_cost("wall", 1), 450)
        self.assertEqual(game.struct_upgrade_cost("wall", 2), 675)
        # برج: پایه ۱۲۰۰؛ سطح ۱->۲ = ۱۸۰۰
        self.assertEqual(game.struct_upgrade_cost("tower", 1), 1800)

    def test_struct_repair_cost_formula(self):
        # دیوار سطح ۱، سلامت ۷۰٪ (۳۰٪ خسارت):
        # cost_per_pct = round(300 * 0.002 * 1) = 1 → 30 * 1 = 30 (حداقل ۱۰)
        cost = game.struct_repair_cost("wall", 1, 70)
        self.assertGreater(cost, 0)
        # بدون خسارت (۱۰۰٪) → ۰
        self.assertEqual(game.struct_repair_cost("wall", 1, 100), 0)
        # سطح ۲ هزینه تعمیر بیشتری نسبت به سطح ۱ دارد
        cost_l2 = game.struct_repair_cost("wall", 2, 70)
        self.assertGreaterEqual(cost_l2, cost)

    def test_total_defense_power_combines_all(self):
        army = {"soldier": 10}  # ۱۰ × ۱۰ × ۰٫۷ = ۷۰
        defs = {
            "wall": {"level": 1, "health": 100},         # ۳۰
            "tower": {"level": 2, "health": 100},        # ۱۲۰ × ۱٫۶ = ۱۹۲
            "radar": {"level": 1, "health": 50},         # ۱۰۰۰ × ۰٫۵ = ۵۰۰
        }
        # base_level 1 → base_bonus 0
        total = game.defense_power(army, defs, base_level=1)
        self.assertEqual(total, 70 + 30 + 192 + 500)
        # base_level 3 → +30 پاداش بستر پایگاه
        total_lvl3 = game.defense_power(army, defs, base_level=3)
        self.assertEqual(total_lvl3, total + 30)


# ─────────────────────────────────────────────────────────── دیتابیس و مهاجرت
class TestDefenseDB(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DB(os.path.join(tempfile.mkdtemp(), "test_def.db"))
        await self.db.init()

    async def asyncTearDown(self):
        await self.db.close()

    async def test_set_and_get_defenses(self):
        await self.db.ensure_user(1, "ali", "علی")
        await self.db.set_defense(1, "wall", 1, 100)
        await self.db.set_defense(1, "tower", 2, 85)
        defs = await self.db.get_defenses(1)
        self.assertEqual(defs["wall"], {"level": 1, "health": 100})
        self.assertEqual(defs["tower"], {"level": 2, "health": 85})

    async def test_upgrade_defense_db(self):
        await self.db.ensure_user(2, "reza", "رضا")
        await self.db.set_defense(2, "wall", 1, 80)
        new_lvl = await self.db.upgrade_defense(2, "wall")
        self.assertEqual(new_lvl, 2)
        d = await self.db.get_defense_structure(2, "wall")
        self.assertEqual(d["level"], 2)
        self.assertEqual(d["health"], 100)  # ارتقا سلامت را ۱۰۰ می‌کند

    async def test_damage_and_repair_defenses_db(self):
        await self.db.ensure_user(3, "sara", "سارا")
        await self.db.set_defense(3, "wall", 1, 100)
        await self.db.set_defense(3, "tower", 1, 100)
        
        # خسارت ۲۰٪
        damaged = await self.db.damage_defenses(3, 20)
        self.assertEqual(damaged["wall"], 80)
        self.assertEqual(damaged["tower"], 80)

        # تعمیر تک‌سازه
        await self.db.repair_defense(3, "wall")
        defs = await self.db.get_defenses(3)
        self.assertEqual(defs["wall"]["health"], 100)
        self.assertEqual(defs["tower"]["health"], 80)

        # تعمیر همه‌جانبه
        await self.db.repair_defense(3, None)
        defs = await self.db.get_defenses(3)
        self.assertEqual(defs["tower"]["health"], 100)

    async def test_migrate_old_army_defenses(self):
        # شبیه‌سازی دیتابیس قدیمی که سازه‌ها در جدول army ذخیره شده بودند
        await self.db.ensure_user(5, "old_p", "قدیمی")
        await self.db._execute("INSERT OR REPLACE INTO army (user_id, unit, count) VALUES (5, 'wall', 2)")
        await self.db._execute("INSERT OR REPLACE INTO army (user_id, unit, count) VALUES (5, 'castle', 1)")
        await self.db.close()

        # بازگشایی دیتابیس برای اجرای مایگریشن
        self.db = DB(self.db.path)
        await self.db.init()

        defs = await self.db.get_defenses(5)
        self.assertEqual(defs["wall"]["level"], 2)
        self.assertEqual(defs["air_defense"]["level"], 1)  # قلعه به پدافند هوایی تبدیل شد
        self.assertEqual(defs["wall"]["health"], 100)

    async def test_reset_player_clears_defenses(self):
        await self.db.ensure_user(6, "rst", "ریستی")
        await self.db.set_defense(6, "radar", 3, 100)
        await self.db.reset_player(6)
        defs = await self.db.get_defenses(6)
        self.assertEqual(defs, {})


# ─────────────────────────────────────────────────────────── جریان‌های UI
class TestDefenseFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DB(os.path.join(tempfile.mkdtemp(), "def_flow.db"))
        await self.db.init()
        hooks.setup(self.db)
        admin_core.setup(self.db)
        handlers_defense.setup(self.db)
        self.user = await self.db.ensure_user(10, "general", "فرمانده کل")
        self.fu = FakeUser(10, "فرمانده کل", "general")

    async def asyncTearDown(self):
        await self.db.close()

    # --- صفحه فرود دفاع: دکمه‌ها و اطلاعات
    async def test_on_defense_reply_button(self):
        msg = FakeMessage(self.fu)
        await handlers_defense.on_defense(msg)
        self.assertTrue(msg.sent)
        text = msg.sent[0][0]
        self.assertIn("سامانه دفاعی پایگاه", text)
        kb_json = msg.sent[0][1]["reply_markup"].model_dump_json()
        self.assertIn("defense:my", kb_json)
        self.assertIn("defense:buy", kb_json)
        self.assertIn("defense:upgrade", kb_json)
        self.assertIn("defense:repair", kb_json)
        self.assertIn("defense:report", kb_json)

    # --- 1) 🏰 دفاع پایگاه من
    async def test_my_defense_page(self):
        await self.db.set_defense(10, "wall", 1, 100)
        await self.db.set_defense(10, "tower", 2, 100)
        cb = FakeCallback("defense:my", self.fu)
        await handlers_defense.cb_defense_my(cb)
        text = cb.message.edited[0][0]
        self.assertIn("دفاع پایگاه من", text)
        self.assertIn("دیوار دفاعی", text)
        self.assertIn("برج دفاعی", text)
        self.assertIn("سطح پایگاه", text)
        self.assertIn("مجموع کل قدرت دفاعی پایگاه", text)

    # --- 2) 🛒 خرید تجهیزات دفاعی
    async def test_buy_defense_view_and_purchase_flow(self):
        # بررسی صفحه فروشگاه
        cb = FakeCallback("defense:buy", self.fu)
        await handlers_defense.cb_defense_buy(cb)
        self.assertTrue(cb.message.edited)
        
        # انتخاب دیوار برای احداث
        cb_view = FakeCallback("defense:buyview:wall", self.fu)
        await handlers_defense.cb_defense_buyview(cb_view)
        text = cb_view.message.edited[0][0]
        self.assertIn("احداث دیوار دفاعی", text)
        self.assertIn(game.fa(300), text)

        # تأیید خرید
        before_coins = (await self.db.get_user(10))["coins"]
        cb_conf = FakeCallback("defense:buyconf:wall", self.fu)
        await handlers_defense.cb_defense_buyconf(cb_conf)
        
        # بررسی کسر سکه و ثبت در دیتابیس
        after_user = await self.db.get_user(10)
        self.assertEqual(after_user["coins"], before_coins - 300)
        defs = await self.db.get_defenses(10)
        self.assertEqual(defs["wall"]["level"], 1)
        self.assertEqual(defs["wall"]["health"], 100)

        # بررسی پیشرفت مأموریت خرج سکه
        rows = await self.db.missions_today(10)
        self.assertEqual(rows["spend2000"]["progress"], 300)

        # خرید دوبارهٔ سازه موجود باید هشدار دهد
        cb_double = FakeCallback("defense:buyconf:wall", self.fu)
        await handlers_defense.cb_defense_buyconf(cb_double)
        self.assertIn("قبلاً احداث شده", cb_double.answers[0][0])

    async def test_buy_insufficient_funds(self):
        # کاهش سکه
        await self.db.update_user(10, coins=50)
        cb = FakeCallback("defense:buyconf:radar", self.fu)  # هزینه ۱۰٬۰۰۰
        await handlers_defense.cb_defense_buyconf(cb)
        self.assertIn("سکه کافی نداری", cb.answers[0][0])
        self.assertNotIn("radar", await self.db.get_defenses(10))

    # --- 3) ⬆️ ارتقای دفاع
    async def test_upgrade_defense_flow(self):
        await self.db.set_defense(10, "wall", 1, 100)
        await self.db.update_user(10, coins=5000)

        # صفحه ارتقا
        cb_up = FakeCallback("defense:upgrade", self.fu)
        await handlers_defense.cb_defense_upgrade(cb_up)
        self.assertTrue(cb_up.message.edited)

        # انتخاب سازه برای ارتقا
        cb_view = FakeCallback("defense:upview:wall", self.fu)
        await handlers_defense.cb_defense_upview(cb_view)
        text = cb_view.message.edited[0][0]
        self.assertIn("ارتقای دیوار دفاعی", text)
        self.assertIn(game.fa(450), text)  # هزینه ارتقا سطح ۱ به ۲

        # تأیید ارتقا
        cb_done = FakeCallback("defense:updone:wall", self.fu)
        await handlers_defense.cb_defense_updone(cb_done)
        
        # بررسی سطح جدید و کسر سکه
        u = await self.db.get_user(10)
        self.assertEqual(u["coins"], 5000 - 450)
        d = await self.db.get_defense_structure(10, "wall")
        self.assertEqual(d["level"], 2)
        self.assertEqual(d["health"], 100)

    # --- 4) 🔧 تعمیر دفاع
    async def test_repair_defense_flow(self):
        await self.db.set_defense(10, "wall", 1, 70)
        await self.db.set_defense(10, "tower", 1, 80)
        await self.db.update_user(10, coins=2000)

        # صفحه تعمیرات
        cb = FakeCallback("defense:repair", self.fu)
        await handlers_defense.cb_defense_repair(cb)
        text = cb.message.edited[0][0]
        self.assertIn("تعمیر و بازسازی", text)
        self.assertIn("۷۰٪", text)

        # تعمیر تک‌سازه (دیوار)
        cb_rep_wall = FakeCallback("defense:repdone:wall", self.fu)
        await handlers_defense.cb_defense_repdone(cb_rep_wall)
        defs = await self.db.get_defenses(10)
        self.assertEqual(defs["wall"]["health"], 100)
        self.assertEqual(defs["tower"]["health"], 80)

        # تعمیر همه سازه‌ها
        cb_rep_all = FakeCallback("defense:repdone:all", self.fu)
        await handlers_defense.cb_defense_repdone(cb_rep_all)
        defs2 = await self.db.get_defenses(10)
        self.assertEqual(defs2["tower"]["health"], 100)

    # --- 5) 📊 گزارش دفاع
    async def test_defense_report_page(self):
        await self.db.set_defense(10, "air_defense", 1, 100)
        # ثبت یک نبرد دفاعی
        await self.db.log_battle(int(time.time()), 99, 10, 10, 0, 500, 800,
                                 "❌ شکست مقابل مدافع", "🛡 دفع حملهٔ دشمن")
        cb = FakeCallback("defense:report", self.fu)
        await handlers_defense.cb_defense_report(cb)
        text = cb.message.edited[0][0]
        self.assertIn("گزارش جامع پدافند پایگاه", text)
        self.assertIn("سامانه پدافند", text)
        self.assertIn("دفع حملهٔ دشمن", text)


# ─────────────────────────────────────────────────────────── اتصال به نبرد
class TestDefenseBattleIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DB(os.path.join(tempfile.mkdtemp(), "def_battle.db"))
        await self.db.init()
        self.att = await self.db.ensure_user(20, "attacker", "مهاجم")
        self.defender = await self.db.ensure_user(30, "defender", "مدافع")

    async def asyncTearDown(self):
        await self.db.close()

    async def test_battle_damages_defender_structures(self):
        # مدافع دارای دیوار و برج با سلامت ۱۰۰٪
        await self.db.set_defense(30, "wall", 2, 100)
        await self.db.set_defense(30, "tower", 1, 100)
        
        # اعمال خسارت ۲۰٪ (شبیه پایان یک نبرد)
        await self.db.damage_defenses(30, 20)
        
        defs = await self.db.get_defenses(30)
        self.assertEqual(defs["wall"]["health"], 80)
        self.assertEqual(defs["tower"]["health"], 80)

        # قدرت دفاعی مؤثر باید به دلیل خسارت کاهش یافته باشد
        pwr_damaged = game.defense_power({}, defs, base_level=1)
        pwr_healthy = game.defense_power({}, {"wall": {"level": 2, "health": 100},
                                              "tower": {"level": 1, "health": 100}}, base_level=1)
        self.assertLess(pwr_damaged, pwr_healthy)

        # تعمیر سلامت را به ۱۰۰٪ و قدرت را به اوج برمی‌گرداند
        await self.db.repair_defense(30, None)
        defs_repaired = await self.db.get_defenses(30)
        pwr_restored = game.defense_power({}, defs_repaired, base_level=1)
        self.assertEqual(pwr_restored, pwr_healthy)


if __name__ == "__main__":
    unittest.main()
