import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import datetime
import gc   # для очищения памяти
# for you tube
import yt_dlp
# для базы данных
import sqlite3
# ===== 1. Токен бота =====
import os
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
bot = telebot.TeleBot(TOKEN)

# ===== Временное хранилище для recordingId (связываем с chat_id) =====
user_data = {}
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
        c.execute("INSERT INTO users (user_id, username, credits) VALUES (?, ?, 5)",
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

def add_credits(user_id, amount=5):
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
    """Скачивает YouTube видео/аудио через yt_dlp. Возвращает (путь, название)."""
    ydl_opts = {
        'format': 'best[height<=720]' if format_type == "video" else 'bestaudio/best',
        'outtmpl': '/tmp/yt_%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
    }
    if format_type == "audio":
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        ext = 'mp3' if format_type == "audio" else info.get('ext', 'mp4')
        filepath = f"/tmp/yt_{info['id']}.{ext}"
        title = info.get('title', 'YouTube Video')
        return filepath, title


# ===== 2. Функция, которая вытаскивает recordingId из текста =====
def extract_recording_id(text):
    """Ищет в тексте recordingId=число и возвращает число или None."""
    match = re.search(r'recordingId=(\d+)', text)
    return match.group(1) if match else None


# ===== 3. Функция скачивания файла по ссылке =====
def download_file(url):
    """Скачивает файл и возвращает его содержимое (байты) или None."""
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            return response.content
        else:
            return None
    except Exception as e:
        print("Ошибка при скачивании:", e)
        return None


# ===== 4. Обработчик команды /start =====
@bot.message_handler(commands=['start'])
def start_message(message):
    user = get_or_create_user(message.from_user.id, message.from_user.username)
    bot.reply_to(message, "*Просто вставь сюда ссылку*", parse_mode="Markdown")


# ===== 4.1 Обработчик команды /share =====
@bot.message_handler(commands=['share'])
def share_message(message):
    print(f"DEBUG: /share получен от {message.from_user.id}", flush=True)
    with open('/root/share_debug.txt', 'a') as f:
        f.write(f"\n[{datetime.datetime.now()}] /share от {message.from_user.id}")
    keyboard = InlineKeyboardMarkup(row_width=1)
    btn_share = InlineKeyboardButton("📢 Поделиться ботом", url="https://t.me/share/url?url=https://t.me/freeStarmakerBot&text=Попробуй этого бота для скачивания видео и музыки!")
    btn_done = InlineKeyboardButton("✅ Я поделился! (+5 скачиваний)", callback_data="share_done")
    keyboard.add(btn_share, btn_done)
    bot.reply_to(message,
        "📢 Поделись ботом с друзьями!\n\n"
        "1. Нажми «Поделиться ботом»\n"
        "2. Выбери кому отправить\n"
        "3. Вернись сюда и нажми «Я поделился!»\n\n"
        "🎁 Получишь +5 скачиваний!",
        reply_markup=keyboard)


# ===== 5. Обработчик текстовых сообщений =====
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    # DEBUG: логируем ВСЕ сообщения
    with open('/root/share_debug.txt', 'a') as f:
        f.write(f"\n[{datetime.datetime.now()}] MSG: {message.text} от {message.from_user.id}")
    print(f"DEBUG MSG: {message.text} от {message.from_user.id}", flush=True)
    text = message.text
    rec_id = extract_recording_id(text)
    if not text:
        bot.reply_to(message, "Пришли ссылку ")
        return

    # Регистрируем/получаем пользователя и проверяем кредиты
    user = get_or_create_user(message.from_user.id, message.from_user.username)
    if user['credits'] <= 0:
        bot.reply_to(message,
            "😔 У тебя закончились скачивания!\n\n"
            "📢 Поделись ботом с друзьями, чтобы получить +5:\n"
            "   → Нажми кнопку «Поделиться» ниже\n\n"
            "Или подожди завтра (лимит сбрасывается)",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("📢 Поделиться ботом", url="https://t.me/share/url?url=https://t.me/freeStarmakerBot&text=Попробуй этого бота для скачивания видео и музыки!")
            ))
        return

    # --- ПРОВЕРКА НА YOUTUBE ---
    if 'youtube.com' in text or 'youtu.be' in text:
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
        user_data[message.chat.id] = {"type": "youtube", "url": text}
        return

    print(
        f"[{datetime.datetime.now()}] Пользователь {message.from_user.id} (@{message.from_user.username}) отправил ссылку: {text[:100]}...")


    if not rec_id:
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
    user_data[message.chat.id] = rec_id

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
    print(f"[1 заход-] CALLBACK: {call.data} от {call.from_user.id}", flush=True)
    # DEBUG: записываем ВСЕ callbacks
    with open('/root/share_debug.txt', 'a') as f:
        f.write(f"\n[{datetime.datetime.now()}] CALLBACK: {call.data} от {call.from_user.id}")

    # === Обработка «Я поделился!» ===
    if call.data == "share_done":
        try:
            # DEBUG: записываем в файл что callback сработал
            with open('/root/share_debug.txt', 'w') as f:
                f.write(f"1 - callback share_done сработал! user={call.from_user.id} time={datetime.datetime.now()}")
            print(f"DEBUG: share_done callback получен от {call.from_user.id}", flush=True)
            add_credits(call.from_user.id, 5)
            credits = get_user_credits(call.from_user.id)
            bot.answer_callback_query(call.id, "✅ +5 скачиваний!")
            bot.edit_message_text(
                f"🎉 Готово! Тебе начислено +5 скачиваний!\n\n"
                f"Просто вставь ссылку 👇",
                chat_id=chat_id,
                message_id=call.message.message_id
            )
        except Exception as e:
            print(f"ОШИБКА share_done: {e}", flush=True)
            with open('/root/share_debug.txt', 'w') as f:
                f.write(f"ОШИБКА: {e}")
            bot.answer_callback_query(call.id, f"Ошибка: {e}")
        return

    # === Обработка YouTube ===
    if call.data in ("yt_video", "yt_audio"):
        if not data or not isinstance(data, dict) or data.get("type") != "youtube":
            bot.answer_callback_query(call.id, "Сначала отправь YouTube ссылку!")
            return
        url = data["url"]
        fmt = "audio" if call.data == "yt_audio" else "video"
        bot.answer_callback_query(call.id, "Скачиваю...")
        bot.edit_message_text("⏳ Скачиваю с YouTube...", chat_id=chat_id, message_id=call.message.message_id)
        try:
            filepath, title = download_youtube(url, fmt)
            file_size_mb = round(os.path.getsize(filepath) / 1024 / 1024, 2)
            with open(filepath, 'rb') as f:
                if fmt == "audio":
                    bot.send_audio(chat_id, f, caption=f"🎵 {title}")
                else:
                    bot.send_video(chat_id, f, caption=f"🎬 {title}", supports_streaming=True)
            # Списываем кредит и записываем загрузку
            use_credit(call.from_user.id)
            record_download(call.from_user.id, "youtube", fmt, title, file_size_mb, url)
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
    rec_id = data if isinstance(data, str) else None
    if not rec_id:
        bot.answer_callback_query(call.id, "Сначала отправь ссылку!")
        return

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
            gc.collect()

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
            bot.send_audio(chat_id, audio_bytes, caption=f"🎵 Вот твоё аудио!")
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
            gc.collect()

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
    bot.polling(none_stop=True, timeout=2, long_polling_timeout=2)
