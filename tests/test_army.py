"""تست‌های سیستم نوین ارتش (handlers_army) — roster، فروشگاه تجهیزات، پادگان آموزش.

پوشش داده‌شده:
  • ساختار یگان‌ها (۹ یگان، زمینی vs تجهیزاتی، قانون ۵× کماندو، قیمت/زمان آموزش)
  • مایگریشن دادهٔ قدیمی: ranger → commando
  • تسویهٔ آموزش (جلوگیری از ساخت آنی + افزودن خودکار به ارتش)
  • جریان کامل خرید و آموزش با اشیای تقلبی (FakeCallback/FakeMessage)
  • رد شدن از مسیرهای نامعتبر (کمبود سکه، تعداد نامعتبر، اشغال بودن پادگان)
  • زنجیرهٔ هوک‌ها (تسویهٔ آموزش + هوک قبلی admin_core حفظ می‌شود)
  • هوک‌های مأموریت (buy5 هنگام ورود نیروها، spend2000 هنگام پرداخت)
"""
import os
import tempfile
import time
import unittest

from narbad_bot import admin_core, game, handlers_army, hooks
from narbad_bot.db import DB


# ─────────────────────────────────────────────────────────── اشیای تقلبی
class FakeUser:
    is_bot = False

    def __init__(self, uid: int, first_name="فرمانده", username="gen"):
        self.id = uid
        self.first_name = first_name
        self.username = username


class FakeMessage:
    def __init__(self, user: FakeUser):
        self.from_user = user
        self.text = None
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


# ─────────────────────────────────────────────────────────── ساختار یگان‌ها
class TestArmyRoster(unittest.TestCase):
    def test_nine_units_and_groups(self):
        self.assertEqual(len(game.UNITS), 9)
        self.assertEqual(set(game.UNITS), set(game.GROUND_UNITS) | set(game.EQUIPMENT_UNITS))
        self.assertFalse(set(game.GROUND_UNITS) & set(game.EQUIPMENT_UNITS))
        self.assertEqual(set(game.GROUND_UNITS), {"soldier", "commando"})
        self.assertEqual(set(game.EQUIPMENT_UNITS),
                         {"tank", "missile", "warship", "fighter", "bomber", "drone", "heli"})

    def test_training_rules(self):
        s, c = game.UNITS["soldier"], game.UNITS["commando"]
        self.assertEqual(s["cost"], 50)            # ۵۰ سکه به ازای هر سرباز
        self.assertEqual(c["cost"], 250)           # ۲۵۰ سکه به ازای هر کماندو
        self.assertEqual(s["train_sec"], 4)        # ۴ ثانیه برای هر سرباز
        self.assertEqual(c["train_sec"], 20)       # ۲۰ ثانیه برای هر کماندو
        self.assertEqual(c["power"], 5 * s["power"])  # کماندو ۵ برابر سرباز

    def test_unit_fields_complete(self):
        for key, info in game.UNITS.items():
            for field in ("name", "emoji", "cost", "power", "desc"):
                self.assertIn(field, info, f"{key}.{field}")
                self.assertTrue(info[field])
            self.assertGreater(info["power"], 0)
            self.assertGreater(info["cost"], 0)
        for key in game.GROUND_UNITS:
            self.assertGreater(game.UNITS[key]["train_sec"], 0)

    def test_ranger_key_gone(self):
        self.assertNotIn("ranger", game.UNITS)
        self.assertNotIn("ranger", admin_core.TESTER_GIFT_ARMY)


class TestQtyParsing(unittest.TestCase):
    def test_fa_and_en_digits(self):
        self.assertEqual(handlers_army.parse_qty("۲۵"), 25)
        self.assertEqual(handlers_army.parse_qty("25"), 25)
        self.assertEqual(handlers_army.parse_qty("۱٬۰۰"), 100)      # جداکنندهٔ هزارگان
        self.assertEqual(handlers_army.parse_qty("۱٬۰۰۰"), None)    # بیش از سقف ۵۰۰
        self.assertEqual(handlers_army.parse_qty("0"), None)
        self.assertEqual(handlers_army.parse_qty("abc"), None)
        self.assertEqual(handlers_army.parse_qty("-5"), None)
        self.assertEqual(handlers_army.parse_qty("500"), 500)
        self.assertEqual(handlers_army.parse_qty("501"), None)


