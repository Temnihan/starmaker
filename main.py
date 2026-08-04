import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import datetime
# for you tube
import yt_dlp
# для базы данных
import sqlite3
# ===== 1. Токен бота =====
import os
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
if not TOKEN:
    print("❌ ОШИБКА: Токен не найден! Установи TELEGRAM_TOKEN в .env", flush=True)
    exit(1)
bot = telebot.TeleBot(TOKEN)

# Проверка ffmpeg
import shutil
if not shutil.which("ffmpeg"):
    print("⚠️ ВНИМАНИЕ: ffmpeg не установлен! Конвертация аудио не будет работать", flush=True)

# ===== Временное хранилище для recordingId (связываем с chat_id) =====
user_data = {}
USER_DATA_TIMEOUT = 600  # 10 минут

def cleanup_user_data():
    """Удаляет записи старше 10 минут."""
    now = datetime.datetime.now()
    to_delete = []
    for chat_id, data in user_data.items():
        if isinstance(data, dict) and 'timestamp' in data:
            if (now - data['timestamp']).seconds > USER_DATA_TIMEOUT:
                to_delete.append(chat_id)
        elif isinstance(data, str):
            # Старый формат без timestamp — удаляем
            to_delete.append(chat_id)
    for chat_id in to_delete:
        user_data.pop(chat_id, None)
SUPPORT_TEXT = "Ваша поддержка — лучшая благодарность. \n🧡)"
ADMIN_CHAT_ID = 158043939  # Твой Telegram ID для уведомлений
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.db')


# ===== Функции работы с базой данных =====
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_or_create_user(user_id, username=None):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    if not user:
        c.execute("INSERT INTO users (user_id, username, credits) VALUES (?, ?, 3)",
                  (user_id, username))
        conn.commit()
        c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        user = c.fetchone()
    conn.close()
    return user

def use_credit(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits - 1, total_downloads = total_downloads + 1 WHERE user_id=? AND credits > 0", (user_id,))
    changed = c.rowcount
    conn.commit()
    conn.close()
    return changed > 0

def add_credits(user_id, amount=3):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET credits = credits + ?, shares = shares + 1 WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def record_download(user_id, platform, fmt, title, file_size_mb, url):
    conn = get_db()
    c = conn.cursor()
    c.execute("""INSERT INTO downloads (user_id, platform, format, title, file_size_mb, url)
                 VALUES (?, ?, ?, ?, ?, ?)""",
              (user_id, platform, fmt, title, file_size_mb, url))
    c.execute("UPDATE users SET total_mb = total_mb + ? WHERE user_id=?", (file_size_mb, user_id))
    conn.commit()
    conn.close()

def get_user_credits(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT credits FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row['credits'] if row else 0


# ===== Функция скачивания YouTube =====
def download_youtube(url, format_type="video"):
    """Скачивает YouTube видео/аудио через yt_dlp. Возвращает (путь, название) или (None, None)."""
    ydl_opts = {
        'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best' if format_type == "video" else 'bestaudio/best',
        'outtmpl': '/tmp/yt_%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4' if format_type == "video" else None,
    }
    if format_type == "audio":
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '64',
        }]
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            ext = 'mp3' if format_type == "audio" else info.get('ext', 'mp4')
            filepath = f"/tmp/yt_{info['id']}.{ext}"
            title = info.get('title', 'YouTube Video')
            return filepath, title
    except Exception as e:
        print(f"Ошибка скачивания YouTube: {e}")
        return None, None


# ===== 2. Функция, которая вытаскивает recordingId из текста =====
def download_tiktok(url):
    """Скачивает TikTok видео через cookies. Возвращает (путь, название) или (None, None)."""
    try:
        import re
        
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        })
        
        # Получаем cookies
        session.get('https://www.tiktok.com/', timeout=10)
        
        # Разрешаем короткую ссылку
        resp = session.get(url, timeout=10, allow_redirects=True)
        final_url = resp.url
        
        # Получаем страницу видео
        resp = session.get(final_url, timeout=10)
        
        # Извлекаем video URL
        video_urls = re.findall(r'"playAddr"\s*:\s*"([^"]+)"', resp.text)
        if not video_urls:
            video_urls = re.findall(r'"downloadAddr"\s*:\s*"([^"]+)"', resp.text)
        
        if not video_urls:
            return None, None
        
        video_url = video_urls[0].encode().decode('unicode_escape')
        
        # Скачиваем с cookies
        video_resp = session.get(
            video_url,
            headers={'Referer': 'https://www.tiktok.com/', 'Origin': 'https://www.tiktok.com'},
            timeout=30,
        )
        
        if video_resp.status_code != 200:
            return None, None
        
        # Сохраняем
        video_id = re.search(r'/video/(\d+)', final_url)
        video_id = video_id.group(1) if video_id else 'tiktok'
        filepath = f'/tmp/tiktok_{video_id}.mp4'
        with open(filepath, 'wb') as f:
            f.write(video_resp.content)
        
        return filepath, f'TikTok {video_id}'
    except Exception as e:
        print(f"Ошибка скачивания TikTok: {e}")
        return None, None

