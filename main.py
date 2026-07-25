import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import datetime
import gc   # для очищения памяти
# for you tube
import yt_dlp
# ===== 1. Токен бота =====
import os
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
bot = telebot.TeleBot(TOKEN)

# ===== Временное хранилище для recordingId (связываем с chat_id) =====
user_data = {}
SUPPORT_TEXT = "Ваша поддержка — лучшая благодарность. \n🧡)"
ADMIN_CHAT_ID = 158043939  # Твой Telegram ID для уведомлений


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


# ===== 4. Обработчик текстовых сообщений =====
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text
    rec_id = extract_recording_id(text)
    if not text:
        bot.reply_to(message, "Пришли ссылку ")
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
    print(f"[{datetime.datetime.now()}] Пользователь {call.from_user.id} запросил {call.data}")

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
            with open(filepath, 'rb') as f:
                if fmt == "audio":
                    bot.send_audio(chat_id, f, caption=f"🎵 {title}")
                else:
                    bot.send_video(chat_id, f, caption=f"🎬 {title}", supports_streaming=True)
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
    print("🚀 Бот запущен и готов к работе!")
    bot.polling(none_stop=True)