# ─────────────────────────────────────────────────────────── دیتابیس و مهاجرت
class TestArmyDB(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DB(os.path.join(tempfile.mkdtemp(), "army.db"))
        await self.db.init()

    async def asyncTearDown(self):
        await self.db.close()

    async def test_migrate_ranger_to_commando(self):
        await self.db.ensure_user(7, "old", "بازیکن قدیمی")
        await self.db._execute(
            "INSERT OR REPLACE INTO army (user_id, unit, count) VALUES (7, 'ranger', 3)")
        await self.db.close()
        # بازگشایی همان فایل → مایگریشن اجرا شود
        self.db = DB(self.db.path)
        await self.db.init()
        army = await self.db.get_army(7)
        self.assertEqual(army.get("commando"), 3)
        self.assertNotIn("ranger", army)

    async def test_training_not_settled_until_due(self):
        await self.db.ensure_user(8, "t", "ت")
        await self.db.set_unit(8, "soldier", 5)
        now = int(time.time())
        await self.db.training_start(8, "soldier", 10, now, now + 40, 500)
        # قبل از پایان زمان: هیچ تسویه‌ای نباید بشود (جلوگیری از ساخت آنی)
        self.assertEqual(await self.db.settle_training(8), [])
        self.assertEqual((await self.db.get_army(8))["soldier"], 5)
        act = await self.db.training_get(8)
        self.assertIsNotNone(act)
        self.assertEqual(act["count"], 10)
        # زمان بگذرد → یگان‌ها اضافه و رکورد پاک شود
        await self.db._execute("UPDATE training SET finish_ts = ? WHERE user_id = 8",
                               (now,))
        done = await self.db.settle_training(8)
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["unit"], "soldier")
        self.assertEqual((await self.db.get_army(8))["soldier"], 15)
        self.assertIsNone(await self.db.training_get(8))
        self.assertEqual(await self.db.settle_training(8), [])

    async def test_reset_player_clears_training(self):
        await self.db.ensure_user(9, "r", "ر")
        now = int(time.time())
        await self.db.training_start(9, "commando", 4, now, now + 80, 1000)
        await self.db.reset_player(9)
        self.assertIsNone(await self.db.training_get(9))


