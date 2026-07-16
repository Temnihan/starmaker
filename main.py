import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ===== 1. Токен бота =====
import os
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
bot = telebot.TeleBot(TOKEN)

# ===== Временное хранилище для recordingId (связываем с chat_id) =====
user_data = {}


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
    if not text:
        bot.reply_to(message, "Пришли ссылку на запись StarMaker.")
        return

    rec_id = extract_recording_id(text)
    if not rec_id:
        bot.reply_to(message, "❌ Не нашёл recordingId в ссылке. Убедись, что ссылка содержит 'recordingId='.")
        return

    # Сохраняем ID пользователя
    user_data[message.chat.id] = rec_id

    # Создаём кнопки
    keyboard = InlineKeyboardMarkup()
    btn_video = InlineKeyboardButton("🎬 Видео (MP4)", callback_data="video")
    btn_audio = InlineKeyboardButton("🎵 Аудио (MP3)", callback_data="audio")
    keyboard.add(btn_video, btn_audio)

    bot.reply_to(
        message,
        f"✅ Нашёл recordingId: `{rec_id}`\nЧто хочешь получить?",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


# ===== 5. Обработчик нажатий на кнопки =====
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    rec_id = user_data.get(chat_id)

    if not rec_id:
        bot.answer_callback_query(call.id, "Сначала отправь ссылку с recordingId!")
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
            bot.send_video(chat_id, video_data, caption="🎬 Вот твоё видео!")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка при отправке видео: {e}")

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
            bot.send_audio(chat_id, audio_bytes, caption="🎵 Вот твоё аудио!")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка конвертации: {e}")

    # Очищаем данные после обработки
    user_data.pop(chat_id, None)


# ===== 6. Запуск бота =====
if __name__ == "__main__":
    print("🚀 Бот запущен и готов к работе!")
    bot.polling(none_stop=True)
