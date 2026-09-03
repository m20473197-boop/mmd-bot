"""تست‌های رگرسیون رفع باگ منوی مأموریت‌های روزانه.

باگ گزارش‌شده: «بعد از تکمیل یک مأموریت، منوی مأموریت‌ها دیگر باز نمی‌شود.»
علت:‌ missions_kb() از spec['emoji'] استفاده می‌کرد در حالی که مشخصه‌های
مأموریت در game.MISSIONS فیلد emoji نداشتند → KeyError دقیقاً وقتی که
اولین مأموریت «قابل دریافت» می‌شد (یعنی بعد از اولین تکمیل).
"""
import asyncio
import os
import tempfile
import unittest

from narbad_bot import game, handlers_missions, hooks
from narbad_bot.db import DB

# ─────────────────────────────────────────────────────────── اشیای تقلبی
class FakeUser:
    is_bot = False

    def __init__(self, uid: int, first_name="تست", username="testuser"):
        self.id = uid
        self.first_name = first_name
        self.username = username


class FakeMessage:
    def __init__(self, user: FakeUser):
        self.from_user = user
        self.reply_to_message = None
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


# ─────────────────────────────────────────────────────────── تست‌های واحد
class TestMissionSpecs(unittest.TestCase):
    def test_all_specs_have_required_keys(self):
        """هر مأموریت باید emoji/name/target/coins/xp داشته باشد (جلوگیری از KeyError)."""
        for key, spec in game.MISSIONS.items():
            for field in ("emoji", "name", "target", "coins", "xp"):
                self.assertIn(field, spec, f"مأموریت {key} فیلد {field} را ندارد")
            self.assertTrue(spec["emoji"])
            self.assertTrue(spec["name"])
            self.assertGreater(spec["target"], 0)

    def test_mission_keys_unique_and_complete(self):
        self.assertEqual(len(game.MISSIONS), 6)

    def test_kb_render_with_claimable_mission_no_crash(self):
        """بازتولید باگ: بعد از تکمیل یک مأموریت، missions_kb نباید خطا بدهد."""
        rows = {"attack3": {"key": "attack3", "day": "2026-09-03",
                            "progress": 3, "claimed": 0}}
        kb = handlers_missions.missions_kb(1, rows)  # قبلاً KeyError: 'emoji'
        texts = [b.text for r in kb.inline_keyboard for b in r]
        datas = [b.callback_data for r in kb.inline_keyboard for b in r]
        self.assertIn("claim:attack3", datas)
        self.assertEqual(len(texts), 4)  # claim + معدن + بازگشت + منوی اصلی

    def test_text_states_ready_claimed_remaining(self):
        rows = {
            "attack3": {"key": "attack3", "progress": 3, "claimed": 0},   # آماده
            "win2": {"key": "win2", "progress": 2, "claimed": 1},         # دریافت‌شده
        }
        text = handlers_missions.missions_text(rows)
        self.assertIn("🟢 آمادهٔ دریافت", text)
        self.assertIn("✅ دریافت شد", text)
        self.assertIn("🔸 ادامه بده", text)          # مأموریت‌های باقی‌مانده
        for key, spec in game.MISSIONS.items():      # همهٔ مأموریت‌ها نمایان‌اند
            self.assertIn(spec["name"], text)

    def test_kb_empty_rows_still_opens(self):
        kb = handlers_missions.missions_kb(1, {})
        datas = [b.callback_data for r in kb.inline_keyboard for b in r]
        self.assertIn("mine:panel", datas)
        self.assertIn("nav:base", datas)

    def test_routes_still_registered(self):
        """هندلرهای مأموریت پس از تکمیل/دریافت نباید غیرفعال شوند."""
        routes = handlers_missions.router.callback_query.handlers
        self.assertGreaterEqual(len(routes), 3)  # missions:show / claim: / mine:...


