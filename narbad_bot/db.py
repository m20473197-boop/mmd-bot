"""لایه دیتابیس — SQLite با aiosqlite"""
from __future__ import annotations

import time
from typing import Any

import aiosqlite

from . import game

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    username     TEXT    DEFAULT '',
    first_name   TEXT    DEFAULT '',
    coins        INTEGER DEFAULT 800,
    level        INTEGER DEFAULT 1,
    xp           INTEGER DEFAULT 0,
    energy       INTEGER DEFAULT 100,
    energy_ts    INTEGER DEFAULT 0,
    wins         INTEGER DEFAULT 0,
    losses       INTEGER DEFAULT 0,
    def_wins     INTEGER DEFAULT 0,
    def_losses   INTEGER DEFAULT 0,
    last_daily   INTEGER DEFAULT 0,
    shield_until INTEGER DEFAULT 0,
    clan_id      INTEGER,
    tester_granted INTEGER DEFAULT 0,
    created_at   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS army (
    user_id INTEGER NOT NULL,
    unit    TEXT    NOT NULL,
    count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, unit)
);

CREATE TABLE IF NOT EXISTS defenses (
    user_id    INTEGER NOT NULL,
    structure  TEXT    NOT NULL,
    level      INTEGER NOT NULL DEFAULT 1,
    health     INTEGER NOT NULL DEFAULT 100,
    PRIMARY KEY (user_id, structure)
);

CREATE TABLE IF NOT EXISTS training (
    user_id   INTEGER PRIMARY KEY,
    unit      TEXT    NOT NULL,
    count     INTEGER NOT NULL,
    start_ts  INTEGER NOT NULL,
    finish_ts INTEGER NOT NULL,
    cost      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS battles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           INTEGER NOT NULL,
    attacker_id  INTEGER NOT NULL,
    defender_id  INTEGER NOT NULL,
    winner       INTEGER NOT NULL,
    loot         INTEGER NOT NULL DEFAULT 0,
    att_power    INTEGER NOT NULL DEFAULT 0,
    def_power    INTEGER NOT NULL DEFAULT 0,
    att_summary  TEXT DEFAULT '',
    def_summary  TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS clans (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT UNIQUE NOT NULL,
    leader_id  INTEGER NOT NULL,
    treasury   INTEGER NOT NULL DEFAULT 0,
    war_wins   INTEGER NOT NULL DEFAULT 0,
    war_losses INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT 0,
    group_id   INTEGER DEFAULT NULL,
    group_title TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS clan_members (
    clan_id   INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    role      TEXT NOT NULL DEFAULT 'member',
    joined_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (clan_id, user_id)
);

CREATE TABLE IF NOT EXISTS wars (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    clan_a    INTEGER NOT NULL,
    clan_b    INTEGER NOT NULL,
    points_a  INTEGER NOT NULL DEFAULT 0,
    points_b  INTEGER NOT NULL DEFAULT 0,
    start_ts  INTEGER NOT NULL,
    end_ts    INTEGER NOT NULL,
    status    TEXT NOT NULL DEFAULT 'active',
    winner_id INTEGER
);

CREATE TABLE IF NOT EXISTS inventory (
    user_id INTEGER NOT NULL,
    item    TEXT NOT NULL,
    qty     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, item)
);

CREATE TABLE IF NOT EXISTS buffs (
    user_id INTEGER NOT NULL,
    buff    TEXT NOT NULL,
    until   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, buff)
);

CREATE TABLE IF NOT EXISTS missions (
    user_id  INTEGER NOT NULL,
    key      TEXT NOT NULL,
    day      TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    claimed  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, key, day)
);