# ─────────────────────────────────────────────────────────── جریان کامل UI
class TestArmyFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DB(os.path.join(tempfile.mkdtemp(), "flow.db"))
        await self.db.init()
        hooks.setup(self.db)
        admin_core.setup(self.db)
        handlers_army.setup(self.db)
        handlers_army._pending_qty.clear()
        handlers_army._arrived.clear()
        self.user = await self.db.ensure_user(1, "gen", "ژنرال")
        self.fu = FakeUser(1, "ژنرال", "gen")

    async def asyncTearDown(self):
        await self.db.close()

    # --- صفحهٔ فرود ارتش: دقیقاً سه گزینهٔ خواسته‌شده
    def test_landing_kb_three_sections(self):
        kb = handlers_army.army_landing_kb()
        labels = [b.text for row in kb.inline_keyboard for b in row]
        self.assertIn("🪖 ارتش من", labels)
        self.assertIn("🛒 خرید تجهیزات نظامی", labels)
        self.assertIn("🏗 آموزش نیروی زمینی", labels)

    async def test_on_army_button_renders_landing(self):
        msg = FakeMessage(self.fu)
        await handlers_army.on_army(msg)
        self.assertTrue(msg.sent)
        self.assertIn("ارتش", msg.sent[0][0])
        kb_json = msg.sent[0][1]["reply_markup"].model_dump_json()
        self.assertIn("army:my", kb_json)
        self.assertIn("army:eq", kb_json)
        self.assertIn("army:tr", kb_json)

    # --- My Army: یگان‌ها، تعداد، قدرت هر یگان و قدرت کل
    async def test_my_army_page_contents(self):
        await self.db.set_unit(1, "soldier", 3)
        await self.db.set_unit(1, "tank", 1)     # ۳×۱۰ + ۹۰ = ۱۲۰
        cb = FakeCallback("army:my", self.fu)
        await handlers_army.cb_army_my(cb)
        text = cb.message.edited[0][0]
        self.assertIn("سرباز", text)
        self.assertIn("تانک", text)
        self.assertIn("قدرت هر عدد", text)
        self.assertIn(game.fa(120), text)        # قدرت کل حمله

    # --- فروشگاه تجهیزات: قیمت و تعداد مالکیت روی هر ردیف
    async def test_equipment_page_lists_owned(self):
        await self.db.set_unit(1, "tank", 2)
        cb = FakeCallback("army:eq", self.fu)
        await handlers_army.cb_army_eq(cb)
        kb_json = cb.message.edited[0][1]["reply_markup"].model_dump_json()
        self.assertIn("دارای", kb_json)          # تعداد مالکیت روی ردیف
        self.assertIn(game.fa(800), kb_json)     # قیمت تانک با ارقام فارسی
        # جزئیات یک تجهیز: نام/توضیح/قیمت/قدرت/تعداد فعلی
        cb2 = FakeCallback("army:eqview:drone", self.fu)
        await handlers_army.cb_eq_view(cb2)
        text = cb2.message.edited[0][0]
        for frag in ("پهپاد تهاجمی", "قیمت هر عدد", "قدرت حمله", "تعداد در ارتش"):
            self.assertIn(frag, text)

    # --- خرید موفق: کسر سکه، افزودن به ارتش، مأموریت‌ها، به‌روزرسانی قدرت
    async def test_equipment_buy_success(self):
        before = (await self.db.get_user(1))["coins"]          # 800
        cb = FakeCallback("army:done:eq:tank:1", self.fu)
        await handlers_army.cb_done(cb)
        u = await self.db.get_user(1)
        self.assertEqual(u["coins"], before - 800)
        self.assertEqual((await self.db.get_army(1))["tank"], 1)
        rows = await self.db.missions_today(1)
        self.assertEqual(rows["buy5"]["progress"], 1)
        self.assertEqual(rows["spend2000"]["progress"], 800)
        self.assertTrue(cb.message.edited)
        self.assertIn("قدرت کل ارتش", cb.message.edited[0][0])

    async def test_equipment_buy_insufficient_funds(self):
        cb = FakeCallback("army:done:eq:warship:1", self.fu)   # ۲۰٬۰۰۰ > ۸۰۰
        await handlers_army.cb_done(cb)
        self.assertTrue(cb.answers)
        self.assertIn("سکه کافی نداری", cb.answers[0][0])
        self.assertEqual((await self.db.get_user(1))["coins"], 800)
        self.assertNotIn("warship", await self.db.get_army(1))
        self.assertFalse(cb.message.edited)

    async def test_equipment_buy_rejects_ground_unit(self):
        cb = FakeCallback("army:done:eq:soldier:1", self.fu)
        await handlers_army.cb_done(cb)
        self.assertIn("نامعتبر", cb.answers[0][0])
        self.assertEqual((await self.db.get_user(1))["coins"], 800)

    # --- ورودی تعداد تایپی
    async def test_qty_prompt_and_text_input_confirm(self):
        cb = FakeCallback("army:trask:soldier", self.fu)
        await handlers_army.cb_tr_ask(cb)
        self.assertEqual(handlers_army._pending_qty[1], ("tr", "soldier"))
        msg = FakeMessage(self.fu)
        msg.text = "۸"
        await handlers_army.on_qty_input(msg)
        text = msg.sent[0][0]
        self.assertIn(game.fa(8 * 50), text)     # جمع قیمت = ۴۰۰
        self.assertIn("۳۲ ثانیه", text)          # ۸ × ۴ ثانیه
        self.assertIn("✅ شروع آموزش",
                      msg.sent[0][1]["reply_markup"].model_dump_json())
        self.assertNotIn(1, handlers_army._pending_qty)   # مصرف شد

    async def test_qty_invalid_input_keeps_pending(self):
        handlers_army._pending_qty[1] = ("eq", "tank")
        msg = FakeMessage(self.fu)
        msg.text = "ده تا!"
        await handlers_army.on_qty_input(msg)
        self.assertIn("عدد صحیح", msg.sent[0][0])
        self.assertIn(1, handlers_army._pending_qty)       # هنوز منتظر است

    async def test_qty_cancel_button_resets_flow(self):
        handlers_army._pending_qty[1] = ("eq", "tank")
        cb = FakeCallback("army:back:eq", self.fu)
        await handlers_army.cb_back(cb)
        self.assertNotIn(1, handlers_army._pending_qty)
        self.assertTrue(cb.message.edited)                  # به فهرست تجهیزات برگشت

    # --- آموزش نیروی زمینی
    async def test_training_pay_starts_queue_not_instant(self):
        before = (await self.db.get_user(1))["coins"]
        cb = FakeCallback("army:done:tr:soldier:10", self.fu)
        await handlers_army.cb_done(cb)
        u = await self.db.get_user(1)
        self.assertEqual(u["coins"], before - 500)          # پرداخت شد
        self.assertEqual((await self.db.get_army(1))["soldier"],
                         game.START_SOLDIERS)                # ولی آنی ساخته نشد!
        act = await self.db.training_get(1)
        self.assertEqual((act["unit"], act["count"]), ("soldier", 10))
        self.assertGreater(act["finish_ts"], int(time.time()))
        # مأموریت «خرج» جلو رفت اما «آموزش یگان» هنوز نه (موقع ورود نیرو)
        rows = await self.db.missions_today(1)
        self.assertEqual(rows["spend2000"]["progress"], 500)
        self.assertEqual(rows["buy5"]["progress"], 0)

    async def test_training_blocks_second_order_until_done(self):
        await self.db.update_user(1, coins=100_000)
        cb1 = FakeCallback("army:done:tr:commando:5", self.fu)
        await handlers_army.cb_done(cb1)
        self.assertIsNotNone(await self.db.training_get(1))
        cb2 = FakeCallback("army:done:tr:commando:2", self.fu)
        await handlers_army.cb_done(cb2)
        self.assertIn("پادگان مشغول", cb2.answers[0][0])
        act = await self.db.training_get(1)
        self.assertEqual(act["count"], 5)                    # صف دست‌نخورده
        # درخواست جدید نباید سکه بگیرد
        self.assertEqual((await self.db.get_user(1))["coins"],
                         100_000 - 5 * game.UNITS["commando"]["cost"])

    async def test_training_full_cycle_units_arrive(self):
        await handlers_army.cb_done(FakeCallback("army:done:tr:soldier:6", self.fu))
        now = int(time.time())
        await self.db._execute("UPDATE training SET finish_ts = ? WHERE user_id = 1",
                               (now - 1,))                   # زمان بگذرد
        await self.db.ensure_user(1, "gen", "ژنرال")         # هر لمس → تسویه
        self.assertEqual((await self.db.get_army(1))["soldier"],
                         game.START_SOLDIERS + 6)
        self.assertIsNone(await self.db.training_get(1))
        rows = await self.db.missions_today(1)
        self.assertEqual(rows["buy5"]["progress"], 6)        # مأموریت آموزش موقع ورود
        self.assertIn(1, handlers_army._arrived)             # پیام رسیدن انبار شد
        # صفحهٔ «ارتش من» پیام رسیدن را نشان می‌دهد و انبار را خالی می‌کند
        cb = FakeCallback("army:my", self.fu)
        await handlers_army.cb_army_my(cb)
        self.assertIn("نیروهای تازه‌رسیده", cb.message.edited[0][0])
        self.assertNotIn(1, handlers_army._arrived)

    async def test_trask_rejected_while_training_active(self):
        await self.db.training_start(1, "soldier", 3, int(time.time()),
                                     int(time.time()) + 60, 150)
        cb = FakeCallback("army:trask:commando", self.fu)
        await handlers_army.cb_tr_ask(cb)
        self.assertEqual(cb.answers[0][0], "⏳ پادگان مشغول آموزش است!")
        self.assertNotIn(1, handlers_army._pending_qty)

    # --- صفحه پادگان: قانون‌ها نمایش داده می‌شوند
    async def test_training_page_shows_rules(self):
        cb = FakeCallback("army:tr", self.fu)
        await handlers_army.cb_army_tr(cb)
        text = cb.message.edited[0][0]
        self.assertIn(game.fa(50), text)
        self.assertIn(game.fa(250), text)
        self.assertIn("آنی ساخته نمی‌شوند", text)

    # --- تأییدیهٔ قبل از خرید: جمع قیمت و زمان کل
    async def test_confirm_view_totals(self):
        u = await self.db.get_user(1)
        text, kb = await handlers_army.confirm_view(1, u, "tr", "commando", 4)
        self.assertIn(game.fa(4 * 250), text)                 # ۱٬۰۰۰ سکه
        self.assertIn(game.fa(4 * 20), text)                   # ۸۰ ثانیه
        self.assertIn("army:done:tr:commando:4",
                      kb.model_dump_json())

    # --- هوک زنجیره‌ای: هوک قبلی نباید گم شود
    async def test_hook_chain_preserves_previous_hook(self):
        db2 = DB(os.path.join(tempfile.mkdtemp(), "chain.db"))
        await db2.init()
        calls: list[int] = []

        async def prev_hook(user: dict) -> dict:
            calls.append(user["user_id"])
            return user

        db2.user_hook = prev_hook
        handlers_army.setup(db2)
        self.assertIsNot(db2.user_hook, prev_hook)
        await db2.ensure_user(42, "c", "چهل‌ودو")
        self.assertEqual(calls, [42])                          # هوک قبلی اجرا شد
        # ثبت مجدد نباید دوباره‌پیچ شود
        hook = db2.user_hook
        handlers_army.setup(db2)
        self.assertIs(db2.user_hook, hook)
        await db2.close()
        # بازگرداندن حالت ماژول برای تست‌های بعدی
        handlers_army.setup(self.db)


if __name__ == "__main__":
    unittest.main()