# ─────────────────────────────────────────────────────── تست‌های جریان کامل
class TestMissionFlowDB(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DB(os.path.join(tempfile.mkdtemp(), "missions.db"))
        await self.db.init()
        handlers_missions.setup(self.db)
        hooks.setup(self.db)
        self.user = await self.db.ensure_user(1, "gen", "ژنرال")
        self.uid = self.user["user_id"]
        self.fake_user = FakeUser(self.uid, "ژنرال", "gen")

    async def asyncTearDown(self):
        await self.db.close()

    async def test_complete_mission_menu_still_opens(self):
        """سناریوی اصلی باگ: تکمیل مأموریت ← باز شدن منو ← دریافت ← باز شدن دوباره."""
        # دو پیروزی → win2 کامل (قبلاً همین‌جا منو می‌شکست)
        await hooks.after_battle(self.uid, won=True)
        await hooks.after_battle(self.uid, won=True)
        rows = await self.db.missions_today(self.uid)
        self.assertEqual(rows["win2"]["progress"], 2)
        self.assertEqual(rows["win2"]["claimed"], 0)

        # ۱) /missions باید باز شود و دکمهٔ دریافت بدهد
        msg = FakeMessage(self.fake_user)
        await handlers_missions.cmd_missions(msg)
        self.assertTrue(msg.sent)
        kb_json = msg.sent[0][1]["reply_markup"].model_dump_json()
        self.assertIn("claim:win2", kb_json)
        self.assertIn("🟢 آمادهٔ دریافت", msg.sent[0][0])

        # ۲) دریافت جایزه
        before = (await self.db.get_user(self.uid))["coins"]
        cb = FakeCallback("claim:win2", self.fake_user)
        await handlers_missions.cb_claim(cb)
        self.assertTrue(cb.answers)                     # پاسخ callback داده شد
        self.assertIn("جایزه دریافت شد", cb.answers[0][0])
        self.assertTrue(cb.message.edited)              # منو رفرش شد
        self.assertIn("✅ دریافت شد", cb.message.edited[0][0])

        # ۳) منو بعد از دریافت هم باید باز شود (دکمهٔ پنل پایه)
        cb2 = FakeCallback("missions:show", self.fake_user)
        await handlers_missions.cb_missions_show(cb2)
        self.assertTrue(cb2.message.edited)
        self.assertTrue(cb2.answers)

        # ۴) مأموریت دریافت‌شده «دریافت شد» نشان داده می‌شود و مأموریت‌های بعدی دیده می‌شوند
        text = cb2.message.edited[0][0]
        self.assertIn("✅ دریافت شد", text)
        self.assertIn(game.MISSIONS["buy5"]["name"], text)          # باقی‌مانده

        # ۵) جایزه دقیقاً یک بار داده شد
        after = (await self.db.get_user(self.uid))["coins"]
        exp = game.add_xp(0, 1, game.MISSIONS["win2"]["xp"])
        bonus = exp[3]  # جایزهٔ ارتقای سطح
        self.assertEqual(after - before, game.MISSIONS["win2"]["coins"] + bonus)

    async def test_double_claim_no_double_reward(self):
        await hooks.after_battle(self.uid, won=True)
        await hooks.after_battle(self.uid, won=True)   # win2 کامل شد
        before = (await self.db.get_user(self.uid))["coins"]

        r1 = await hooks.claim_mission_rewards(self.uid, "win2")
        after_first = (await self.db.get_user(self.uid))["coins"]
        r2 = await hooks.claim_mission_rewards(self.uid, "win2")   # لمس دوباره
        after_second = (await self.db.get_user(self.uid))["coins"]
        self.assertIsNotNone(r1)
        self.assertIsNone(r2)
        self.assertGreater(after_first, before)
        # فقط یک بار جایزه؛ ادعای دوم هیچ سکه‌ای اضافه نمی‌کند
        self.assertEqual(after_first, after_second)

    async def test_concurrent_claims_only_one_wins(self):
        """دو درخواست هم‌زمان → فقط یکی جایزه می‌گیرد (رقابت atomic)."""
        await self.db.bump_mission(self.uid, "attack3", 3)
        before = (await self.db.get_user(self.uid))["coins"]
        results = await asyncio.gather(
            hooks.claim_mission_rewards(self.uid, "attack3"),
            hooks.claim_mission_rewards(self.uid, "attack3"),
        )
        winners = [r for r in results if r is not None]
        self.assertEqual(len(winners), 1)
        after = (await self.db.get_user(self.uid))["coins"]
        spec = game.MISSIONS["attack3"]
        exp = game.add_xp(0, 1, spec["xp"])
        self.assertEqual(after - before, spec["coins"] + exp[3])

    async def test_claim_incomplete_mission_returns_none(self):
        self.assertIsNone(await hooks.claim_mission_rewards(self.uid, "buy5"))
        self.assertIsNone(await hooks.claim_mission_rewards(self.uid, "unknown_key"))

    async def test_claim_unknown_mission_handler_safe(self):
        """فشردن دکمهٔ نامعتبر نباید منو را بشکند."""
        cb = FakeCallback("claim:hacked", self.fake_user)
        await handlers_missions.cb_claim(cb)
        self.assertTrue(cb.answers)
        self.assertEqual(cb.answers[0][1], True)   # alert
        self.assertFalse(cb.message.edited)        # بدون رفرش خراب

    async def test_all_claimed_menu_fully_functional(self):
        """حتی وقتی همهٔ مأموریت‌ها دریافت شده، منو باز می‌ماند."""
        for key in game.MISSIONS:
            await self.db.bump_mission(self.uid, key, game.MISSIONS[key]["target"])
            await hooks.claim_mission_rewards(self.uid, key)

        cb = FakeCallback("missions:show", self.fake_user)
        await handlers_missions.cb_missions_show(cb)
        self.assertTrue(cb.message.edited)
        kb_json = cb.message.edited[0][1]["reply_markup"].model_dump_json()
        self.assertNotIn("claim:", kb_json)            # هیچ دکمهٔ دریافت نمانده
        self.assertIn("mine:panel", kb_json)           # ولی منو زنده است
        self.assertIn("nav:base", kb_json)

    async def test_mission_progress_never_drops_after_claim(self):
        """بعد از دریافت، پیشرفت مأموریت حفظ می‌شود (وضعیت نامعتبر نمی‌شود)."""
        await self.db.bump_mission(self.uid, "mine1", 1)
        await hooks.claim_mission_rewards(self.uid, "mine1")
        await hooks.after_mine_claim(self.uid)          # باز هم استخراج
        rows = await self.db.missions_today(self.uid)
        self.assertEqual(rows["mine1"]["progress"], 2)
        self.assertEqual(rows["mine1"]["claimed"], 1)


if __name__ == "__main__":
    unittest.main()
