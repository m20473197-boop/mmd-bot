"""تست‌های واحد برای منطق بازی نبردگاه."""
import unittest

from narbad_bot import game


class TestUnits(unittest.TestCase):
    def test_unit_fields(self):
        self.assertEqual(len(game.UNITS), 9)
        for u in game.UNITS.values():
            self.assertGreater(u["cost"], 0)
            self.assertGreater(u["power"], 0)
            self.assertTrue(u["name"])
            self.assertTrue(u["emoji"])

    def test_power_calcs(self):
        army = {"soldier": 5, "tank": 2}
        self.assertEqual(game.attack_power(army), 5 * 10 + 2 * 90)
        # سازه‌ها در قدرت حمله نقشی ندارند
        self.assertEqual(game.attack_power({"wall": 3}), 0)
        # دفاع: یگان ۷۰٪ + سازه کامل
        self.assertEqual(
            game.defense_power({"soldier": 10}, {"wall": 2}),
            round(10 * 10 * 0.7 + game.struct_defense_power("wall", 2)),
        )


class TestRanks(unittest.TestCase):
    def test_rank_names(self):
        self.assertEqual(game.rank_name(1), "سرباز")
        self.assertEqual(game.rank_name(5), "گروهبان")
        self.assertEqual(game.rank_name(10), "ستوان")
        self.assertEqual(game.rank_name(40), "ژنرال")

    def test_xp_curve(self):
        # سطح ۱ → ۱۰۰ تجربه، سطح ۲ → ۱۷۵
        self.assertEqual(game.xp_to_next(1), 100)
        self.assertEqual(game.xp_to_next(2), 175)
        xp, lvl, gained, reward = game.add_xp(90, 1, 60)  # 90+60=150 → سطح ۲ (۵۰ باقی)
        self.assertEqual((xp, lvl, gained), (50, 2, 1))
        self.assertGreater(reward, 0)

    def test_daily_reward(self):
        self.assertEqual(game.daily_reward(1), 290)
        self.assertEqual(game.daily_reward(5), 450)


class TestEnergy(unittest.TestCase):
    def test_regen(self):
        import time
        now = int(time.time())
        # ts=0 یعنی زمان پایه ثبت نشده → بازتولید کامل
        u = {"energy": 50, "energy_ts": 0}
        e, ts = game.effective_energy(u)
        self.assertEqual(e, game.MAX_ENERGY)
        # با گذشت ۱۰ دقیقه، ۲ واحد بازتولید
        u = {"energy": 50, "energy_ts": now - 10 * 60}
        e, ts = game.effective_energy(u)
        self.assertEqual(e, 52)
        # بدون گذر زمان، چیزی بازتولید نمی‌شود
        u = {"energy": 50, "energy_ts": now}
        e, ts = game.effective_energy(u)
        self.assertEqual(e, 50)

    def test_cap(self):
        u = {"energy": game.MAX_ENERGY, "energy_ts": 0}
        e, ts = game.effective_energy(u)
        self.assertEqual(e, game.MAX_ENERGY)


class TestBattle(unittest.TestCase):
    def _tank_army(self, n):
        return {"tank": n}

    def test_strong_attacker_wins_mostly(self):
        wins = 0
        for _ in range(100):
            r = game.simulate_battle(self._tank_army(100), self._tank_army(1),
                                     {"wall": 1}, 10000, 5000)
            if r["winner"] == "attacker":
                wins += 1
        self.assertGreater(wins, 90)  # برتری بزرگ → برد تقریباً همیشه

    def test_strong_defender_mostly_wins(self):
        wins = 0
        for _ in range(100):
            r = game.simulate_battle(self._tank_army(1), self._tank_army(100),
                                     {"castle": 5}, 5000, 10000)
            if r["winner"] == "defender":
                wins += 1
        self.assertGreater(wins, 90)

    def test_no_negative_values(self):
        for _ in range(200):
            r = game.simulate_battle(self._tank_army(3), {"soldier": 4},
                                     {"wall": 2}, 800, 500)
            self.assertGreaterEqual(r["loot"], 0)
            self.assertGreaterEqual(r["att_xp"], 0)
            self.assertGreaterEqual(r["def_xp"], 0)
            for loss in list(r["att_cas"].values()) + list(r["def_cas"].values()):
                self.assertGreaterEqual(loss, 0)

    def test_loot_is_bounded(self):
        r = game.simulate_battle(self._tank_army(200), self._tank_army(200),
                                 {}, 10**9, 10**9)
        self.assertLessEqual(r["loot"], game.MAX_LOOT)

    def test_casualties_never_exceed_army(self):
        for _ in range(300):
            army = {"soldier": 5, "tank": 2, "missile": 1}
            r = game.simulate_battle(army, army, {"wall": 3}, 1000, 1000)
            for k, v in r["att_cas"].items():
                self.assertLessEqual(v, army[k])
            for k, v in r["def_cas"].items():
                self.assertLessEqual(v, army[k])

    def test_cas_text(self):
        self.assertEqual(game.cas_text({}), "بدون تلفات")
        self.assertIn("🪖", game.cas_text({"soldier": 3}))


class TestFormatting(unittest.TestCase):
    def test_fa_digits(self):
        self.assertEqual(game.fa(0), "۰")
        self.assertEqual(game.fa(1234567), "۱٬۲۳۴٬۵۶۷")
    def test_shop_keys(self):
        self.assertEqual(len(game.SHOP), len(game.UNITS) + len(game.DEFENSES))


if __name__ == "__main__":
    unittest.main()