CREATE TABLE IF NOT EXISTS mines (
    user_id  INTEGER PRIMARY KEY,
    start_ts INTEGER NOT NULL,
    workers  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS growth (
    user_id INTEGER NOT NULL,
    ts      INTEGER NOT NULL,
    power   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_growth_user ON growth (user_id, ts);
"""


class DB:
    def __init__(self, path: str = "narbad.db"):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        # هوک اختیاری بعد از بازیابی هر کاربر (مثلاً هدیهٔ تست‌کننده‌ها).
        # هستهٔ مدیران (admin_core.setup) این هوک را ثبت می‌کند؛
        # برای کاربران عادی هیچ کاری انجام نمی‌دهد.
        self.user_hook = None

    # ------------------------------------------------------------ پایه
    async def init(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self._migrate()
        await self.conn.commit()

    async def _migrate(self) -> None:
        """افزودن ستون‌های جدید به دیتابیس‌های قدیمی."""
        cur = await self.conn.execute("PRAGMA table_info(users)")
        cols = {r[1] for r in await cur.fetchall()}
        await cur.close()
        if "clan_id" not in cols:
            await self.conn.execute("ALTER TABLE users ADD COLUMN clan_id INTEGER")
        if "tester_granted" not in cols:
            await self.conn.execute(
                "ALTER TABLE users ADD COLUMN tester_granted INTEGER DEFAULT 0")
        # مایگریشن اتحادیه‌ها: افزودن group_id برای محدودیت گروهی
        cur = await self.conn.execute("PRAGMA table_info(clans)")
        ccols = {r[1] for r in await cur.fetchall()}
        await cur.close()
        if "group_id" not in ccols:
            await self.conn.execute("ALTER TABLE clans ADD COLUMN group_id INTEGER DEFAULT NULL")
        if "group_title" not in ccols:
            await self.conn.execute("ALTER TABLE clans ADD COLUMN group_title TEXT DEFAULT ''")
        # مایگریشن سیستم نوین ارتش: «تکاور» (ranger) → «کماندو» (commando)
        await self.conn.execute(
            "UPDATE army SET unit = 'commando' "
            "WHERE unit = 'ranger' AND user_id NOT IN "
            "(SELECT user_id FROM army WHERE unit = 'commando')")
        await self.conn.execute("DELETE FROM army WHERE unit = 'ranger'")
        # مایگریشن سیستم نوین دفاع: انتقال سازه‌ها از جدول army به جدول اختصاصی defenses
        await self.conn.execute(
            "INSERT OR IGNORE INTO defenses (user_id, structure, level, health) "
            "SELECT user_id, "
            "CASE WHEN unit = 'castle' THEN 'air_defense' ELSE unit END, "
            "count, 100 FROM army "
            "WHERE unit IN ('wall', 'tower', 'castle', 'radar', 'air_defense') AND count > 0"
        )
        await self.conn.execute(
            "DELETE FROM army WHERE unit IN ('wall', 'tower', 'castle', 'radar', 'air_defense')"
        )
        # مایگریشن حذف سیستم قلمروها: جدول‌های مختص قلمرو حذف می‌شوند
        # (این داده‌ها فقط متعلق به سیستم قلمرو بودند و هیچ سیستم دیگری به آن‌ها وابسته نیست)
        await self.conn.execute("DROP TABLE IF EXISTS territories")
        await self.conn.execute("DROP TABLE IF EXISTS terr_contribs")

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def _fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        cur = await self.conn.execute(sql, params)
        row = await cur.fetchone()
        await cur.close()
        return dict(row) if row else None

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = await self.conn.execute(sql, params)
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]

    async def _execute(self, sql: str, params: tuple = ()) -> None:
        await self.conn.execute(sql, params)
        await self.conn.commit()

    # ------------------------------------------------------------ کاربران
    async def ensure_user(self, user_id: int, username: str = "",
                          first_name: str = "") -> dict:
        """ثبت‌نام خودکار + به‌روزرسانی نام کاربر."""
        user = await self._fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if user is None:
            await self._execute(
                "INSERT INTO users (user_id, username, first_name, coins, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, (username or "").lower(), first_name or "",
                 game.START_COINS, int(time.time())),
            )
            await self.set_unit(user_id, "soldier", game.START_SOLDIERS)
            user = await self._fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        else:
            if (username or "").lower() != (user.get("username") or "") or \
               (first_name or "") != (user.get("first_name") or ""):
                await self._execute(
                    "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                    ((username or "").lower(), first_name or "", user_id),
                )
                user["username"], user["first_name"] = (username or "").lower(), first_name or ""
        # هوک مدیران: هدیهٔ یک‌بارهٔ تست‌کننده‌ها (برای بقیه no-op است)
        if self.user_hook:
            user = await self.user_hook(user)
        return user

    async def get_user(self, user_id: int) -> dict | None:
        return await self._fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))

    async def update_user(self, user_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        await self._execute(
            f"UPDATE users SET {cols} WHERE user_id = ?",
            (*fields.values(), user_id),
        )

    async def find_by_username(self, username: str) -> dict | None:
        return await self._fetchone(
            "SELECT * FROM users WHERE username = ?", (username.lstrip("@").lower(),)
        )

    # ------------------------------------------------------------ ارتش
    async def get_army(self, user_id: int) -> dict[str, int]:
        rows = await self._fetchall(
            "SELECT unit, count FROM army WHERE user_id = ? AND count > 0", (user_id,)
        )
        army = {r["unit"]: r["count"] for r in rows}
        def_rows = await self._fetchall(
            "SELECT structure, level FROM defenses WHERE user_id = ? AND level > 0", (user_id,)
        )
        for r in def_rows:
            army[r["structure"]] = r["level"]
        return army

    async def set_unit(self, user_id: int, unit: str, count: int) -> None:
        if unit in game.DEFENSES or unit == "castle":
            struct = "air_defense" if unit == "castle" else unit
            await self.set_defense(user_id, struct, count, 100)
            return
        await self._execute(
            "INSERT INTO army (user_id, unit, count) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, unit) DO UPDATE SET count = excluded.count",
            (user_id, unit, max(0, count)),
        )

    async def all_users(self) -> list[dict]:
        return await self._fetchall("SELECT * FROM users")

    # ------------------------------------------------------------ پادگان آموزش (سیستم نوین ارتش)
    async def training_get(self, user_id: int) -> dict | None:
        """وضعیت فعلی آموزش (اگر زمانی باقی مانده باشد)."""
        return await self._fetchone(
            "SELECT * FROM training WHERE user_id = ? AND finish_ts > ?",
            (user_id, int(time.time())))

    async def training_start(self, user_id: int, unit: str, count: int,
                             start_ts: int, finish_ts: int, cost: int) -> None:
        await self._execute(
            "INSERT INTO training (user_id, unit, count, start_ts, finish_ts, cost) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET unit = excluded.unit, "
            "count = excluded.count, start_ts = excluded.start_ts, "
            "finish_ts = excluded.finish_ts, cost = excluded.cost",
            (user_id, unit, count, start_ts, finish_ts, cost),
        )

    async def training_clear(self, user_id: int) -> None:
        await self._execute("DELETE FROM training WHERE user_id = ?", (user_id,))

    async def settle_training(self, user_id: int) -> list[dict]:
        """تسویهٔ آموزش‌های کامل‌شده: یگان‌ها به ارتش اضافه و رکورد پاک می‌شود.

        خروجی: فهرست رکوردهای تسویه‌شده (خالی اگر چیزی کامل نشده باشد).
        همین‌جا «جلوگیری از ساخت آنی» اعمال می‌شود: تا finish_ts نرسیده باشد،
        یگانی به ارتش اضافه نمی‌شود.
        """
        rows = await self._fetchall(
            "SELECT * FROM training WHERE user_id = ? AND finish_ts <= ?",
            (user_id, int(time.time())))
        if not rows:
            return []
        army = await self.get_army(user_id)
        for r in rows:
            await self.set_unit(user_id, r["unit"],
                                army.get(r["unit"], 0) + r["count"])
            army[r["unit"]] = army.get(r["unit"], 0) + r["count"]
        await self._execute("DELETE FROM training WHERE user_id = ?", (user_id,))
        return rows

    # ------------------------------------------------------------ سازه‌های دفاعی پایگاه
    async def get_defenses(self, user_id: int) -> dict[str, dict[str, int]]:
        """خواندن همهٔ سازه‌های دفاعی فعال کاربر به همراه سطح و درصد سلامت."""
        rows = await self._fetchall(
            "SELECT structure, level, health FROM defenses WHERE user_id = ? AND level > 0",
            (user_id,),
        )
        return {r["structure"]: {"level": r["level"], "health": r["health"]} for r in rows}

    async def get_defense_structure(self, user_id: int, structure: str) -> dict | None:
        """اطلاعات یک سازهٔ خاص برای کاربر."""
        return await self._fetchone(
            "SELECT structure, level, health FROM defenses "
            "WHERE user_id = ? AND structure = ? AND level > 0",
            (user_id, structure),
        )

    async def set_defense(self, user_id: int, structure: str, level: int,
                          health: int = 100) -> None:
        """تنظیم یا حذف سطح/سلامت یک سازه دفاعی."""
        if level <= 0:
            await self._execute(
                "DELETE FROM defenses WHERE user_id = ? AND structure = ?",
                (user_id, structure),
            )
        else:
            await self._execute(
                "INSERT INTO defenses (user_id, structure, level, health) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, structure) DO UPDATE SET level = excluded.level, health = excluded.health",
                (user_id, structure, level, max(0, min(100, health))),
            )

    async def upgrade_defense(self, user_id: int, structure: str) -> int:
        """ارتقای سطح سازه به مرحلهٔ بعد (سلامت ۱۰۰٪ بازنشانی می‌شود)."""
        curr = await self.get_defense_structure(user_id, structure)
        new_lvl = (curr["level"] + 1) if curr else 1
        await self.set_defense(user_id, structure, new_lvl, 100)
        return new_lvl

    async def repair_defense(self, user_id: int, structure: str | None = None) -> None:
        """تعمیر یک سازه یا تمام سازه‌های دفاعی پایگاه تا ۱۰۰٪ سلامت."""
        if structure:
            await self._execute(
                "UPDATE defenses SET health = 100 WHERE user_id = ? AND structure = ?",
                (user_id, structure),
            )
        else:
            await self._execute(
                "UPDATE defenses SET health = 100 WHERE user_id = ?",
                (user_id,),
            )

    async def damage_defenses(self, user_id: int, damage_pct: int) -> dict[str, int]:
        """اعمال خسارت به سازه‌های دفاعی در نتیجهٔ نبرد (حداقل سلامت ۱۰٪)."""
        defs = await self.get_defenses(user_id)
        out = {}
        for s, data in defs.items():
            new_h = max(10, data["health"] - damage_pct)
            await self._execute(
                "UPDATE defenses SET health = ? WHERE user_id = ? AND structure = ?",
                (new_h, user_id, s),
            )
            out[s] = new_h
        return out

    async def defense_battle_history(self, user_id: int, limit: int = 5) -> list[dict]:
        """تاریخچهٔ آخرین نبردهای دفاعی پایگاه."""
        return await self._fetchall(
            "SELECT * FROM battles WHERE defender_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )

    # ------------------------------------------------------------ رده‌بندی
    async def top_power(self, limit: int = 10) -> list[dict]:
        """کاربران برتر بر اساس قدرت کل ارتش (یگان‌های تهاجمی)."""
        users = await self.all_users()
        rows = await self._fetchall("SELECT user_id, unit, count FROM army WHERE count > 0")
        armies: dict[int, dict[str, int]] = {}
        for r in rows:
            armies.setdefault(r["user_id"], {})[r["unit"]] = r["count"]

        ranked = []
        for u in users:
            power = game.attack_power(armies.get(u["user_id"], {}))
            ranked.append({"user": u, "power": power})
        ranked.sort(key=lambda x: x["power"], reverse=True)
        return ranked[:limit]

    async def top_coins(self, limit: int = 10) -> list[dict]:
        rows = await self._fetchall(
            "SELECT * FROM users ORDER BY coins DESC, level DESC LIMIT ?", (limit,)
        )
        return rows

    async def random_opponent(self, exclude_id: int) -> dict | None:
        return await self._fetchone(
            "SELECT * FROM users WHERE user_id != ? AND coins > 0 "
            "ORDER BY RANDOM() LIMIT 1",
            (exclude_id,),
        )

    # ------------------------------------------------------------ نبردها
    async def log_battle(self, ts: int, attacker_id: int, defender_id: int,
                         winner: int, loot: int, att_power: int, def_power: int,
                         att_summary: str, def_summary: str) -> None:
        await self._execute(
            "INSERT INTO battles (ts, attacker_id, defender_id, winner, loot, "
            "att_power, def_power, att_summary, def_summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, attacker_id, defender_id, winner, loot, att_power, def_power,
             att_summary, def_summary),
        )

    async def battle_history(self, user_id: int, limit: int = 10) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM battles WHERE attacker_id = ? OR defender_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, user_id, limit),
        )

    # ------------------------------------------------------------ اتحادیه
    async def create_clan(self, name: str, leader_id: int, group_id: int | None = None, group_title: str | None = None) -> dict:
        cur = await self.conn.execute(
            "INSERT INTO clans (name, leader_id, created_at, group_id, group_title) VALUES (?, ?, ?, ?, ?)",
            (name.strip(), leader_id, int(time.time()), group_id, group_title or ""),
        )
        await self.conn.commit()
        clan_id = cur.lastrowid
        await self.conn.execute(
            "INSERT INTO clan_members (clan_id, user_id, role, joined_at) "
            "VALUES (?, ?, 'leader', ?)",
            (clan_id, leader_id, int(time.time())),
        )
        await self.conn.commit()
        await self.update_user(leader_id, clan_id=clan_id)
        return await self.get_clan(clan_id)

    async def get_clan(self, clan_id: int) -> dict | None:
        return await self._fetchone("SELECT * FROM clans WHERE id = ?", (clan_id,))

    async def clan_by_name(self, name: str) -> dict | None:
        return await self._fetchone("SELECT * FROM clans WHERE name = ?",
                                    (name.strip(),))

    async def clan_members(self, clan_id: int) -> list[dict]:
        return await self._fetchall(
            "SELECT COALESCE(u.user_id, cm.user_id) AS user_id, "
            "COALESCE(u.username, '') AS username, "
            "COALESCE(u.first_name, '') AS first_name, "
            "COALESCE(u.coins, 0) AS coins, COALESCE(u.level, 1) AS level, "
            "COALESCE(u.xp, 0) AS xp, cm.role, cm.joined_at "
            "FROM clan_members cm LEFT JOIN users u ON u.user_id = cm.user_id "
            "WHERE cm.clan_id = ? ORDER BY cm.joined_at", (clan_id,),
        )

    async def member_ids(self, clan_id: int) -> list[int]:
        rows = await self._fetchall(
            "SELECT user_id FROM clan_members WHERE clan_id = ?", (clan_id,))
        return [r["user_id"] for r in rows]

    async def all_clans(self) -> list[dict]:
        return await self._fetchall(
            "SELECT c.*, (SELECT COUNT(*) FROM clan_members m WHERE m.clan_id = c.id) "
            "AS members FROM clans c ORDER BY members DESC, c.id",
        )

    async def update_clan(self, clan_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        await self._execute(
            f"UPDATE clans SET {cols} WHERE id = ?", (*fields.values(), clan_id))

    async def add_member(self, clan_id: int, user_id: int) -> None:
        await self._execute(
            "INSERT INTO clan_members (clan_id, user_id, role, joined_at) "
            "VALUES (?, ?, 'member', ?)",
            (clan_id, user_id, int(time.time())),
        )
        await self.update_user(user_id, clan_id=clan_id)

    async def remove_member(self, user_id: int) -> dict | None:
        """حذف عضو (و در صورت نیاز ارتقا/تسویهٔ رهبری)."""
        row = await self._fetchone(
            "SELECT clan_id, role FROM clan_members WHERE user_id = ?", (user_id,))
        if not row:
            return None
        clan_id = row["clan_id"]
        was_leader = row["role"] == "leader"
        members = await self.clan_members(clan_id)
        await self._execute("DELETE FROM clan_members WHERE user_id = ?", (user_id,))
        await self.update_user(user_id, clan_id=None)

        if new_leader := next((m for m in members
                               if m["user_id"] != user_id), None):
            if was_leader:
                await self._execute(
                    "UPDATE clan_members SET role = 'leader' WHERE clan_id = ? "
                    "AND user_id = ?", (clan_id, new_leader["user_id"]))
                await self.update_clan(clan_id, leader_id=new_leader["user_id"])
        else:
            # اتحادیه خالی شد → انحلال
            await self._execute("DELETE FROM clans WHERE id = ?", (clan_id,))
            await self._execute(
                "UPDATE wars SET status = 'finished', winner_id = NULL "
                "WHERE status = 'active' AND (clan_a = ? OR clan_b = ?)",
                (clan_id, clan_id))
            return {"disbanded": True, "clan_id": clan_id}
        return {"disbanded": False, "clan_id": clan_id}

    async def clan_power(self, clan_id: int) -> int:
        members = await self.clan_members(clan_id)
        total = 0
        for m in members:
            army = await self.get_army(m["user_id"])
            total += game.attack_power(army)
        return total

    async def clan_level(self, clan_id: int) -> int:
        members = await self.clan_members(clan_id)
        return 1 + sum(m["level"] for m in members) // 15

    async def random_enemy_clan(self, exclude_clan_id: int) -> dict | None:
        return await self._fetchone(
            "SELECT c.*, (SELECT COUNT(*) FROM clan_members m WHERE m.clan_id = c.id) "
            "AS members FROM clans c WHERE c.id != ? AND members > 0 "
            "AND NOT EXISTS (SELECT 1 FROM wars w WHERE w.status = 'active' "
            "AND (w.clan_a = c.id OR w.clan_b = c.id)) "
            "ORDER BY RANDOM() LIMIT 1",
            (exclude_clan_id,),
        )

    # ------------------------------------------------------------ جنگ اتحادیه‌ها
    async def create_war(self, clan_a: int, clan_b: int) -> dict:
        now = int(time.time())
        cur = await self.conn.execute(
            "INSERT INTO wars (clan_a, clan_b, start_ts, end_ts) VALUES (?, ?, ?, ?)",
            (clan_a, clan_b, now, now + game.WAR_DURATION),
        )
        await self.conn.commit()
        return await self.get_war(cur.lastrowid)

    async def get_war(self, war_id: int) -> dict | None:
        war = await self._fetchone("SELECT * FROM wars WHERE id = ?", (war_id,))
        if war:
            war = await self._settle_if_expired(war)
        return war

    async def active_war_for_clan(self, clan_id: int) -> dict | None:
        war = await self._fetchone(
            "SELECT * FROM wars WHERE status = 'active' AND (clan_a = ? OR clan_b = ?)"
            " ORDER BY id DESC LIMIT 1", (clan_id, clan_id))
        if war:
            war = await self._settle_if_expired(war)
        return war

    async def _settle_if_expired(self, war: dict) -> dict:
        if war["status"] != "active" or war["end_ts"] > time.time():
            return war
        winner = None
        if war["points_a"] != war["points_b"]:
            winner = war["clan_a"] if war["points_a"] > war["points_b"] else war["clan_b"]
        await self._execute(
            "UPDATE wars SET status = 'finished', winner_id = ? WHERE id = ?",
            (winner, war["id"]))
        if winner:
            loser = war["clan_b"] if winner == war["clan_a"] else war["clan_a"]
            l_clan = await self.get_clan(loser)
            w_clan = await self.get_clan(winner)
            if l_clan and w_clan:
                cut = round(l_clan["treasury"] * game.WAR_TREASURY_CUT)
                await self.update_clan(loser, treasury=l_clan["treasury"] - cut)
                await self.update_clan(winner, treasury=w_clan["treasury"] + cut)
                await self.update_clan(
                    winner, war_wins=w_clan.get("war_wins", 0) + 1)
                await self.update_clan(
                    loser, war_losses=l_clan.get("war_losses", 0) + 1)
                # جایزه به اعضای اتحادیهٔ برنده
                for mid in await self.member_ids(winner):
                    u = await self.get_user(mid)
                    if not u:
                        continue
                    xp, lvl, gained, reward = game.add_xp(
                        u["xp"], u["level"], game.WAR_BONUS_XP)
                    await self.update_user(
                        mid, coins=u["coins"] + game.WAR_BONUS_COINS,
                        xp=xp, level=lvl)
        return await self._fetchone("SELECT * FROM wars WHERE id = ?", (war["id"],))

    async def add_war_points(self, war_id: int, side: str, points: int) -> None:
        col = "points_a" if side == "A" else "points_b"
        await self._execute(
            f"UPDATE wars SET {col} = {col} + ? WHERE id = ?", (points, war_id))

    # ------------------------------------------------------------ موجودی و بافت‌ها
    async def inv_get(self, user_id: int) -> dict[str, int]:
        rows = await self._fetchall(
            "SELECT item, qty FROM inventory WHERE user_id = ? AND qty > 0", (user_id,))
        return {r["item"]: r["qty"] for r in rows}

    async def inv_add(self, user_id: int, item: str, qty: int) -> None:
        await self._execute(
            "INSERT INTO inventory (user_id, item, qty) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, item) DO UPDATE SET qty = qty + excluded.qty",
            (user_id, item, qty),
        )

    async def inv_take(self, user_id: int, item: str, qty: int = 1) -> None:
        await self._execute(
            "UPDATE inventory SET qty = qty - ? WHERE user_id = ? AND item = ?",
            (qty, user_id, item),
        )

    async def buffs_active(self, user_id: int) -> dict[str, int]:
        now = int(time.time())
        rows = await self._fetchall(
            "SELECT buff, until FROM buffs WHERE user_id = ? AND until > ?",
            (user_id, now))
        return {r["buff"]: r["until"] for r in rows}

    async def set_buff(self, user_id: int, buff: str, until: int) -> None:
        await self._execute(
            "INSERT INTO buffs (user_id, buff, until) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, buff) DO UPDATE SET until = excluded.until",
            (user_id, buff, until),
        )

    # ------------------------------------------------------------ مأموریت‌ها
    def _today(self) -> str:
        return time.strftime("%Y-%m-%d")

    async def missions_today(self, user_id: int) -> dict[str, dict]:
        day = self._today()
        rows = await self._fetchall(
            "SELECT * FROM missions WHERE user_id = ? AND day = ?", (user_id, day))
        return {r["key"]: r for r in rows}

    async def bump_mission(self, user_id: int, key: str, amount: int = 1) -> None:
        day = self._today()
        await self._execute(
            "INSERT INTO missions (user_id, key, day, progress, claimed) "
            "VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT(user_id, key, day) DO UPDATE SET progress = progress + excluded.progress",
            (user_id, key, day, amount),
        )

    async def claim_mission(self, user_id: int, key: str) -> dict | None:
        """خواندن وضعیت فعلی مأموریت (برای نمایش/اعتبارسنجی)."""
        day = self._today()
        row = await self._fetchone(
            "SELECT * FROM missions WHERE user_id = ? AND key = ? AND day = ?",
            (user_id, key, day))
        if not row:
            return None
        return row

    async def claim_mission_atomic(self, user_id: int, key: str,
                                   target: int) -> bool:
        """ثبت اتمیِ دریافت جایزه.

        فقط اگر مأموریت در همین روز «کامل» باشد و هنوز گرفته نشده باشد
        (claimed=0) پرچم claimed را ۱ می‌کند و True برمی‌گرداند.
        این روش جلوی جایزهٔ دوباره در لمس دوبارهٔ دکمه یا رقابت هم‌زمان
        چند درخواست را می‌گیرد.
        """
        day = self._today()
        cur = await self.conn.execute(
            "UPDATE missions SET claimed = 1 "
            "WHERE user_id = ? AND key = ? AND day = ? "
            "AND claimed = 0 AND progress >= ?",
            (user_id, key, day, target),
        )
        await self.conn.commit()
        rowcount = cur.rowcount
        await cur.close()
        return rowcount > 0

    async def mark_mission_claimed(self, user_id: int, key: str) -> None:
        """نشان‌گذاری دستیِ دریافت‌شده (سازگاری با کدهای قبلی)."""
        await self._execute(
            "UPDATE missions SET claimed = 1 WHERE user_id = ? AND key = ? AND day = ?",
            (user_id, key, self._today()),
        )

    # ------------------------------------------------------------ ریست مدیران
    async def reset_player(self, user_id: int) -> dict | None:
        """ریست کامل حساب (برای حساب‌های تست).

        همهٔ چیزهای یک بازیکن به حالت اولیه برمی‌گردد:
        سکه/سطح/تجربه/انرژی/آمار/سپر + ارتش (۵ سرباز) + پاک‌شدن آیتم‌ها،
        بافت‌ها، مأموریت‌ها، معدن، رشد و خروج از اتحادیه.
        پرچم tester_granted هم صفر می‌شود تا هدیهٔ تست دوباره فعال شود.
        بازیکنان عادی می‌توانند از همین مسیر ریست شوند (اختیار مدیر).
        """
        # خروج از اتحادیه (در صورت عضویت؛ برای بقیه no-op)
        await self.remove_member(user_id)
        # بازنشانی فیلدهای اصلی
        await self._execute(
            "UPDATE users SET coins = ?, level = 1, xp = 0, energy = ?, "
            "energy_ts = ?, wins = 0, losses = 0, def_wins = 0, def_losses = 0, "
            "last_daily = 0, shield_until = 0, tester_granted = 0 "
            "WHERE user_id = ?",
            (game.START_COINS, game.MAX_ENERGY, int(time.time()), user_id),
        )
        # ارتش: پاک و ۵ سرباز اولیه
        await self._execute("DELETE FROM army WHERE user_id = ?", (user_id,))
        await self.set_unit(user_id, "soldier", game.START_SOLDIERS)
        # پاک‌سازی بخش‌های جانبی
        await self._execute("DELETE FROM defenses WHERE user_id = ?", (user_id,))
        await self._execute("DELETE FROM training WHERE user_id = ?", (user_id,))
        await self._execute("DELETE FROM inventory WHERE user_id = ?", (user_id,))
        await self._execute("DELETE FROM buffs WHERE user_id = ?", (user_id,))
        await self._execute("DELETE FROM missions WHERE user_id = ?", (user_id,))
        await self._execute("DELETE FROM mines WHERE user_id = ?", (user_id,))
        await self._execute("DELETE FROM growth WHERE user_id = ?", (user_id,))
        return await self.get_user(user_id)

    # ------------------------------------------------------------ معدن
    async def mine_start(self, user_id: int, start_ts: int, workers: int) -> None:
        await self._execute(
            "INSERT INTO mines (user_id, start_ts, workers) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET start_ts = excluded.start_ts, "
            "workers = excluded.workers",
            (user_id, start_ts, workers),
        )

    async def mine_get(self, user_id: int) -> dict | None:
        return await self._fetchone("SELECT * FROM mines WHERE user_id = ?", (user_id,))

    async def mine_clear(self, user_id: int) -> None:
        await self._execute("DELETE FROM mines WHERE user_id = ?", (user_id,))

    # ------------------------------------------------------------ رشد
    async def growth_snapshot(self, user_id: int, power: int) -> None:
        now = int(time.time())
        await self._execute(
            "INSERT INTO growth (user_id, ts, power) VALUES (?, ?, ?)", (user_id, now, power))
        # نگه‌داشتن فقط ۹۰ روز اخیر
        await self._execute(
            "DELETE FROM growth WHERE user_id = ? AND ts < ?",
            (user_id, now - 90 * 86400))

    async def growth_history(self, user_id: int, limit: int = 30) -> list[dict]:
        rows = await self._fetchall(
            "SELECT * FROM growth WHERE user_id = ? ORDER BY ts ASC LIMIT ?",
            (user_id, limit))
        # آخرین N نقطه
        return rows[-limit:]
