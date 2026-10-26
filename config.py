import os
from pathlib import Path
from dotenv import load_dotenv

# .env faylini yuklash
load_dotenv()

# Telegram Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Asosiy papkalar
BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Cookies fayli (ixtiyoriy, agar Instagram cheklov o'rnatsa kerak bo'ladi)
COOKIES_FILE = BASE_DIR / "cookies.txt"

# Telegram Bot API maksimal fayl hajmi: 50 MB (baytlarda)
MAX_FILE_SIZE = 50 * 1024 * 1024


# Google Gemini AI sozlamalari
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
