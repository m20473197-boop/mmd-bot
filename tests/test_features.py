"""تست‌های قابلیت‌های جدید: مأموریت‌ها، معدن، آیتم‌ها، اتحادیه، نمودار."""
import asyncio
import os
import tempfile
import time
import unittest

from narbad_bot import game
from narbad_bot.db import DB


class TestMissionsAndMine(unittest.TestCase):
    def test_mission_specs(self):
        for key, spec in game.MISSIONS.items():
            self.assertGreater(spec["target"], 0)
            self.assertGreater(spec["coins"], 0)
            self.assertGreater(spec["xp"], 0)
        self.assertEqual(len(game.MISSIONS), 6)

    def test_mine_gain(self):
        # ۱۰ سرباز در ۱ ساعت → ۳۰ سکه
        self.assertEqual(game.mine_gain(10, 3600), 30)
        # نصف ساعت → ۱۵ سکه
        self.assertEqual(game.mine_gain(10, 1800), 15)
        # سقف ۸ ساعت
        self.assertEqual(game.mine_gain(10, 80 * 3600), 10 * 3 * 8)
        # صفر
        self.assertEqual(game.mine_gain(10, 0), 0)

    def test_xp_curve_for_claims(self):
        xp, lvl, gained, bonus = game.add_xp(0, 1, 80)
        self.assertEqual((xp, lvl, gained), (80, 1, 0))


class TestItems(unittest.TestCase):
    def test_item_specs(self):
        self.assertEqual(len(game.ITEMS), 7)
        for key, item in game.ITEMS.items():
            self.assertGreater(item["price"], 0)
            self.assertIn(item["kind"], ("instant", "buff", "consumable", "pack"))

    def test_buff_multipliers_valid(self):
        for buff, (field, factor) in game.BUFF_MULT.items():
            self.assertIn(buff, game.ITEMS)
            self.assertGreater(factor, 1.0)
            self.assertIn(field, ("att_mult", "loot_mult", "xp_mult"))

    def test_battle_with_buffs(self):
        army = {"tank": 10}
        base = game.simulate_battle(army, {"soldier": 10}, {}, 5000, 5000)
        lucky = game.simulate_battle(army, {"soldier": 10}, {}, 5000, 5000,
                                     att_mult=1.2)
        self.assertGreaterEqual(lucky["att_power"], base["att_power"])
        # کیت تعمیر: تلفات کمتر یا مساوی
        repair = game.simulate_battle(army, {"soldier": 10}, {}, 5000, 5000,
                                      cas_mult=0.5)
        base_cas = sum(base["att_cas"].values())
        repair_cas = sum(repair["att_cas"].values())
        self.assertLessEqual(repair_cas, base_cas + 1e-9)


class TestWar(unittest.TestCase):
    def test_war_points(self):
        self.assertEqual(game.war_points(True, 600), 120 + 2)
        self.assertEqual(game.war_points(False, 99999), 30)
        self.assertEqual(game.war_points(True, 0), 120)

    def test_war_constants(self):
        self.assertEqual(game.WAR_DURATION, 86400)
        self.assertEqual(game.WAR_START_COST, 3000)