def extract_recording_id(text):
    """Ищет в тексте recordingId=число и возвращает число или None."""
    match = re.search(r'recordingId=(\d+)', text)
    return match.group(1) if match else None

def resolve_starmaker_link(text):
    """Разрешает короткую ссылку StarMaker (onelink.me) и возвращает recordingId."""
    match = re.search(r'(https?://starmaker\.onelink\.me/\S+)', text)
    if not match:
        return None
    url = match.group(1)
    try:
        resp = requests.get(url, allow_redirects=True, timeout=10, stream=True)
        final_url = resp.url
        rec_match = re.search(r'recordingId=(\d+)', final_url)
        if rec_match:
            return rec_match.group(1)
    except Exception as e:
        print(f"Ошибка разрешения ссылки: {e}")
    return None

def resolve_likee_link(text):
    """Разрешает короткую ссылку Likee (l.likee.video) и возвращает полный URL."""
    match = re.search(r'(https?://l\.likee\.video/\S+)', text)
    if not match:
        return None
    url = match.group(1)
    try:
        resp = requests.get(url, allow_redirects=True, timeout=10, stream=True)
        final_url = resp.url
        # Проверяем что это Likee видео
        if 'likee.video' in final_url and ('/video/' in final_url or '/v/' in final_url):
            return final_url
    except Exception as e:
        print(f"Ошибка разрешения Likee ссылки: {e}")
    return None

def is_valid_youtube_url(text):
    """Проверяет что это настоящая YouTube ссылка."""
    pattern = r'^https?://(www\.)?(youtube\.com|youtu\.be)/'
    return bool(re.match(pattern, text.strip()))

def is_valid_rutube_url(text):
    """Проверяет что это настоящая Rutube ссылка."""
    pattern = r'^https?://(www\.)?rutube\.ru/'
    return bool(re.match(pattern, text.strip()))

def is_valid_likee_url(text):
    """Проверяет что это настоящая Likee ссылка."""
    pattern = r'^https?://(www\.)?(likee\.video|l\.likee\.video|likee\.video)/'
    return bool(re.match(pattern, text.strip()))

def is_valid_tiktok_url(text):
    """Проверяет что это настоящая TikTok ссылка."""
    pattern = r'^https?://(www\.)?(tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)/'
    return bool(re.match(pattern, text.strip()))


# ===== 3. Функция скачивания файла по ссылке =====
def download_file(url):
    """Скачивает файл с повторными попытками. Возвращает байты или None."""
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                return response.content
            elif response.status_code == 404:
                return None  # Файл не существует — не повторяем
        except Exception as e:
            print(f"Попытка {attempt+1}/3 не удалась: {e}")
            if attempt < 2:
                import time
                time.sleep(2)
    return None

# Лимиты Telegram
MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50 МБ
MAX_AUDIO_SIZE = 20 * 1024 * 1024  # 20 МБ


# ===== 4. Обработчик команды /start =====
@bot.message_handler(commands=['start'])
def start_message(message):
    user = get_or_create_user(message.from_user.id, message.from_user.username)
    bot.reply_to(message, "*Просто вставь сюда ссылку*", parse_mode="Markdown")


# ===== 4.1 Обработчик команды /share =====
@bot.message_handler(commands=['share'])
def share_message(message):
    keyboard = InlineKeyboardMarkup(row_width=1)
    btn_share = InlineKeyboardButton("📢 Поделиться ботом", url="https://t.me/share/url?url=https://t.me/freeStarmakerBot&text=Попробуй этого бота для скачивания видео и музыки!")
    btn_done = InlineKeyboardButton("✅ Я поделился! (+3 скачивания)", callback_data="share_done")
    keyboard.add(btn_share, btn_done)
    bot.reply_to(message,
        "📢 Поделись ботом с друзьями!\n\n"
        "1. Нажми «Поделиться ботом»\n"
        "2. Выбери кому отправить\n"
        "3. Вернись сюда и нажми «Я поделился!»\n\n"
        "🎁 Получишь +3 скачивания!",
        reply_markup=keyboard)


