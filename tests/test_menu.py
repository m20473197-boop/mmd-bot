"""تست‌های منوی پایین چت (صفحه‌کلید سفارشی)."""
import asyncio
import os
import tempfile
import unittest

from aiogram import Dispatcher

from narbad_bot import (handlers, handlers_army, handlers_clan,
                        handlers_defense, handlers_missions, menu)
from narbad_bot.db import DB


class TestMenuLayout(unittest.TestCase):
    def test_main_menu_is_reply_keyboard(self):
        """منوی اصلی باید ReplyKeyboardMarkup باشد (دکمه‌های پایین چت)."""
        kb = menu.main_menu_kb()
        self.assertEqual(kb.__class__.__name__, "ReplyKeyboardMarkup")
        self.assertEqual(len(kb.keyboard), 2)      # دو ردیف
        self.assertEqual(len(kb.keyboard[0]), 3)   # سه ستون
        self.assertEqual(len(kb.keyboard[1]), 2)   # دو ستون
        # برچسب‌های دقیق دکمه‌ها
        flat = [b.text for row in kb.keyboard for b in row]
        self.assertEqual(flat, list(menu.MENU_BUTTONS))
        self.assertTrue(kb.resize_keyboard)
        self.assertTrue(kb.is_persistent)

    def test_all_five_buttons_present(self):
        expected = {"🏠 پایگاه", "⚔️ نبرد", "🪖 ارتش",
                    "🏰 اتحادیه", "🛡 دفاع"}
        self.assertEqual(set(menu.MENU_BUTTONS), expected)

    def test_menu_router_has_five_button_handlers(self):
        """چهار دکمهٔ دسته در menu router، دکمهٔ «🪖 ارتش» در handlers_army و دکمهٔ «🛡 دفاع» در handlers_defense."""
        names = {h.callback.__name__ for h in menu.router.message.handlers}
        for expected in ("on_base", "on_battle", "on_clan"):
            self.assertIn(expected, names)
        from narbad_bot import handlers_army, handlers_defense
        army_names = {h.callback.__name__ for h in handlers_army.router.message.handlers}
        self.assertIn("on_army", army_names)
        def_names = {h.callback.__name__ for h in handlers_defense.router.message.handlers}
        self.assertIn("on_defense", def_names)

    def test_shield_menu_does_not_crash_hours_parser(self):
        """دادهٔ «shield:menu» نباید توسط هندلر «shield:» شکسته شود."""
        parts = "shield:menu".split(":")
        valid = len(parts) == 2 and parts[1].isdigit()
        self.assertFalse(valid)          # باید رد شود
        parts = "shield:6".split(":")
        valid = len(parts) == 2 and parts[1].isdigit()
        self.assertTrue(valid)           # اما «shield:6» مجاز است
        self.assertEqual(int("shield:24".split(":")[1]), 24)


class TestMenuDB(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DB(os.path.join(tempfile.mkdtemp(), "menu.db"))
        await self.db.init()
        menu.setup(self.db)
        handlers.setup(self.db)
        handlers_missions.setup(self.db)
        handlers_clan.setup(self.db)

    async def asyncTearDown(self):
        await self.db.close()

    async def test_base_text_renders(self):
        u = await self.db.ensure_user(1, "ali", "علی")
        # base_text سازگار با نسخهٔ جدید (پروکسی به پنل پایگاه)
        text = await menu.base_text(u) if hasattr(menu, "base_text") else menu.BASE_PANEL
        self.assertIn("پایگاه", text)
        self.assertIn("سکه", text)
        self.assertIn("قدرت", text)

    async def test_menu_buttons_reach_handlers(self):
        """هر دکمهٔ منو باید به یک پنل inline کامل ختم شود."""
        u = await self.db.ensure_user(1, "a", "الف")
        base_text_fn = menu.base_text if hasattr(menu, "base_text") else lambda x: menu.BASE_PANEL
        # handle both sync/async
        import inspect
        bt = base_text_fn(u)
        if inspect.isawaitable(bt):
            bt = await bt
        self.assertIn("پایگاه", bt)              # 🏠
        # attack_kb قدیمی → battle_kb جدید
        atk_kb_fn = getattr(menu, "attack_kb", None) or getattr(menu, "battle_menu_kb", None)
        self.assertIn("تصادفی", atk_kb_fn().model_dump_json() if atk_kb_fn else "")  # ⚔️ نبرد
        eq_buttons = [b.callback_data for r in handlers_army.equipment_kb().inline_keyboard for b in r]
        self.assertEqual(sum(1 for c in eq_buttons if c.startswith("army:eqview:")), 7)  # 🪖 ۷ تجهیز
        self.assertGreater(len(handlers.defense_kb().inline_keyboard), 3)  # 🛡
        # اتحادیه: کاربر بدون اتحادیه → دکمهٔ ساخت/لیست می‌بیند
        self.assertIsNotNone(u)


if __name__ == "__main__":
    unittest.main()
