"""تنظیمات ربات — از فایل .env خوانده می‌شود."""
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
DB_PATH: str = os.getenv("DB_PATH", "narbad.db")