# ===== 5. Обработчик текстовых сообщений =====
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text
    rec_id = extract_recording_id(text)
    if not rec_id:
        rec_id = resolve_starmaker_link(text)
    if not text:
        bot.reply_to(message, "Пришли ссылку ")
        return

    # Регистрируем/получаем пользователя и проверяем кредиты
    user = get_or_create_user(message.from_user.id, message.from_user.username)
    if user['credits'] <= 0:
        keyboard = InlineKeyboardMarkup(row_width=1)
        btn_share = InlineKeyboardButton("📢 Поделиться ботом", url="https://t.me/share/url?url=https://t.me/freeStarmakerBot&text=Попробуй этого бота для скачивания видео и музыки!")
        btn_done = InlineKeyboardButton("✅ Я поделился! (+3 скачивания)", callback_data="share_done")
        keyboard.add(btn_share, btn_done)
        bot.reply_to(message,
            "😔 У тебя закончились скачивания!\n\n"
            "📢 Поделись ботом с друзьями, чтобы получить +3:\n"
            "1. Нажми «Поделиться ботом»\n"
            "2. Выбери кому отправить\n"
            "3. Вернись сюда и нажми «Я поделился!»\n\n"
            "Или подожди завтра (лимит сбрасывается)",
            reply_markup=keyboard)
        return

    # --- ПРОВЕРКА НА YOUTUBE ---
    if is_valid_youtube_url(text):
        # Уведомление админу
        try:
            user_name = message.from_user.first_name or ""
            username = message.from_user.username or "нет username"
            bot.send_message(ADMIN_CHAT_ID,
                f"🔔 YouTube запрос!\n👤 {user_name} (@{username})\n🆔 ID: {message.from_user.id}\n🔗 {text[:100]}")
        except Exception as e:
            print(f"Ошибка отправки уведомления: {e}")

        keyboard = InlineKeyboardMarkup(row_width=2)
        btn_video = InlineKeyboardButton("🎬 Видео (MP4)", callback_data="yt_video")
        btn_audio = InlineKeyboardButton("🎵 Аудио (MP3)", callback_data="yt_audio")
        btn_support = InlineKeyboardButton("❤️ На чай  10 руб", callback_data="support")
        keyboard.add(btn_video, btn_audio, btn_support)
        bot.reply_to(message, "🎬 YouTube обнаружен! Выбери формат:", reply_markup=keyboard)
        cleanup_user_data()
        user_data[message.chat.id] = {"type": "youtube", "url": text, "timestamp": datetime.datetime.now()}
        return

    # --- ПРОВЕРКА НА RUTUBE ---
    if is_valid_rutube_url(text):
        # Уведомление админу
        try:
            user_name = message.from_user.first_name or ""
            username = message.from_user.username or "нет username"
            bot.send_message(ADMIN_CHAT_ID,
                f"🔔 Rutube запрос!\n👤 {user_name} (@{username})\n🆔 ID: {message.from_user.id}\n🔗 {text[:100]}")
        except Exception as e:
            print(f"Ошибка отправки уведомления: {e}")

        keyboard = InlineKeyboardMarkup(row_width=2)
        btn_video = InlineKeyboardButton("🎬 Видео (MP4)", callback_data="yt_video")
        btn_audio = InlineKeyboardButton("🎵 Аудио (MP3)", callback_data="yt_audio")
        btn_support = InlineKeyboardButton("❤️ На чай  10 руб", callback_data="support")
        keyboard.add(btn_video, btn_audio, btn_support)
        bot.reply_to(message, "🎬 Rutube обнаружен! Выбери формат:", reply_markup=keyboard)
        cleanup_user_data()
        user_data[message.chat.id] = {"type": "rutube", "url": text, "timestamp": datetime.datetime.now()}
        return

    # --- ПРОВЕРКА НА LIKEE ---
    # Разрешаем короткие ссылки Likee
    likee_url = resolve_likee_link(text)
    if likee_url:
        text = likee_url
    if is_valid_likee_url(text):
        # Уведомление админу
        try:
            user_name = message.from_user.first_name or ""
            username = message.from_user.username or "нет username"
            bot.send_message(ADMIN_CHAT_ID,
                f"🔔 Likee запрос!\n👤 {user_name} (@{username})\n🆔 ID: {message.from_user.id}\n🔗 {text[:100]}")
        except Exception as e:
            print(f"Ошибка отправки уведомления: {e}")

        keyboard = InlineKeyboardMarkup(row_width=2)
        btn_video = InlineKeyboardButton("🎬 Видео (MP4)", callback_data="yt_video")
        btn_audio = InlineKeyboardButton("🎵 Аудио (MP3)", callback_data="yt_audio")
        btn_support = InlineKeyboardButton("❤️ На чай  10 руб", callback_data="support")
        keyboard.add(btn_video, btn_audio, btn_support)
        bot.reply_to(message, "🎬 Likee обнаружен! Выбери формат:", reply_markup=keyboard)
        cleanup_user_data()
        user_data[message.chat.id] = {"type": "likee", "url": text, "timestamp": datetime.datetime.now()}
        return

    # --- ПРОВЕРКА НА TIKTOK ---
    if is_valid_tiktok_url(text):
        # Уведомление админу
        try:
            user_name = message.from_user.first_name or ""
            username = message.from_user.username or "нет username"
            bot.send_message(ADMIN_CHAT_ID,
                f"🔔 TikTok запрос!\n👤 {user_name} (@{username})\n🆔 ID: {message.from_user.id}\n🔗 {text[:100]}")
        except Exception as e:
            print(f"Ошибка отправки уведомления: {e}")

        keyboard = InlineKeyboardMarkup(row_width=2)
        btn_video = InlineKeyboardButton("🎬 Видео (MP4)", callback_data="yt_video")
        btn_audio = InlineKeyboardButton("🎵 Аудио (MP3)", callback_data="yt_audio")
        btn_support = InlineKeyboardButton("❤️ На чай  10 руб", callback_data="support")
        keyboard.add(btn_video, btn_audio, btn_support)
        bot.reply_to(message, "🎬 TikTok обнаружен! Выбери формат:", reply_markup=keyboard)
        cleanup_user_data()
        user_data[message.chat.id] = {"type": "tiktok", "url": text, "timestamp": datetime.datetime.now()}
        return

    print(
        f"[{datetime.datetime.now()}] Пользователь {message.from_user.id} (@{message.from_user.username}) отправил ссылку: {text[:100]}...")


    if not rec_id:
        # Уведомление админу о неизвестной ссылке
        try:
            user_name = message.from_user.first_name or ""
            username = message.from_user.username or "нет username"
            bot.send_message(ADMIN_CHAT_ID,
                f"⚠️ Неизвестная ссылка!\n👤 {user_name} (@{username})\n🆔 ID: {message.from_user.id}\n🔗 {text[:150]}")
        except Exception as e:
            print(f"Ошибка отправки уведомления: {e}")
        bot.reply_to(message, "❌ Не нашёл recordingId в ссылке. Убедись, что ссылка содержит 'recordingId='.")
        return

    # Уведомление админу о новом пользователе
    try:
        user_name = message.from_user.first_name or ""
        user_last = message.from_user.last_name or ""
        username = message.from_user.username or "нет username"
        full_name = f"{user_name} {user_last}".strip()
        notify_text = (
            f"🔔 Новый запрос!\n"
            f"👤 {full_name} (@{username})\n"
            f"🆔 ID: {message.from_user.id}\n"
            f"🔗 Recording: {rec_id}\n"
            f"💬 Chat ID: {message.chat.id}"
        )
        bot.send_message(ADMIN_CHAT_ID, notify_text)
    except Exception as e:
        print(f"Ошибка отправки уведомления: {e}")

    # Сохраняем ID пользователя
    cleanup_user_data()
    user_data[message.chat.id] = {"type": "starmaker", "rec_id": rec_id, "timestamp": datetime.datetime.now()}

    # Создаём кнопки
    keyboard = InlineKeyboardMarkup(row_width=2)
    btn_video = InlineKeyboardButton("🎬 Видео (MP4)", callback_data="video")
    btn_audio = InlineKeyboardButton("🎵 Аудио (MP3)", callback_data="audio")
    btn_support = InlineKeyboardButton("❤️ На чай  10 руб", callback_data="support")
    keyboard.add(btn_video, btn_audio, btn_support)

    bot.reply_to(
        message,
        f"✅ Нашёл \nЧто хочешь получить?",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


# ===== 5. Обработчик нажатий на кнопки =====
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    data = user_data.get(chat_id)

    # === Обработка «Я поделился!» ===
    if call.data == "share_done":
        try:
            add_credits(call.from_user.id, 5)
            credits = get_user_credits(call.from_user.id)
            bot.answer_callback_query(call.id, "✅ +3 скачивания!")
            bot.edit_message_text(
                f"🎉 Готово! Тебе начислено +3 скачивания!\n\n"
                f"Просто вставь ссылку 👇",
                chat_id=chat_id,
                message_id=call.message.message_id
            )
        except Exception as e:
            print(f"ОШИБКА share_done: {e}")
            bot.answer_callback_query(call.id, f"Ошибка: {e}")
        return

    # === Обработка YouTube / Rutube ===
    if call.data in ("yt_video", "yt_audio"):
        if not data or not isinstance(data, dict) or data.get("type") not in ("youtube", "rutube", "likee", "tiktok"):
            bot.answer_callback_query(call.id, "Сначала отправь ссылку!")
            return
        url = data["url"]
        fmt = "audio" if call.data == "yt_audio" else "video"
        bot.answer_callback_query(call.id, "Скачиваю...")
        bot.edit_message_text("⏳ Скачиваю...", chat_id=chat_id, message_id=call.message.message_id)
        try:
            # Для TikTok используем отдельную функцию для видео
            if data.get("type") == "tiktok" and fmt == "video":
                filepath, title = download_tiktok(url)
            else:
                filepath, title = download_youtube(url, fmt)
            if filepath is None:
                bot.send_message(chat_id, "❌ Не удалось скачать видео. Возможно, оно недоступно или требует авторизации.")
                user_data.pop(chat_id, None)
                return
            file_size_mb = round(os.path.getsize(filepath) / 1024 / 1024, 2)
            # Проверяем размер перед отправкой (админ без лимита)
            max_size = MAX_AUDIO_SIZE if fmt == "audio" else MAX_VIDEO_SIZE
            if os.path.getsize(filepath) > max_size and call.from_user.id != ADMIN_CHAT_ID:
                limit_mb = 20 if fmt == "audio" else 50
                bot.send_message(chat_id, f"❌ Файл слишком большой ({file_size_mb} МБ). Лимит Telegram: {limit_mb} МБ.")
                os.remove(filepath)
                user_data.pop(chat_id, None)
                return
            # Сжимаем видео если слишком большое (только для не-админа)
            if fmt == "video" and os.path.getsize(filepath) > MAX_VIDEO_SIZE:
                bot.send_message(chat_id, "⏳ Видео большое, сжимаю...")
                compressed_path = filepath.replace('.mp4', '_compressed.mp4')
                os.system(f'ffmpeg -i "{filepath}" -vf "scale=-2:480" -c:v libx264 -crf 28 -c:a aac -b:a 64k "{compressed_path}" -y 2>/dev/null')
                if os.path.exists(compressed_path) and os.path.getsize(compressed_path) > 0:
                    os.remove(filepath)
                    filepath = compressed_path
                    file_size_mb = round(os.path.getsize(filepath) / 1024 / 1024, 2)

            with open(filepath, 'rb') as f:
                if fmt == "audio":
                    bot.send_audio(chat_id, f, caption=f"🎵 {title}")
                else:
                    bot.send_video(chat_id, f, caption=f"🎬 {title}", supports_streaming=True)
            # Списываем кредит и записываем загрузку
            use_credit(call.from_user.id)
            record_download(call.from_user.id, data.get("type", "youtube"), fmt, title, file_size_mb, url)
            user = get_or_create_user(call.from_user.id)
            if user['total_downloads'] > 5:
                remaining = get_user_credits(call.from_user.id)
                bot.send_message(chat_id, f"✅ Скачано! Осталось скачиваний: {remaining}")
            else:
                bot.send_message(chat_id, "✅ Скачано!")
            os.remove(filepath)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка: {e}")
        user_data.pop(chat_id, None)
        return

    # === Обработка StarMaker ===
    if not data or not isinstance(data, dict) or data.get("type") != "starmaker":
        bot.answer_callback_query(call.id, "Сначала отправь ссылку!")
        return
    rec_id = data.get("rec_id")

    # Сообщаем о начале обработки
    bot.answer_callback_query(call.id, "Начинаю обработку...")
    bot.edit_message_text(
        f"⏳ Обрабатываю запрос для ID: {rec_id}",
        chat_id=chat_id,
        message_id=call.message.message_id
    )

    video_url = f"https://static.smoutro.com/production/uploading/recordings/{rec_id}/master.mp4"

    if call.data == "video":
        bot.send_message(chat_id, "📥 Скачиваю видео...")
        video_data = download_file(video_url)

        if video_data is None:
            bot.send_message(chat_id, "❌ Не удалось скачать видео. Возможно, файл не существует.")
            return

        if len(video_data) > MAX_VIDEO_SIZE and call.from_user.id != ADMIN_CHAT_ID:
            bot.send_message(chat_id, f"❌ Файл слишком большой ({round(len(video_data)/1024/1024, 1)} МБ). Лимит Telegram: 50 МБ.")
            user_data.pop(chat_id, None)
            return

        try:
            bot.send_video(chat_id, video_data, caption=f"🎬 Вот твоё видео! ")
            # Списываем кредит и записываем загрузку
            file_size_mb = round(len(video_data) / 1024 / 1024, 2)
            use_credit(call.from_user.id)
            record_download(call.from_user.id, "starmaker", "video", f"StarMaker #{rec_id}", file_size_mb, video_url)
            user = get_or_create_user(call.from_user.id)
            if user['total_downloads'] > 5:
                remaining = get_user_credits(call.from_user.id)
                bot.send_message(chat_id, f"✅ Скачано! Осталось скачиваний: {remaining}")
            else:
                bot.send_message(chat_id, "✅ Скачано!")

        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка при отправке видео: {e}")
        finally:
            del video_data

    elif call.data == "audio":
        try:
            from pydub import AudioSegment
            import io

            bot.send_message(chat_id, "🎵 Скачиваю и конвертирую в MP3...")
            video_data = download_file(video_url)
            if video_data is None:
                bot.send_message(chat_id, "❌ Не удалось скачать видео.")
                return

            audio = AudioSegment.from_file(io.BytesIO(video_data), format="mp4")
            audio_bytes = io.BytesIO()
            audio.export(audio_bytes, format="mp3", bitrate="128k")
            audio_bytes.seek(0)
            
            if len(audio_bytes.getvalue()) > MAX_AUDIO_SIZE:
                bot.send_message(chat_id, f"❌ Аудио слишком большое ({round(len(audio_bytes.getvalue())/1024/1024, 1)} МБ). Лимит Telegram: 20 МБ.")
                user_data.pop(chat_id, None)
                return
            
            tmp_path = f"/tmp/starmaker_{rec_id}.mp3"
            with open(tmp_path, "wb") as tmp:
                tmp.write(audio_bytes.getvalue())
            with open(tmp_path, "rb") as tmp:
                bot.send_audio(chat_id, tmp, caption=f"🎵 Вот твоё аудио!", title=f"StarMaker #{rec_id}")
            os.remove(tmp_path)
            # Списываем кредит и записываем загрузку
            file_size_mb = round(len(audio_bytes.getvalue()) / 1024 / 1024, 2)
            use_credit(call.from_user.id)
            record_download(call.from_user.id, "starmaker", "audio", f"StarMaker #{rec_id}", file_size_mb, video_url)
            user = get_or_create_user(call.from_user.id)
            if user['total_downloads'] > 5:
                remaining = get_user_credits(call.from_user.id)
                bot.send_message(chat_id, f"✅ Скачано! Осталось скачиваний: {remaining}")
            else:
                bot.send_message(chat_id, "✅ Скачано!")

            # Очистка
            del audio
            del audio_bytes
            del video_data

        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка конвертации: {e}")
    elif call.data == "support":
        # Вместо bot.send_message(chat_id, SUPPORT_TEXT)
        with open('sber-phone-qr1.jpg', 'rb') as photo:
            bot.send_photo(chat_id, photo, caption=f"❤️ {SUPPORT_TEXT}!")
        #bot.send_message(chat_id, SUPPORT_TEXT)
    # Очищаем данные после обработки
    user_data.pop(chat_id, None)


# ===== 6. Запуск бота =====
if __name__ == "__main__":
    import sys
    print("🚀 Бот запущен и готов к работе!", flush=True)
    # Сбрасываем offset чтобы не застревал
    try:
        bot.get_updates(offset=-1, timeout=1)
        print("✅ Offset сброшен", flush=True)
    except:
        pass
    bot.polling(none_stop=True, timeout=30, long_polling_timeout=30)
