"""تست‌های کامل سیستم توسعه/مدیریت: admins.py، admin_core.py و admin_panel.py.

اصول مورد آزمون:
    • اختیارات داینامیک (هیچ مقدار بی‌نهایتی در دیتابیس نوشته نمی‌شود)
    • بازیکنان عادی تحت تأثیر قرار نمی‌گیرند
    • پنل /admin فقط برای DEVELOPER_IDS
    • هدیهٔ تست‌کننده فقط یک‌بار (tester_granted)
    • ریست حساب تست همه‌چیز را برمی‌گرداند
"""
import asyncio
import os
import tempfile
import unittest

from narbad_bot import admin_core, admin_panel, admins, game
from narbad_bot.db import DB

DEV_ID = admins.DEVELOPER_IDS[0]
TST_ID = admins.TESTER_IDS[0]
NORMAL_ID = 555_555_555


# ─────────────────────────────── تست‌های پیکربندی ────────────────────────────
class TestAdminsConfig(unittest.TestCase):
    def test_developer_detection(self):
        self.assertTrue(admins.is_developer(DEV_ID))
        self.assertFalse(admins.is_developer(NORMAL_ID))
        self.assertFalse(admins.is_developer(TST_ID))

    def test_tester_detection(self):
        self.assertTrue(admins.is_tester(TST_ID))
        self.assertFalse(admins.is_tester(NORMAL_ID))
        self.assertFalse(admins.is_tester(DEV_ID))

    def test_privileged_union(self):
        self.assertTrue(admins.is_privileged(DEV_ID))
        self.assertTrue(admins.is_privileged(TST_ID))
        self.assertFalse(admins.is_privileged(NORMAL_ID))

    def test_ids_are_ints(self):
        for uid in admins.DEVELOPER_IDS + admins.TESTER_IDS:
            self.assertIsInstance(uid, int)
            self.assertGreater(uid, 0)


