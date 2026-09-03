"""دموی نبرد در ترمینال — بدون نیاز به تلگرام.

دو لشکر تصادفی می‌سازد، نبرد را شبیه‌سازی می‌کند و قابلیت‌های جدید
(بافت‌ها، مأموریت‌ها) را نشان می‌دهد:

    python simulate.py
"""
from narbad_bot import game


def random_army(budget: int) -> dict[str, int]:
    army = {"soldier": 10 + budget // 300}
    for key in list(game.UNITS):
        if key == "soldier" or budget < game.UNITS[key]["cost"]:
            continue
        count = budget // game.UNITS[key]["cost"]
        if count:
            army[key] = max(1, min(count, 5))
    return army


def show(army: dict[str, int]) -> str:
    parts = [f"{game.DISP[k]['emoji']}×{game.fa(c)}" for k, c in sorted(army.items())]
    return " + ".join(parts) if parts else "—"


def main() -> None:
    print("=" * 52)
    print("        ⚔️  نبردگاه — شبیه‌ساز نبرد ترمینال  ⚔️")
    print("=" * 52)

    red = random_army(50_000)
    blue = random_army(40_000)
    red_struct = {"wall": 6, "castle": 2}
    blue_struct = {"wall": 4}

    print(f"\n🔴 ارتش سرخ  : {show(red)}")
    print(f"   دفاع سرخ  : {show(red_struct)}")
    print(f"🔵 ارتش آبی  : {show(blue)}")
    print(f"   دفاع آبی  : {show(blue_struct)}")

    red_power = game.attack_power(red)
    blue_power = game.attack_power(blue)
    red_def = game.defense_power(red, red_struct)
    blue_def = game.defense_power(blue, blue_struct)
    print(f"\n⚔️ قدرت حمله سرخ : {game.fa(red_power)}   🛡 دفاع: {game.fa(red_def)}")
    print(f"⚔️ قدرت حمله آبی : {game.fa(blue_power)}   🛡 دفاع: {game.fa(blue_def)}")

    # آبی با طلسم پیروزی (+۲۰٪) به سرخ حمله می‌کند
    print("\n✨ آبی «طلسم پیروزی 🍀» استفاده کرد (+۲۰٪ قدرت)!")
    print("💥 آبی به پایگاه سرخ حمله می‌کند...")
    res = game.simulate_battle(blue, red, red_struct, 12_000, 9_000, att_mult=1.2)

    winner = "آبی" if res["winner"] == "attacker" else "سرخ"
    print(f"\n🏆 برنده: {winner}!")
    print(f"   تلفات آبی: {game.cas_text(res['att_cas'])}")
    print(f"   تلفات سرخ: {game.cas_text(res['def_cas'])}")
    if res["winner"] == "attacker":
        print(f"💰 غنیمت آبی: {game.fa(res['loot'])} سکه")
    else:
        print(f"💸 آبی {game.fa(res['loot'])} سکه از دست داد")
    print(f"⭐ تجربهٔ آبی: +{game.fa(res['att_xp'])} | سرخ: +{game.fa(res['def_xp'])}")


    print("\n🎯 مأموریت روزانهٔ نمونه:")
    m = game.MISSIONS["win2"]
    print(f"   {m['emoji']} {m['name']} — {game.fa(m['target'])} پیروزی → "
          f"{game.fa(m['coins'])}💰 + {game.fa(m['xp'])}⭐")

    print("\n⛏ معدن (۱۰ سرباز، ۲ ساعت):")
    print(f"   استخراج: {game.fa(game.mine_gain(10, 2 * 3600))} سکه")

    print("\n🏰 جنگ اتحادیه (برنده):")
    print(f"   امتیاز یک پیروزی با قدرت ۲۶٬۰۰۰: "
          f"{game.fa(game.war_points(True, 26_000))} امتیاز")

    print("\n" + "=" * 52)
    print("برای اجرای نسخهٔ اصلی تلگرام: python -m narbad_bot.bot")
    print("=" * 52)


if __name__ == "__main__":
    main()
