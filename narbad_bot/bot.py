"""ورودی اصلی ربات نبردگاه — اجرا: python -m narbad_bot.bot"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from . import (admin_core, admin_panel, config, handlers, handlers_clan,
               handlers_missions, handlers_shop, handlers_territory, hooks,
               menu)
from .db import DB

# فقط دستورات خاص که نیاز به ورودی کاربر دارند یا برای دکمه مناسب نیستند
# همه قابلیت‌های عادی بازی از طریق منوی پایین (ReplyKeyboard) در دسترس هستند
# /admin عمداً از لیست عمومی حذف شده — فقط توسعه‌دهندگان با تایپ دستی به آن دسترسی دارند
COMMANDS = [
    ("start", "شروع بازی و ساخت حساب 🎖"),
    ("menu", "نمایش منوی اصلی 🎮"),
    ("hidemenu", "پنهان کردن منو 🚫"),
    ("attack", "حمله تصادفی 🎲"),
    ("gift", "هدیه سکه به بازیکن دیگر 🎁"),
    ("myid", "نمایش شناسه عددی شما 🆔"),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)

async def main() -> None:
    if not config.BOT_TOKEN:
        print("❌ BOT_TOKEN تنظیم نشده است!")
        print("   ۱) در تلگرام به @BotFather پیام بده و /newbot بزن")
        print("   ۲) توکن را در فایل .env کنار پروژه بگذار:")
        print("      BOT_TOKEN=123456:ABC-DEF...")
        return

    bot = Bot(config.BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    db = DB(config.DB_PATH)
    await db.init()
    for module in (handlers, handlers_shop, handlers_missions,
                   handlers_clan, handlers_territory, menu):
        module.setup(db)
    hooks.setup(db)
    admin_core.setup(db)
    admin_panel.setup(db)
    dp.include_router(handlers.router)
    dp.include_router(handlers_shop.router)
    dp.include_router(handlers_missions.router)
    dp.include_router(handlers_clan.router)
    dp.include_router(handlers_territory.router)
    dp.include_router(menu.router)
    dp.include_router(admin_panel.router)

    try:
        await bot.get_me()
        logging.info("اتصال به تلگرام برقرار شد ✅")
    except Exception as exc:  # noqa: BLE001
        logging.error("اتصال برقرار نشد (توکن را بررسی کن): %s", exc)
        return

    await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in COMMANDS])
    logging.info("ربات نبردگاه در حال اجراست... ⚔️")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("ربات متوقف شد.")