# ─────────────────────────────── تست‌های هستهٔ اختیارات ──────────────────────
class TestAdminCore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DB(os.path.join(tempfile.mkdtemp(), "admin.db"))
        await self.db.init()
        admin_core.setup(self.db)

    async def asyncTearDown(self):
        await self.db.close()

    # --- سکه: داینامیک، بدون ذخیرهٔ بی‌نهایت
    async def test_dev_pay_never_deducts(self):
        dev = await self.db.ensure_user(DEV_ID)
        before = dev["coins"]
        ok = await admin_core.pay(dev, 999_999)
        self.assertTrue(ok)
        after = await self.db.get_user(DEV_ID)
        self.assertEqual(after["coins"], before)   # هیچ کسری در دیتابیس

    async def test_normal_pay_deducts(self):
        u = await self.db.ensure_user(NORMAL_ID)
        ok = await admin_core.pay(u, 300)
        self.assertTrue(ok)
        self.assertEqual((await self.db.get_user(NORMAL_ID))["coins"],
                         game.START_COINS - 300)
        # ناکافی → False و بدون تغییر
        ok = await admin_core.pay(await self.db.get_user(NORMAL_ID), 10**9)
        self.assertFalse(ok)
        self.assertEqual((await self.db.get_user(NORMAL_ID))["coins"],
                         game.START_COINS - 300)

    async def test_display_infinite_not_stored(self):
        dev = await self.db.ensure_user(DEV_ID)
        self.assertEqual(admin_core.coins_display(dev), "∞")
        self.assertEqual((await self.db.get_user(DEV_ID))["coins"],
                         game.START_COINS)  # دیتابیس دست‌نخورده

    # --- انرژی: بدون کسر برای مدیر
    async def test_dev_energy_unlimited_no_deduct(self):
        dev = await self.db.ensure_user(DEV_ID)
        self.assertTrue(admin_core.can_pay_energy(dev, 999))
        self.assertTrue(await admin_core.try_spend_energy(dev, 999))
        self.assertEqual((await self.db.get_user(DEV_ID))["energy"],
                         game.MAX_ENERGY)

    async def test_normal_energy_deducts(self):
        u = await self.db.ensure_user(NORMAL_ID)
        self.assertTrue(await admin_core.try_spend_energy(u, 30))
        self.assertEqual((await self.db.get_user(NORMAL_ID))["energy"],
                         game.MAX_ENERGY - 30)
        self.assertFalse(admin_core.can_pay_energy(
            await self.db.get_user(NORMAL_ID), 30 + 41))

    async def test_tester_xp_multiplier(self):
        self.assertEqual(admin_core.xp_multiplier(TST_ID), 2.0)
        self.assertEqual(admin_core.xp_multiplier(DEV_ID), 1.0)
        self.assertEqual(admin_core.xp_multiplier(NORMAL_ID), 1.0)

    async def test_no_cooldown_for_privileged(self):
        self.assertTrue(admin_core.no_cooldown(DEV_ID))
        self.assertTrue(admin_core.no_cooldown(TST_ID))
        self.assertFalse(admin_core.no_cooldown(NORMAL_ID))

    # --- هدیهٔ تست‌کننده: فقط یک‌بار
    async def test_tester_gift_applied_once(self):
        t = await self.db.ensure_user(TST_ID)
        self.assertEqual(t["tester_granted"], 1)
        coins_after = t["coins"]
        self.assertGreater(coins_after, game.START_COINS)
        self.assertGreater(t["level"], 1)
        # ثبت‌نام دوباره → هدیهٔ تکراری نمی‌گیرد
        t2 = await self.db.ensure_user(TST_ID)
        self.assertEqual(t2["coins"], coins_after)

    async def test_tester_gift_units_and_items(self):
        await self.db.ensure_user(TST_ID)
        army = await self.db.get_army(TST_ID)
        self.assertGreaterEqual(army.get("tank", 0),
                                admin_core.TESTER_GIFT_ARMY["tank"])
        self.assertGreaterEqual(army.get("wall", 0),
                                admin_core.TESTER_GIFT_DEFENSES["wall"])
        inv = await self.db.inv_get(TST_ID)
        self.assertGreaterEqual(inv.get("energy_pack", 0), 3)

    async def test_normal_player_gets_no_gift(self):
        u = await self.db.ensure_user(NORMAL_ID)
        self.assertEqual(u["tester_granted"], 0)
        self.assertEqual(u["coins"], game.START_COINS)
        army = await self.db.get_army(NORMAL_ID)
        self.assertEqual(army, {"soldier": 5})

    # --- نبرد آزمایشی: بدون هیچ تغییری در دیتابیس
    async def test_test_battle_is_read_only(self):
        a = await self.db.ensure_user(TST_ID)
        b = await self.db.ensure_user(NORMAL_ID)
        await self.db.set_unit(TST_ID, "tank", 10)
        await self.db.set_unit(NORMAL_ID, "soldier", 5)
        await self.db.set_unit(NORMAL_ID, "wall", 3)
        snapshot = {
            "a": (await self.db.get_user(TST_ID))["coins"],
            "b": (await self.db.get_user(NORMAL_ID))["coins"],
            "army_a": await self.db.get_army(TST_ID),
            "army_b": await self.db.get_army(NORMAL_ID),
        }
        res = await admin_core.simulate_test_battle(TST_ID, NORMAL_ID)
        self.assertTrue(res["ok"])
        self.assertIn(res["winner"], ("attacker", "defender"))
        self.assertEqual((await self.db.get_user(TST_ID))["coins"], snapshot["a"])
        self.assertEqual((await self.db.get_user(NORMAL_ID))["coins"], snapshot["b"])
        self.assertEqual(await self.db.get_army(TST_ID), snapshot["army_a"])
        self.assertEqual(await self.db.get_army(NORMAL_ID), snapshot["army_b"])

    async def test_test_battle_missing_player(self):
        res = await admin_core.simulate_test_battle(999_999_999, TST_ID)
        self.assertFalse(res["ok"])

    # --- ریست حساب تست
    async def test_reset_player(self):
        await self.db.ensure_user(TST_ID)
        await self.db.set_unit(TST_ID, "missile", 8)
        await self.db.inv_add(TST_ID, "lucky", 2)
        await self.db.set_buff(TST_ID, "lucky", int(os.sys.maxsize))
        await self.db.bump_mission(TST_ID, "attack3", 3)
        await self.db.growth_snapshot(TST_ID, 500)

        reset = await self.db.reset_player(TST_ID)
        self.assertIsNotNone(reset)
        self.assertEqual(reset["coins"], game.START_COINS)
        self.assertEqual(reset["level"], 1)
        self.assertEqual(reset["xp"], 0)
        self.assertEqual(reset["tester_granted"], 0)
        self.assertEqual(await self.db.get_army(TST_ID), {"soldier": 5})
        self.assertEqual(await self.db.inv_get(TST_ID), {})
        self.assertEqual(await self.db.buffs_active(TST_ID), {})
        self.assertEqual(await self.db.missions_today(TST_ID), {})
        self.assertIsNone(await self.db.mine_get(TST_ID))
        self.assertEqual(await self.db.growth_history(TST_ID), [])
        # هدیهٔ تست دوباره فعال می‌شود
        t = await self.db.ensure_user(TST_ID)
        self.assertEqual(t["tester_granted"], 1)
        self.assertGreater(t["coins"], game.START_COINS)