class TestFeaturesDB(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "test.db")
        self.db = DB(self.path)
        await self.db.init()

    async def asyncTearDown(self):
        await self.db.close()

    async def test_clan_lifecycle(self):
        clan = await self.db.create_clan("شیران", 1)
        await self.db.add_member(clan["id"], 2)
        members = await self.db.clan_members(clan["id"])
        self.assertEqual(len(members), 2)
        self.assertEqual(members[0]["role"], "leader")
        # خروج رهبر → ارتقای اولین عضو
        await self.db.remove_member(1)
        clan = await self.db.get_clan(clan["id"])
        self.assertEqual(clan["leader_id"], 2)

    async def test_clan_disband(self):
        clan = await self.db.create_clan("تنها", 1)
        res = await self.db.remove_member(1)
        self.assertTrue(res["disbanded"])
        self.assertIsNone(await self.db.get_clan(clan["id"]))

    async def test_war_flow(self):
        c1 = await self.db.create_clan("الف", 1)
        c2 = await self.db.create_clan("ب", 2)
        war = await self.db.create_war(c1["id"], c2["id"])
        await self.db.add_war_points(war["id"], "A", 100)
        war = await self.db.get_war(war["id"])
        self.assertEqual(war["points_a"], 100)
        self.assertEqual(war["status"], "active")
        # پایان جنگ
        now = time.time()
        await self.db._execute("UPDATE wars SET end_ts = ? WHERE id = ?",
                               (int(now) - 1, war["id"]))
        await self.db.update_clan(c2["id"], treasury=10000)
        war = await self.db.get_war(war["id"])
        self.assertEqual(war["status"], "finished")
        self.assertEqual(war["winner_id"], c1["id"])
        c1 = await self.db.get_clan(c1["id"])
        c2 = await self.db.get_clan(c2["id"])
        self.assertEqual(c2["treasury"], 10000 - 2500)
        self.assertEqual(c1["treasury"], 2500)
        self.assertEqual(c1["war_wins"], 1)

    async def test_missions_db(self):
        await self.db.bump_mission(1, "attack3", 2)
        await self.db.bump_mission(1, "attack3", 1)
        rows = await self.db.missions_today(1)
        self.assertEqual(rows["attack3"]["progress"], 3)
        self.assertEqual(rows["attack3"]["claimed"], 0)
        await self.db.mark_mission_claimed(1, "attack3")
        rows = await self.db.missions_today(1)
        self.assertEqual(rows["attack3"]["claimed"], 1)

    async def test_inventory_and_buffs_db(self):
        await self.db.inv_add(1, "lucky", 2)
        self.assertEqual((await self.db.inv_get(1))["lucky"], 2)
        await self.db.inv_take(1, "lucky")
        self.assertEqual((await self.db.inv_get(1))["lucky"], 1)
        await self.db.set_buff(1, "lucky", int(time.time()) + 1000)
        self.assertIn("lucky", await self.db.buffs_active(1))
        # بافت منقضی نمایش داده نمی‌شود
        await self.db.set_buff(1, "magnet", int(time.time()) - 1)
        self.assertNotIn("magnet", await self.db.buffs_active(1))

    async def test_growth_snapshot(self):
        await self.db.growth_snapshot(1, 100)
        await self.db.growth_snapshot(1, 250)
        await self.db.growth_snapshot(1, 400)
        rows = await self.db.growth_history(1)
        self.assertEqual([r["power"] for r in rows], [100, 250, 400])

    async def test_mine_db(self):
        await self.db.mine_start(1, int(time.time()) - 7200, 10)
        state = await self.db.mine_get(1)
        self.assertEqual(state["workers"], 10)
        self.assertEqual(game.mine_gain(state["workers"],
                                        int(time.time()) - state["start_ts"]), 60)
        await self.db.mine_clear(1)
        self.assertIsNone(await self.db.mine_get(1))

    async def test_migration_from_old_schema(self):
        """دیتابیس قدیمی (بدون clan_id) باید بدون خطا ارتقا یابد."""
        import sqlite3
        with sqlite3.connect(self.path) as con:
            con.executescript("""
                DROP TABLE IF EXISTS users;
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '',
                    first_name TEXT DEFAULT '', coins INTEGER DEFAULT 800,
                    level INTEGER DEFAULT 1, xp INTEGER DEFAULT 0,
                    energy INTEGER DEFAULT 100, energy_ts INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0,
                    def_wins INTEGER DEFAULT 0, def_losses INTEGER DEFAULT 0,
                    last_daily INTEGER DEFAULT 0, shield_until INTEGER DEFAULT 0,
                    created_at INTEGER DEFAULT 0);
                INSERT INTO users (user_id, username) VALUES (42, 'old');
            """)
        # بستن اتصال فعلی و باز کردن دوباره با همان فایل
        await self.db.close()
        self.db = DB(self.path)
        await self.db.init()
        u = await self.db.get_user(42)
        self.assertIsNotNone(u)
        await self.db.ensure_user(42, "old", "قدیمی")
        u = await self.db.get_user(42)
        self.assertEqual(u["first_name"], "قدیمی")


if __name__ == "__main__":
    unittest.main()
