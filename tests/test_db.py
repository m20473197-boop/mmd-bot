"""تست‌های دیتابیس و شبیه‌سازی نبرد کامل (بدون تلگرام)."""
import asyncio
import os
import tempfile
import unittest

from narbad_bot import game
from narbad_bot.db import DB


class TestDB(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "test.db")
        self.db = DB(self.path)
        await self.db.init()

    async def asyncTearDown(self):
        await self.db.close()

    async def test_ensure_user_creates_and_keeps(self):
        u = await self.db.ensure_user(1, "ali", "علی")
        self.assertEqual(u["coins"], game.START_COINS)
        army = await self.db.get_army(1)
        self.assertEqual(army.get("soldier"), game.START_SOLDIERS)
        # ثبت دوباره نباید وضعیت را عوض کند
        u2 = await self.db.ensure_user(1, "ali", "علی")
        self.assertEqual(u2["coins"], game.START_COINS)

    async def test_army_ops(self):
        await self.db.set_unit(1, "tank", 3)
        await self.db.set_unit(1, "tank", 3 + 5)
        army = await self.db.get_army(1)
        self.assertEqual(army["tank"], 8)
        await self.db.set_unit(1, "tank", 0)  # حذف
        self.assertNotIn("tank", await self.db.get_army(1))

    async def test_find_by_username(self):
        await self.db.ensure_user(1, "Ali")
        self.assertEqual((await self.db.find_by_username("@ali"))["user_id"], 1)
        self.assertIsNone(await self.db.find_by_username("nobody"))

    async def test_leaderboards(self):
        await self.db.ensure_user(1, "a", "الف")
        await self.db.ensure_user(2, "b", "ب")
        await self.db.set_unit(1, "tank", 10)
        await self.db.set_unit(2, "soldier", 10)
        top = await self.db.top_power(10)
        self.assertEqual(top[0]["user"]["user_id"], 1)
        coins = await self.db.top_coins(10)
        self.assertIn(coins[0]["user_id"], (1, 2))

    async def test_battle_flow_end_to_end(self):
        """نبرد کامل بدون تلگرام: ثبت، شبیه‌سازی، اعمال نتایج، لاگ."""
        a = await self.db.ensure_user(1, "a", "مهاجم")
        b = await self.db.ensure_user(2, "b", "مدافع")
        await self.db.set_unit(1, "tank", 6)
        await self.db.set_unit(2, "soldier", 3)
        await self.db.set_unit(2, "wall", 2)

        att_army = await self.db.get_army(1)
        def_army = await self.db.get_army(2)
        def_struct = {k: v for k, v in def_army.items() if k in game.DEFENSES}
        res = game.simulate_battle(att_army, def_army, def_struct,
                                   a["coins"], b["coins"])

        # اعمال نتایج شبیه شبیه‌سازی run_attack
        for k, loss in res["att_cas"].items():
            await self.db.set_unit(1, k, att_army.get(k, 0) - loss)
        for k, loss in res["def_cas"].items():
            await self.db.set_unit(2, k, def_army.get(k, 0) - loss)
        xp, lvl, levels, reward = game.add_xp(a["xp"], a["level"],
                                              res["att_xp"] if res["winner"] == "attacker"
                                              else res["def_xp"])
        await self.db.update_user(1, coins=a["coins"] + res["loot"], xp=xp, level=lvl)
        await self.db.update_user(2, coins=b["coins"] - res["loot"])

        await self.db.log_battle(1, 1, 2, 1 if res["winner"] == "attacker" else 2,
                                 res["loot"], res["att_power"], res["def_power"],
                                 "⚔️ پیروزی مقابل B", "⚠️ باخت در برابر A")

        log = await self.db.battle_history(1, 5)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["loot"], res["loot"])

        a2 = await self.db.get_user(1)
        self.assertEqual(a2["coins"], a["coins"] + res["loot"])
        # واحدها هرگز منفی نمی‌شوند
        final_army = await self.db.get_army(1)
        for v in final_army.values():
            self.assertGreaterEqual(v, 0)


if __name__ == "__main__":
    unittest.main()