# ─────────────────────────────── تست‌های پنل مدیریت ──────────────────────────
class TestAdminPanel(unittest.TestCase):
    def test_parse_two_ints(self):
        self.assertEqual(admin_panel.parse_two_ints("123 456"), (123, 456))
        self.assertIsNone(admin_panel.parse_two_ints("123"))
        self.assertIsNone(admin_panel.parse_two_ints("abc def"))

    def test_parse_three(self):
        self.assertEqual(admin_panel.parse_three("1 tank 5"), (1, "tank", 5))
        self.assertIsNone(admin_panel.parse_three("1 tank"))
        self.assertIsNone(admin_panel.parse_three("x y 5"))

    def test_resolve_user_id(self):
        self.assertEqual(admin_panel.resolve_user_id("123456"), 123456)
        self.assertEqual(admin_panel.resolve_user_id("@ali"), 0)  # یوزرنیم جدا
        self.assertEqual(admin_panel.resolve_user_id("abc"), 0)

    def test_panel_text_and_kb(self):
        text = admin_panel.admin_panel_text()
        self.assertIn("پنل مدیریت", text)
        kb = admin_panel.admin_panel_kb()
        datas = [b.callback_data for r in kb.inline_keyboard for b in r]
        for expected in ("adm:coins", "adm:xp", "adm:level", "adm:unit",
                         "adm:item", "adm:battle", "adm:info", "adm:reset",
                         "adm:help"):
            self.assertIn(expected, datas)

    def test_giveable_lists(self):
        for key in admin_panel.GIVEABLE_UNITS:
            self.assertTrue(key in game.UNITS or key in game.DEFENSES,
                            f"{key} نه یگان است نه سازه")
        for key in admin_panel.GIVEABLE_ITEMS:
            self.assertIn(key, game.ITEMS)
            self.assertNotEqual(game.ITEMS[key]["kind"], "pack")


class TestAdminPanelDB(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DB(os.path.join(tempfile.mkdtemp(), "panel.db"))
        await self.db.init()
        admin_core.setup(self.db)
        admin_panel.setup(self.db)
        # بازیکن عادی و مدیر
        self.normal = await self.db.ensure_user(NORMAL_ID, "ali", "علی")
        self.dev = await self.db.ensure_user(DEV_ID, "dev", "مدیر")

    async def asyncTearDown(self):
        await self.db.close()

    async def test_add_coins_via_db(self):
        before = (await self.db.get_user(NORMAL_ID))["coins"]
        await self.db.update_user(NORMAL_ID, coins=before + 50_000)
        self.assertEqual((await self.db.get_user(NORMAL_ID))["coins"],
                         game.START_COINS + 50_000)

    async def test_add_xp_and_level_via_panel_math(self):
        u = await self.db.get_user(NORMAL_ID)
        xp, lvl, gained, bonus = game.add_xp(u["xp"], u["level"], 1500)
        await self.db.update_user(NORMAL_ID, xp=xp, level=lvl)
        u2 = await self.db.get_user(NORMAL_ID)
        self.assertGreater(u2["xp"], 0)
        self.assertGreaterEqual(u2["level"], u["level"])

    async def test_give_unit_and_item_via_db(self):
        army = await self.db.get_army(NORMAL_ID)
        await self.db.set_unit(NORMAL_ID, "fighter", army.get("fighter", 0) + 3)
        await self.db.inv_add(NORMAL_ID, "lucky", 2)
        self.assertEqual((await self.db.get_army(NORMAL_ID))["fighter"], 3)
        self.assertEqual((await self.db.inv_get(NORMAL_ID))["lucky"], 2)

    async def test_dev_can_see_admin_button_in_menu_kb(self):
        from narbad_bot import menu
        kb_dev = menu.base_kb(self.dev)
        kb_normal = menu.base_kb(self.normal)
        dev_datas = [b.callback_data for r in kb_dev.inline_keyboard for b in r]
        normal_datas = [b.callback_data for r in kb_normal.inline_keyboard
                        for b in r]
        self.assertIn("admin:panel", dev_datas)
        self.assertNotIn("admin:panel", normal_datas)

    async def test_registered_routers_have_no_conflict(self):
        """ثبت تمام ۹ روتر اصلی (شامل پنل مدیریت، سیستم نوین ارتش و دفاع) در یک Dispatcher."""
        from aiogram import Dispatcher
        from narbad_bot import (handlers, handlers_army, handlers_clan,
                                handlers_defense, handlers_missions,
                                handlers_shop, handlers_territory, menu)
        dp = Dispatcher()
        for r in (handlers.router, handlers_shop.router, handlers_missions.router,
                  handlers_clan.router, handlers_territory.router, menu.router,
                  handlers_army.router, handlers_defense.router, admin_panel.router):
            try:
                r.parent_router = None
            except Exception:  # noqa: BLE001
                pass
            dp.include_router(r)
        self.assertEqual(len(dp.sub_routers), 9)


if __name__ == "__main__":
    unittest.main()
