import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Установите BOT_TOKEN в .env (скопируйте из .env.example)")

# Папка для временных загрузок (очищается после отправки)
DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR", "./downloads"))
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Лимит размера файла для отправки в чат (50 MB — лимит Telegram для ботов)
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(50 * 1024 * 1024)))

# Прокси для yt-dlp (если YouTube недоступен в регионе). Примеры:
#   http://127.0.0.1:7890
#   socks5://user:pass@host:1080
YTDL_PROXY = os.getenv("YTDL_PROXY", "").strip() or None

# Таймаут отправки файла в Telegram (секунды). Увеличь при медленном интернете.
UPLOAD_TIMEOUT = int(os.getenv("UPLOAD_TIMEOUT", "300"))

# Поддерживаемые хосты (можно расширить)
SUPPORTED_URL_PATTERNS = ("youtube.com", "youtu.be", "www.youtube.com")
